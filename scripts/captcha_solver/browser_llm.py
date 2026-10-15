"""Selenium 集成层 - 在浏览器中通过大模型解算腾讯验证码（点击 + 滑块）。"""

import base64
import io
import logging
import os
import random
import re
import time
from typing import Optional, Tuple
from urllib.parse import urlparse

import requests
from PIL import Image
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from captcha_solver.llm_solver import ClickCaptchaSolver, llm_api_key, llm_base_url, llm_model

logger = logging.getLogger(__name__)

TENCENT_SELECTORS = {
    "content": "#tCaptchaDyContent",
    "header_answer_img": ".tencent-captcha-dy__header-answer img",
    "point_area": ".tencent-captcha-dy__point-area",
    "click_type_wrap": ".tencent-captcha-dy__click-type-wrap",
    "image_area": ".tencent-captcha-dy__verify-bg-img",
    "verify_bg_img": ".tencent-captcha-dy__verify-bg-img",
    "verify_bg": ".tencent-captcha-dy__verify-bg",
    "refresh_btn": ".tencent-captcha-dy__footer-icon--refresh",
    "confirm_btn": ".tencent-captcha-dy__verify-confirm-btn",
    "slider_area": ".tencent-captcha-dy__verify-slider-area",
    "slider_groove": ".tencent-captcha-dy__slider-groove",
    "slider_block": ".tencent-captcha-dy__slider-block",
    "slider_bg_img": ".tencent-captcha-dy__slider-bg-img",
}

_WIDGET_SELECTORS = [
    ".tencent-captcha-dy__warp",
    ".tencent-captcha-dy__wrapper",
    ".tencent-captcha__wrapper",
    ".tencent-captcha-dy__body-wrap",
    "#tCaptchaDyContent",
]


def solve_captcha_in_browser(
    driver: WebDriver,
    timeout: int = 15,
    max_retries: int = 3,
    selectors: dict = None,
    solver: ClickCaptchaSolver = None,
) -> bool:
    """在浏览器中处理验证码，返回是否通过。"""
    selectors = selectors or TENCENT_SELECTORS
    solver = solver or ClickCaptchaSolver()
    if not solver.api_key:
        raise RuntimeError("LLM_API_KEY 未设置，无法使用 LLM 验证码识别")

    implicit_wait_backup = None
    try:
        implicit_wait_backup = driver.timeouts.implicit_wait
    except Exception:
        pass

    for attempt in range(max_retries):
        try:
            logger.info("验证码尝试 %s/%s", attempt + 1, max_retries)

            if not _wait_for_captcha(driver, timeout):
                logger.warning("验证码未出现")
                continue

            captcha_type = _detect_captcha_type_js(driver)
            logger.info("验证码类型: %s", captcha_type)

            if captcha_type == "slider":
                if _solve_slider(driver, selectors):
                    logger.info("滑块验证码已解算")
                    if implicit_wait_backup is not None:
                        try:
                            driver.implicitly_wait(implicit_wait_backup)
                        except Exception:
                            pass
                    return True
                _refresh_captcha(driver, selectors)
                time.sleep(2)
                continue

            if captcha_type != "click":
                for refresh_i in range(5):
                    logger.info("获取到 %s，正在刷新 (%s/5)...", captcha_type, refresh_i + 1)
                    _refresh_captcha(driver, selectors)
                    time.sleep(2)
                    captcha_type = _detect_captcha_type_js(driver)
                    logger.info("刷新后验证码类型: %s", captcha_type)
                    if captcha_type == "click":
                        break
                    if captcha_type == "slider":
                        if _solve_slider(driver, selectors):
                            logger.info("刷新后滑块已解算")
                            if implicit_wait_backup is not None:
                                try:
                                    driver.implicitly_wait(implicit_wait_backup)
                                except Exception:
                                    pass
                            return True
                if captcha_type != "click":
                    continue

            ref_url = _extract_ref_url(driver, selectors)
            main_url, main_size = _extract_main_url(driver, selectors)

            if not ref_url or not main_url or not main_size:
                logger.warning("提取验证码图片 URL 失败，正在刷新...")
                _refresh_captcha(driver, selectors)
                time.sleep(1)
                continue

            logger.info("主图尺寸=%s", main_size)
            _save_debug_images(ref_url, main_url)

            logger.info(
                "调用大模型解算点选验证码 (model=%s, endpoint=%s)...",
                llm_model(),
                llm_base_url(),
            )
            coords = solver.solve(ref_url, main_url, main_size[0], main_size[1])
            if not coords or len(coords) < 2:
                logger.warning("大模型仅返回 %s 个坐标，正在刷新...", len(coords or []))
                _refresh_captcha(driver, selectors)
                time.sleep(1)
                continue
            logger.info("大模型坐标: %s", coords)

            expected_aspect = main_size[0] / main_size[1]
            image_el = _find_main_image_element(driver, selectors, expected_aspect)
            if image_el is None:
                logger.error("找不到主图元素")
                continue

            rect = driver.execute_script(
                "var r = arguments[0].getBoundingClientRect();"
                "return {x: r.x, y: r.y, w: r.width, h: r.height};",
                image_el,
            )
            if rect["h"] < 10:
                image_el = _find_element(driver, selectors.get("image_area"))
                if image_el is None:
                    continue
                rect = driver.execute_script(
                    "var r = arguments[0].getBoundingClientRect();"
                    "return {x: r.x, y: r.y, w: r.width, h: r.height};",
                    image_el,
                )

            scale_x = rect["w"] / main_size[0]
            scale_y = rect["h"] / main_size[1]
            logger.info("图片区域: rect=%s, 缩放=(%.3f, %.3f)", rect, scale_x, scale_y)

            for i, (cx, cy) in enumerate(coords[:3]):
                px = cx * scale_x
                py = cy * scale_y
                offset_x = int(px - rect["w"] / 2)
                offset_y = int(py - rect["h"] / 2)
                logger.info("点击 #%s: 像素=(%s,%s) -> 偏移=(%s,%s)", i + 1, cx, cy, offset_x, offset_y)
                _click_with_actions(driver, image_el, offset_x, offset_y)
                time.sleep(random.uniform(0.25, 0.55))

            time.sleep(1)

            confirm_btn = _find_element(driver, selectors.get("confirm_btn"))
            if confirm_btn is not None and confirm_btn.is_displayed():
                try:
                    WebDriverWait(driver, 3).until(
                        lambda _d: "disabled" not in (confirm_btn.get_attribute("class") or "")
                    )
                    logger.info("确认按钮已启用，正在点击...")
                    driver.execute_script("arguments[0].click();", confirm_btn)
                    time.sleep(2)
                except Exception:
                    logger.info("点击后确认按钮仍为禁用状态")

            time.sleep(2)
            if _check_passed(driver, selectors):
                logger.info("验证码已通过")
                if implicit_wait_backup is not None:
                    try:
                        driver.implicitly_wait(implicit_wait_backup)
                    except Exception:
                        pass
                return True

            logger.info("未通过，正在刷新...")
            _refresh_captcha(driver, selectors)
            time.sleep(1)
        except StaleElementReferenceException:
            # 验证码 DOM 被重新渲染（验证已完成或自动换了一张图），不能直接当失败退出
            logger.warning("验证码元素已失效（页面已刷新或验证已完成），重新检查是否通过...")
            time.sleep(2)
            if _check_passed(driver, selectors):
                logger.info("验证码已通过")
                if implicit_wait_backup is not None:
                    try:
                        driver.implicitly_wait(implicit_wait_backup)
                    except Exception:
                        pass
                return True
            logger.info("验证码仍未通过，继续下一次尝试")
            continue

    logger.error("所有重试后验证码解算失败")
    if implicit_wait_backup is not None:
        try:
            driver.implicitly_wait(implicit_wait_backup)
        except Exception:
            pass
    return False


def _solve_slider(driver: WebDriver, selectors: dict) -> bool:
    """使用 LLM 解算滑块验证码。"""
    bg_el = _find_element(driver, ".tencent-captcha-dy__slider-bg-img", wait=1.0)
    if bg_el is None:
        bg_el = _find_element(driver, selectors.get("verify_bg_img"), wait=1.0)
    if bg_el is None:
        logger.warning("找不到滑块背景图片")
        return False

    bg_url = None
    tag = (bg_el.tag_name or "").lower()
    if tag == "img":
        bg_url = bg_el.get_attribute("src") or ""
    if not bg_url or not bg_url.startswith("http"):
        style = bg_el.get_attribute("style") or ""
        m = re.search(r'url\(["\']?(https?://[^"\')\s]+)["\']?\)', style)
        if m:
            bg_url = m.group(1)

    if not bg_url:
        try:
            bg_bytes = bg_el.screenshot_as_png
            bg_url = "data:image/png;base64," + base64.b64encode(bg_bytes).decode()
        except Exception as exc:
            logger.error("无法获取滑块背景图片，错误详情: %s", exc)
            return False

    groove = _find_element(driver, selectors.get("slider_groove"), wait=1.0)
    slider_block = _find_element(driver, selectors.get("slider_block"), wait=1.0)
    if groove is None or slider_block is None:
        logger.warning("找不到滑块轨道/滑块块")
        return False

    groove_width = groove.size.get("width", 300)
    logger.info("滑块轨道宽度: %s", groove_width)

    api_key = llm_api_key()
    if not api_key:
        logger.error("LLM_API_KEY 未设置，无法解算滑块验证码")
        return False

    try:
        from openai import OpenAI

        logger.info(
            "调用大模型解算滑块验证码 (model=%s, endpoint=%s)...",
            llm_model(),
            llm_base_url(),
        )
        client = OpenAI(
            base_url=llm_base_url(),
            api_key=api_key,
        )

        if bg_url.startswith("http"):
            resp = requests.get(bg_url, timeout=15)
            bg_data = resp.content
        elif bg_url.startswith("data:"):
            _, encoded = bg_url.split(",", 1)
            bg_data = base64.b64decode(encoded)
        else:
            return False

        bg_uri = "data:image/png;base64," + base64.b64encode(bg_data).decode()
        img = Image.open(io.BytesIO(bg_data))
        bg_w, bg_h = img.size
        model = llm_model()
        logger.info("正在请求大模型 API 识别滑块缺口 (model=%s)...", model)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": bg_uri}},
                        {
                            "type": "text",
                            "text": (
                                f"这是一个滑块拼图验证码的背景图（{bg_w}x{bg_h}像素）。\n"
                                "图中有一个矩形缺口（拼图块被挖掉的位置），缺口边缘有轻微阴影或颜色差异。\n"
                                "请找到这个缺口，返回缺口左侧边缘的X坐标比例（0~1之间）。\n"
                                "输出格式（仅一个数字）：0.XX"
                            ),
                        },
                    ],
                }
            ],
            max_tokens=50,
        )

        output = response.choices[0].message.content or ""
        logger.info("滑块大模型响应: %s", output[:100])

        nums = re.findall(r"(\d+\.?\d*)", output)
        if not nums:
            logger.warning("无法从大模型解析滑块位置")
            return False
        ratio = float(nums[0])
        if ratio > 1.5:
            ratio = ratio / bg_w
        ratio = max(0.0, min(ratio, 1.0))

        drag_distance = int(ratio * groove_width)
        logger.info("滑块缺口比例=%.3f, 拖拽距离=%spx", ratio, drag_distance)

        _simulate_drag(driver, slider_block, drag_distance)
        time.sleep(2)
        return _check_passed(driver, selectors)

    except Exception as exc:
        logger.error("滑块解算错误: %s", exc)
        return False


def _simulate_drag(driver: WebDriver, element: WebElement, distance: int):
    try:
        action = ActionChains(driver)
        action.click_and_hold(element).perform()
        time.sleep(random.uniform(0.05, 0.15))

        segments = random.randint(3, 5)
        remaining = distance
        for _ in range(segments - 1):
            step = random.randint(int(remaining * 0.2), int(remaining * 0.5))
            remaining -= step
            action.move_by_offset(step, random.randint(-1, 1))
            action.pause(random.uniform(0.02, 0.08))
            action.perform()

        action.move_by_offset(remaining, random.randint(-1, 1))
        action.pause(random.uniform(0.1, 0.2))
        action.release().perform()
        logger.info("拖拽 %spx，共 %s 段", distance, segments)
    except Exception as exc:
        logger.error("拖拽错误: %s", exc)


def _extract_ref_url(driver: WebDriver, selectors: dict) -> Optional[str]:
    el = _find_element(driver, selectors.get("header_answer_img"))
    if el is None:
        return None
    src = el.get_attribute("src") or ""
    return src or None


def _extract_main_url(
    driver: WebDriver, selectors: dict
) -> Tuple[Optional[str], Optional[Tuple[int, int]]]:
    for sel in [
        selectors.get("verify_bg_img"),
        selectors.get("point_area"),
        selectors.get("click_type_wrap"),
        selectors.get("verify_bg"),
    ]:
        el = _find_element(driver, sel)
        if el is None:
            continue

        tag = (el.tag_name or "").lower()
        if tag == "img":
            src = el.get_attribute("src") or ""
            if src:
                return src, _get_image_size_from_url(src)

        style = el.get_attribute("style") or ""
        url_match = re.search(r'url\(["\']?(https?://[^"\')\s]+)["\']?\)', style)
        if url_match:
            url = url_match.group(1)
            return url, _get_image_size_from_url(url)

    return None, None


def _save_debug_images(ref_url: str, main_url: str):
    try:
        from const import get_data_dir

        trace_dir = os.path.join(get_data_dir(), "pages")
        os.makedirs(trace_dir, exist_ok=True)
        if ref_url.startswith("http"):
            resp = requests.get(ref_url, timeout=15)
            if resp.status_code == 200:
                with open(os.path.join(trace_dir, "captcha_ref_strip_debug.png"), "wb") as f:
                    f.write(resp.content)
        if main_url.startswith("http"):
            resp = requests.get(main_url, timeout=15)
            if resp.status_code == 200:
                with open(os.path.join(trace_dir, "captcha_main_debug.png"), "wb") as f:
                    f.write(resp.content)
    except Exception:
        pass


def _get_image_size_from_url(url: str) -> Optional[Tuple[int, int]]:
    if not url or not url.startswith("http"):
        return None
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            img = Image.open(io.BytesIO(resp.content))
            return img.size
    except Exception:
        pass
    return None


def _detect_captcha_type_js(driver: WebDriver) -> str:
    try:
        result = driver.execute_script(
            """
            function textOf(sel) {
                var els = document.querySelectorAll(sel);
                for (var i = 0; i < els.length; i++) {
                    if (els[i].offsetParent !== null) {
                        return (els[i].textContent || els[i].innerText || '').trim();
                    }
                }
                return '';
            }
            function exists(sel) {
                var els = document.querySelectorAll(sel);
                for (var i = 0; i < els.length; i++) {
                    if (els[i].offsetParent !== null) return true;
                }
                return false;
            }

            var prompt = textOf('.tencent-captcha-dy__header-text') ||
                         textOf('.tencent-captcha-dy__question') ||
                         textOf('.tencent-captcha-dy__title') || '';

            if (/拖动|拼图|滑块/i.test(prompt)) return 'slider';

            var hasPointClick = /依次点击|顺序点击|点击下图|文字点选|请点击|点击/i.test(prompt) ||
                                exists('.tencent-captcha-dy__click-type-wrap') ||
                                exists('.tencent-captcha-dy__click-word') ||
                                exists('.tencent-captcha-dy__point-area') ||
                                exists('.tencent-captcha-dy__header-answer');

            if (hasPointClick) return 'click';

            if (exists('.tencent-captcha-dy__slider-groove') ||
                exists('.tencent-captcha-dy__verify-slider-area')) return 'slider';

            return 'unknown';
            """
        )
        return result or "unknown"
    except Exception:
        pass
    return _detect_captcha_type_fallback(driver)


def _detect_captcha_type_fallback(driver: WebDriver) -> str:
    content_el = _find_element(driver, "#tCaptchaDyContent", wait=1.0)
    if content_el is None:
        return "unknown"
    try:
        html = content_el.get_attribute("innerHTML") or ""
        if "拖动" in html or "拼图" in html:
            return "slider"
        if "header-answer" in html:
            return "click"
        if "依次点击" in html or "请点击" in html or "点击下图" in html:
            return "click"
    except Exception:
        pass
    return "unknown"


def _wait_for_captcha(driver: WebDriver, timeout: int) -> bool:
    for sel in _WIDGET_SELECTORS:
        try:
            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            return True
        except Exception:
            continue
    return False


def _find_element(driver: WebDriver, selector: str, wait: float = 1.0) -> Optional[WebElement]:
    if not selector:
        return None
    try:
        return WebDriverWait(driver, wait).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )
    except Exception:
        return None


def _find_main_image_element(
    driver: WebDriver, selectors: dict, expected_aspect: float = None
) -> Optional[WebElement]:
    best = None
    best_aspect_diff = float("inf")
    saved_wait = driver.timeouts.implicit_wait if hasattr(driver, "timeouts") else None
    driver.implicitly_wait(0)
    try:
        for sel in [
            selectors.get("verify_bg_img"),
            selectors.get("image_area"),
            selectors.get("point_area"),
            selectors.get("click_type_wrap"),
            selectors.get("verify_bg"),
        ]:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                try:
                    rect = driver.execute_script(
                        "var r = arguments[0].getBoundingClientRect();"
                        "if (r.width < 80 || r.height < 80) return null;"
                        "if (r.bottom <= 0 || r.right <= 0) return null;"
                        "return {h: r.height, w: r.width};",
                        el,
                    )
                    if rect and expected_aspect:
                        aspect = rect["w"] / rect["h"]
                        diff = abs(aspect - expected_aspect) / expected_aspect
                        if diff < best_aspect_diff:
                            best_aspect_diff = diff
                            best = el
                    elif rect:
                        best = el
                        break
                except Exception:
                    pass
            if best and not expected_aspect:
                break
    finally:
        if saved_wait is not None:
            driver.implicitly_wait(saved_wait)
    return best


def _click_with_actions(driver: WebDriver, element: WebElement, offset_x: int, offset_y: int):
    try:
        ActionChains(driver).move_to_element_with_offset(
            element, offset_x, offset_y
        ).pause(random.uniform(0.05, 0.15)).click().perform()
    except Exception:
        try:
            driver.execute_script(
                "var r = arguments[0].getBoundingClientRect();"
                "var cx = r.left + r.width/2 + arguments[1];"
                "var cy = r.top + r.height/2 + arguments[2];"
                "var el = document.elementFromPoint(cx, cy);"
                "if (el) {"
                "  ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){"
                "    el.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true, clientX:cx, clientY:cy}));"
                "  });"
                "}",
                element,
                offset_x,
                offset_y,
            )
        except Exception:
            pass


def _check_passed(driver: WebDriver, selectors: dict) -> bool:
    if "/login" not in urlparse(driver.current_url).path:
        return True
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text or ""
        if any(kw in body_text for kw in ["登录成功", "验证成功", "success"]):
            return True
    except Exception:
        pass
    if not _captcha_visible(driver, selectors):
        time.sleep(2)
        if not _captcha_visible(driver, selectors):
            return True
    return False


def _captcha_visible(driver: WebDriver, selectors: dict) -> bool:
    """验证码弹窗是否仍在显示；元素刚被移除（stale）视为不显示。"""
    el = _find_element(driver, selectors["content"], wait=0.5)
    if el is None:
        return False
    try:
        return el.is_displayed()
    except StaleElementReferenceException:
        return False


def _refresh_captcha(driver: WebDriver, selectors: dict):
    btn = _find_element(driver, selectors.get("refresh_btn"), wait=0.5)
    if btn is not None:
        try:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                logger.info("已点击刷新按钮")
                return
        except Exception:
            pass

    refresh_div = _find_element(driver, ".tencent-captcha-dy__footer-icon--refresh", wait=0.5)
    if refresh_div is not None:
        try:
            imgs = refresh_div.find_elements(By.TAG_NAME, "img")
            for img in imgs:
                if img.is_displayed():
                    driver.execute_script("arguments[0].click();", img)
                    logger.info("已通过 JS 点击刷新图片")
                    return
        except Exception:
            pass

    try:
        driver.execute_script(
            """
            var els = document.querySelectorAll('[class*="refresh"], [class*="footer-icon"]');
            for (var i = 0; i < els.length; i++) {
                if (els[i].offsetParent !== null && els[i].getBoundingClientRect().width > 5) {
                    els[i].click();
                    return;
                }
            }
            """
        )
        logger.info("已通过 JS 回退方式点击刷新")
    except Exception:
        pass
