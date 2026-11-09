"""点击验证码 LLM 解算器（默认火山引擎豆包，支持任意 OpenAI 兼容接口）。"""

import base64
import io
import json
import logging
import os
import re
import threading
import time
from typing import List, Optional, Tuple
from urllib.parse import unquote

import requests
from PIL import Image
from openai import BadRequestError, OpenAI

logger = logging.getLogger(__name__)

DEFAULT_LLM_MODEL = "doubao-seed-2-0-pro-260215"
DEFAULT_LLM_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


def llm_api_key() -> str:
    return os.getenv("LLM_API_KEY", "").strip()


def llm_model() -> str:
    return os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL).strip() or DEFAULT_LLM_MODEL


def llm_base_url() -> str:
    return os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL).strip() or DEFAULT_LLM_BASE_URL


def _env_number(name: str, cast):
    """读取可选的数字配置；未配置或格式错误时返回 None（沿用默认行为）。"""
    raw = os.getenv(name, "").strip().strip('"').strip("'")
    if not raw:
        return None
    try:
        value = cast(raw)
    except ValueError:
        logger.warning("%s=%r 不是有效数字，已忽略", name, raw)
        return None
    return value if value >= 0 else None


def llm_timeout() -> Optional[float]:
    """LLM_TIMEOUT：单次请求超时秒数，未配置时沿用 openai 库默认值（600 秒）。"""
    value = _env_number("LLM_TIMEOUT", float)
    return value if value else None


def llm_max_retries() -> Optional[int]:
    """LLM_MAX_RETRIES：失败自动重试次数，未配置时沿用 openai 库默认值（2 次）。"""
    return _env_number("LLM_MAX_RETRIES", int)


def llm_max_tokens(default: int) -> int:
    """LLM_MAX_TOKENS：最大输出 token 数，未配置时使用调用处的默认值。"""
    value = _env_number("LLM_MAX_TOKENS", int)
    return value if value else default


def create_llm_client(api_key: str, base_url: Optional[str] = None) -> OpenAI:
    """按 LLM_* 配置创建 OpenAI 兼容客户端。"""
    kwargs = {"base_url": base_url or llm_base_url(), "api_key": api_key}
    timeout = llm_timeout()
    if timeout is not None:
        kwargs["timeout"] = timeout
    max_retries = llm_max_retries()
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    return OpenAI(**kwargs)


def create_chat_completion(client: OpenAI, **kwargs):
    """调用 chat.completions；部分模型不接受 max_tokens 时，自动改用 max_completion_tokens 重试。"""
    try:
        return client.chat.completions.create(**kwargs)
    except BadRequestError as exc:
        if "max_tokens" not in kwargs or "max_completion_tokens" not in str(exc):
            raise
        logger.info("模型不支持 max_tokens 参数，改用 max_completion_tokens 重试")
        kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        return client.chat.completions.create(**kwargs)


def _mask_api_key(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def _wait_heartbeat(stop: threading.Event, label: str) -> None:
    start = time.monotonic()
    while not stop.wait(5):
        elapsed = int(time.monotonic() - start)
        logger.info("%s推理中，已等待 %ss...", label, elapsed)


class ClickCaptchaSolver:
    """基于大模型的点击/滑块验证码解算器。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = (api_key or llm_api_key()).strip()
        self.model = model or llm_model()
        self.base_url = base_url or llm_base_url()
        self._client: Optional[OpenAI] = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("LLM_API_KEY 未设置，无法使用 LLM 验证码识别")
            self._client = create_llm_client(self.api_key, self.base_url)
        return self._client

    def solve(
        self, ref_url: str, main_url: str, main_width: int, main_height: int
    ) -> List[Tuple[int, int]]:
        t0 = time.monotonic()
        logger.info(
            "开始大模型点选解算: model=%s, endpoint=%s, 主图=%sx%s",
            self.model,
            self.base_url,
            main_width,
            main_height,
        )

        logger.info("步骤 1/4: 下载参考图标条...")
        ref_raw = self._download(ref_url)
        if not ref_raw:
            return []
        logger.info("参考图标条已下载 (%s bytes, %.1fs)", len(ref_raw), time.monotonic() - t0)

        logger.info("步骤 2/4: 拆分参考图标...")
        icon_uris = self._split_strip(ref_raw)
        if len(icon_uris) < 3:
            return []
        logger.info("已拆分 %s 个参考图标 (%.1fs)", len(icon_uris), time.monotonic() - t0)

        logger.info("步骤 3/4: 下载主图并编码...")
        main_raw = self._download(main_url)
        if not main_raw:
            return []
        main_uri = "data:image/png;base64," + base64.b64encode(main_raw).decode("ascii")
        logger.info("主图已下载 (%s bytes, %.1fs)", len(main_raw), time.monotonic() - t0)

        logger.info("步骤 4/4: 调用大模型识别坐标 (key=%s)...", _mask_api_key(self.api_key))
        coords = self._find_all_icons(icon_uris, main_uri, main_width, main_height)
        logger.info(
            "大模型点选解算完成: 返回 %s 个坐标, 总耗时 %.1fs",
            len(coords),
            time.monotonic() - t0,
        )
        if len(coords) < 2:
            return []

        return [
            (max(0, min(x, main_width - 1)), max(0, min(y, main_height - 1)))
            for x, y in coords
        ]

    def _download(self, url: str) -> Optional[bytes]:
        source = "data URI" if url.startswith("data:") else url[:80]
        try:
            if url.startswith("data:"):
                _, encoded = url.split(",", 1)
                try:
                    data = base64.b64decode(encoded)
                except Exception:
                    data = base64.b64decode(unquote(encoded))
                logger.debug("图片下载完成: %s (%s bytes)", source, len(data))
                return data
            logger.debug("正在下载: %s...", source)
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                logger.debug("图片下载完成: HTTP 200 (%s bytes)", len(resp.content))
                return resp.content
            logger.error("下载验证码图片失败: HTTP %s, url=%s", resp.status_code, source)
            return None
        except Exception as exc:
            logger.error("下载验证码图片错误 (%s): %s", source, exc)
            return None

    def _split_strip(self, raw: bytes) -> List[str]:
        try:
            img = Image.open(io.BytesIO(raw))
            w, h = img.size
            logger.info("参考图标条尺寸: %sx%s", w, h)

            part_w = w // 3
            uris = []
            for i in range(3):
                left = i * part_w
                right = (i + 1) * part_w if i < 2 else w
                icon = img.crop((left, 0, right, h))
                icon = icon.resize((icon.width * 3, icon.height * 3), Image.LANCZOS)
                buf = io.BytesIO()
                icon.save(buf, format="PNG")
                uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
                uris.append(uri)
                logger.info("参考图标 #%s: 放大后 %sx%s", i + 1, icon.width, icon.height)
            return uris
        except Exception as exc:
            logger.error("拆分参考图标条失败: %s", exc)
            return []

    def _call_chat(self, content: list, *, json_mode: bool, label: str) -> str:
        messages = [{"role": "user", "content": content}]
        kwargs = {"model": self.model, "messages": messages, "max_tokens": llm_max_tokens(4096)}
        if json_mode:
            kwargs["messages"] = [
                {"role": "system", "content": "Output valid JSON only. No markdown, no explanation."},
                {"role": "user", "content": content},
            ]
            kwargs["response_format"] = {"type": "json_object"}

        mode = "JSON" if json_mode else "普通"
        logger.info(
            "正在请求大模型 API (%s 模式): %s/chat/completions, model=%s",
            mode,
            self.base_url.rstrip("/"),
            self.model,
        )

        stop = threading.Event()
        heartbeat = threading.Thread(
            target=_wait_heartbeat, args=(stop, "大模型"), daemon=True
        )
        heartbeat.start()
        t0 = time.monotonic()
        try:
            response = create_chat_completion(self.client, **kwargs)
            output = response.choices[0].message.content or ""
            # 打印 Request ID，便于向大模型服务商排查慢响应问题
            request_id = getattr(response, "id", None) or \
                         getattr(response, "_request_id", None) or "unknown"
            elapsed = time.monotonic() - t0
            logger.info("大模型 API 响应完成 (%.1fs) | Request-ID: %s", elapsed, request_id)
            if elapsed > 30:
                logger.warning("大模型响应过慢 (%.1fs)，Request-ID: %s，可凭此向服务商排查", elapsed, request_id)
            return output
        finally:
            stop.set()

    def _find_all_icons(
        self,
        icon_uris: List[str],
        main_uri: str,
        main_width: int,
        main_height: int,
    ) -> List[Tuple[int, int]]:
        prompt = (
            f"大图（{main_width}×{main_height}像素）是一个图标网格。\n"
            "找到3个参考图标(A, B, C)各自在大图网格中的位置。\n"
            "匹配规则：形状和颜色必须一致，空心/实心、线条粗细是关键区分点，允许旋转。\n\n"
            '输出JSON：{"coords":[[xA,yA],[xB,yB],[xC,yC]]}\n'
            "其中x、y为图标中心的比例坐标（0~1）。"
        )

        content = []
        labels = ["A", "B", "C"]
        for i, uri in enumerate(icon_uris[:3]):
            content.append({"type": "image_url", "image_url": {"url": uri}})
            content.append({"type": "text", "text": f"参考图标{labels[i]}"})
        content.append({"type": "image_url", "image_url": {"url": main_uri}})
        content.append({"type": "text", "text": prompt})

        try:
            output = self._call_chat(content, json_mode=True, label="点选")
            logger.info("大模型响应: %s", output[:400])
            coords = self._parse_coordinates(output, main_width, main_height)
            if coords:
                return coords
            logger.warning("JSON 模式响应无法解析坐标，尝试普通模式")
        except Exception as exc:
            logger.warning("JSON 模式调用失败，尝试普通模式: %s", exc)

        return self._find_all_icons_fallback(content, main_width, main_height)

    def _find_all_icons_fallback(
        self, content: list, main_width: int, main_height: int
    ) -> List[Tuple[int, int]]:
        try:
            output = self._call_chat(content, json_mode=False, label="点选")
            logger.info("大模型响应(普通模式): %s", output[:400])
            return self._parse_coordinates(output, main_width, main_height)
        except Exception as exc:
            logger.error("大模型调用失败: %s", exc)
            return []

    def _parse_coordinates(
        self, text: str, main_width: int, main_height: int
    ) -> List[Tuple[int, int]]:
        match = re.search(r'\{.*"coords"\s*:\s*\[.*?\]\s*\}', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                result = []
                for x, y in data["coords"]:
                    x, y = float(x), float(y)
                    if max(x, y) <= 1.5:
                        result.append((round(x * main_width), round(y * main_height)))
                    else:
                        result.append((round(x), round(y)))
                return result
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass

        coords = []
        paren_pairs = re.findall(r"\(\s*(\d+\.?\d*)\s*[,，]\s*(\d+\.?\d*)\s*\)", text)
        for x_str, y_str in paren_pairs:
            coords.append((float(x_str), float(y_str)))

        if not coords:
            nums = re.findall(r"(\d+\.?\d+)", text)
            for i in range(0, len(nums) - 1, 2):
                coords.append((float(nums[i]), float(nums[i + 1])))

        result = []
        for x, y in coords[:3]:
            max_val = max(x, y)
            if max_val <= 1.5:
                result.append((round(x * main_width), round(y * main_height)))
            else:
                result.append((round(x), round(y)))
        return result
