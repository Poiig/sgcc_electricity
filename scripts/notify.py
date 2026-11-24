import hashlib
import base64
import io
import logging
import os
import typing as typ
from urllib.parse import urlparse

import requests


def _balance_threshold() -> float:
    return float(os.getenv("BALANCE", 10.0))


def _env_truthy(name: str, default: str = "false") -> bool:
    """统一解析开关类环境变量，避免各处重复判断。"""
    return os.getenv(name, default).strip().strip('"').strip("'").lower() in (
        "true", "1", "yes", "on",
    )


def _should_notify(balance: float) -> bool:
    threshold = _balance_threshold()
    logging.info("检查电费余额，低于 %s 元时将发送通知", threshold)
    return balance < threshold


def _format_user_label(user_id, user_name: str = "") -> str:
    name = (user_name or "").strip()
    if name and name != str(user_id):
        return f"{name}（{user_id}）"
    return str(user_id)


def create_balance_notifier():
    """按 PUSH_TYPE 创建余额不足通知器，供 REST/MQTT 推送共用。"""
    push_type = os.getenv("PUSH_TYPE", "none").strip().lower()
    mapping = {
        "pushplus": PushplusNotify,
        "urlpush": UrlPushNotify,
        "wework": WeworkNotify,
        "bark": BarkNotify,
    }
    cls = mapping.get(push_type)
    return cls() if cls else None


def _current_month_prefix() -> str:
    return __import__("datetime").datetime.now().strftime("%Y-%m")


def _sum_current_month_tou(tou_data: dict) -> dict:
    """从日用电汇总当月总量及谷/平/峰/尖；日数据缺分时尝试账单分时。"""
    prefix = _current_month_prefix()
    daily_rows = (tou_data or {}).get("daily") or []
    month_rows = [r for r in daily_rows if str(r.get("date", ""))[:7] == prefix]

    def _sum(rows, field):
        return round(sum(float(r.get(field, 0) or 0) for r in rows), 2)

    result = {}
    if month_rows:
        result = {
            "usage": _sum(month_rows, "total_usage"),
            "valley": _sum(month_rows, "valley_usage"),
            "flat": _sum(month_rows, "flat_usage"),
            "peak": _sum(month_rows, "peak_usage"),
            "tip": _sum(month_rows, "tip_usage"),
        }

    bill = (tou_data or {}).get("bill_month_tou") or {}
    if str(bill.get("month", ""))[:7] == prefix:
        if not result.get("usage") and bill.get("usage") is not None:
            result["usage"] = round(float(bill["usage"]), 2)
        has_tou = any(result.get(k, 0) > 0 for k in ("valley", "flat", "peak", "tip"))
        if not has_tou:
            for src, dst in (
                ("valley_usage", "valley"), ("flat_usage", "flat"),
                ("peak_usage", "peak"), ("tip_usage", "tip"),
            ):
                if bill.get(src) is not None:
                    result[dst] = round(float(bill[src]), 2)

    for row in (tou_data or {}).get("months") or []:
        if str(row.get("month", ""))[:7] == prefix:
            if not result.get("usage") and row.get("total_usage") is not None:
                result["usage"] = round(float(row["total_usage"]), 2)
            break

    return result


def _format_tou_detail(tou: dict) -> str:
    parts = []
    mapping = (("valley", "谷"), ("flat", "平"), ("peak", "峰"), ("tip", "尖"))
    for key, label in mapping:
        val = tou.get(key)
        if val is not None and float(val) > 0:
            parts.append(f"{label} {val}")
    return " / ".join(parts)


def _resolve_current_month_charge(tou_data: dict) -> float | None:
    """尝试从 Vue 月度数据获取当月电费（若有）。"""
    prefix = _current_month_prefix()
    for row in (tou_data or {}).get("months") or []:
        if str(row.get("month", ""))[:7] == prefix:
            charge = row.get("total_charge")
            return float(charge) if charge is not None else None
    bill = (tou_data or {}).get("bill_month_tou") or {}
    if str(bill.get("month", ""))[:7] == prefix and bill.get("charge") is not None:
        return float(bill["charge"])
    return None


def _post_wework(webhook: str, payload: dict) -> bool:
    try:
        resp = requests.post(webhook, json=payload, timeout=_push_timeout())
        if resp.status_code != 200:
            logging.warning("企业微信推送 HTTP 失败: %s %s", resp.status_code, resp.text[:200])
            return False
        data = resp.json()
        if data.get("errcode", 0) != 0:
            logging.warning("企业微信推送返回错误: %s", data)
            return False
        return True
    except Exception as exc:
        logging.warning("企业微信推送异常: %s", exc)
        return False


def _push_timeout() -> int:
    """统一 HTTP 推送超时，避免各渠道硬编码不一致。"""
    try:
        return max(3, int(os.getenv("PUSH_TIMEOUT", "10")))
    except ValueError:
        return 10


class PushplusNotify(typ.NamedTuple):
    """PushPlus 余额不足提醒（支持多 token、模板/话题可配）。"""

    def __call__(self, user_id, balance, user_name: str = ""):
        if not _should_notify(balance):
            return False
        label = _format_user_label(user_id, user_name)
        tokens = [t.strip() for t in os.getenv("PUSHPLUS_TOKEN", "").split(",") if t.strip()]
        if not tokens:
            logging.warning("PUSHPLUS_TOKEN 未配置")
            return False

        title = os.getenv("PUSHPLUS_TITLE", "电费余额不足提醒").strip() or "电费余额不足提醒"
        content = (
            os.getenv("PUSHPLUS_CONTENT_TEMPLATE", "").strip()
            or "用户 {label} 的当前电费余额为：{balance}元，请及时充值。"
        ).format(label=label, balance=balance, user_id=user_id, user_name=user_name or "")

        api = os.getenv("PUSHPLUS_API", "https://www.pushplus.plus/send").strip()
        template = os.getenv("PUSHPLUS_TEMPLATE", "html").strip() or "html"
        topic = os.getenv("PUSHPLUS_TOPIC", "").strip()
        channel = os.getenv("PUSHPLUS_CHANNEL", "").strip()

        any_ok = False
        for token in tokens:
            payload = {
                "token": token,
                "title": title,
                "content": content,
                "template": template,
            }
            if topic:
                payload["topic"] = topic
            if channel:
                payload["channel"] = channel
            try:
                resp = requests.post(api, json=payload, timeout=_push_timeout())
                if resp.status_code == 200:
                    data = resp.json() if resp.content else {}
                    if data.get("code", 200) in (200, 0) or "code" not in data:
                        any_ok = True
                        logging.info("已发送 PushPlus 余额提醒: %s 余额=%s", label, balance)
                    else:
                        logging.warning("PushPlus 返回错误: %s", data)
                else:
                    logging.warning("PushPlus HTTP 失败: %s %s", resp.status_code, resp.text[:200])
            except Exception as exc:
                logging.warning("PushPlus 推送异常: %s", exc)
        return any_ok


class UrlPushNotify(typ.NamedTuple):
    """自定义 Webhook：POST JSON 余额提醒。"""

    def __call__(self, user_id, balance, user_name: str = ""):
        if not _should_notify(balance):
            return False
        label = _format_user_label(user_id, user_name)
        url = os.getenv("PUSH_URL", "").strip()
        if not url:
            logging.warning("PUSH_URL 未配置")
            return False
        try:
            resp = requests.post(
                url,
                json={
                    "user_id": user_id,
                    "user_name": user_name,
                    "balance": balance,
                    "threshold": _balance_threshold(),
                    "title": "电费余额不足提醒",
                },
                timeout=_push_timeout(),
            )
            ok = resp.status_code == 200
            if ok:
                logging.info("已发送 URL 余额提醒: %s 余额=%s", label, balance)
            else:
                logging.warning("URL 推送 HTTP 失败: %s %s", resp.status_code, resp.text[:200])
            return ok
        except Exception as exc:
            logging.warning("URL 推送异常: %s", exc)
            return False


class WeworkNotify(typ.NamedTuple):
    """企业微信群机器人 webhook 余额提醒。"""

    def __call__(self, user_id, balance, user_name: str = ""):
        if not _should_notify(balance):
            return False
        webhook = os.getenv("WEWORK_WEBHOOK_URL", "").strip()
        if not webhook:
            logging.warning("WEWORK_WEBHOOK_URL 未配置")
            return False
        label = _format_user_label(user_id, user_name)
        threshold = _balance_threshold()
        content = (
            "**电费余额不足提醒**\n"
            f"> 户名：<font color=\"comment\">{(user_name or user_id)}</font>\n"
            f"> 户号：<font color=\"comment\">{user_id}</font>\n"
            f"> 当前余额：<font color=\"warning\">{balance} 元</font>\n"
            f"> 提醒阈值：{threshold} 元\n"
            "请及时登录国网 APP 或网站充值。"
        )
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        ok = _post_wework(webhook, payload)
        if ok:
            logging.info("已发送企业微信余额提醒: %s 余额=%s", label, balance)
        return ok


def _bark_endpoints() -> list[tuple[str, str]]:
    """解析 BARK_KEY（支持多 key / 完整 URL）与 BARK_SERVER，得到 (server, key) 列表。"""
    raw = os.getenv("BARK_KEY", "").strip()
    default_server = os.getenv("BARK_SERVER", "https://api.day.app").strip().rstrip("/")
    endpoints: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("http://") or part.startswith("https://"):
            parsed = urlparse(part.rstrip("/"))
            segments = [s for s in parsed.path.split("/") if s]
            if not segments or segments[-1] == "push":
                logging.warning("BARK_KEY URL 缺少 device_key: %s", part)
                continue
            key = segments[-1]
            base_path = "/".join(segments[:-1])
            server = f"{parsed.scheme}://{parsed.netloc}"
            if base_path:
                server = f"{server}/{base_path}"
            endpoints.append((server.rstrip("/"), key))
        else:
            endpoints.append((default_server, part))
    return endpoints


def _bark_options() -> dict:
    """从环境变量组装 Bark 可选参数，空值不传以免覆盖 App 默认。"""
    mapping = {
        "group": "BARK_GROUP",
        "sound": "BARK_SOUND",
        "icon": "BARK_ICON",
        "level": "BARK_LEVEL",
        "url": "BARK_CLICK_URL",
        "volume": "BARK_VOLUME",
        "copy": "BARK_COPY",
    }
    opts = {}
    for field, env_name in mapping.items():
        val = os.getenv(env_name, "").strip()
        if val:
            opts[field] = val
    if _env_truthy("BARK_CALL"):
        opts["call"] = "1"
    if _env_truthy("BARK_AUTO_COPY"):
        opts["autoCopy"] = "1"
    if _env_truthy("BARK_IS_ARCHIVE"):
        opts["isArchive"] = "1"
    badge = os.getenv("BARK_BADGE", "").strip()
    if badge.isdigit():
        opts["badge"] = int(badge)
    return opts


def _post_bark(title: str, body: str) -> bool:
    """向所有已配置 Bark 设备推送同一条通知。"""
    endpoints = _bark_endpoints()
    if not endpoints:
        logging.warning("BARK_KEY 未配置")
        return False
    opts = _bark_options()
    any_ok = False
    for server, key in endpoints:
        payload = {"title": title, "body": body, "device_key": key, **opts}
        url = f"{server}/{key}"
        try:
            resp = requests.post(url, json=payload, timeout=_push_timeout())
            if resp.status_code != 200:
                logging.warning("Bark 推送 HTTP 失败: %s %s", resp.status_code, resp.text[:200])
                continue
            data = resp.json() if resp.content else {}
            if data.get("code", 200) not in (200, 0):
                logging.warning("Bark 推送返回错误: %s", data)
                continue
            any_ok = True
        except Exception as exc:
            logging.warning("Bark 推送异常: %s", exc)
    return any_ok


class BarkNotify(typ.NamedTuple):
    """iOS Bark 余额不足提醒。"""

    def __call__(self, user_id, balance, user_name: str = ""):
        if not _should_notify(balance):
            return False
        if not _bark_endpoints():
            logging.warning("BARK_KEY 未配置")
            return False
        label = _format_user_label(user_id, user_name)
        threshold = _balance_threshold()
        title = os.getenv("BARK_TITLE", "电费余额不足提醒").strip() or "电费余额不足提醒"
        body = (
            os.getenv("BARK_BODY_TEMPLATE", "").strip()
            or "户名：{label}\n当前余额：{balance} 元\n提醒阈值：{threshold} 元\n请及时充值。"
        ).format(
            label=label,
            balance=balance,
            threshold=threshold,
            user_id=user_id,
            user_name=user_name or "",
        )
        ok = _post_bark(title, body)
        if ok:
            logging.info("已发送 Bark 余额提醒: %s 余额=%s", label, balance)
        return ok


def _iter_summary_lines(records: list, *, rich: bool) -> list[str]:
    """组装同步汇总正文；rich=True 用企微 markdown 色标，否则用纯文本给 Bark。"""
    now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if rich:
        lines = [
            "## 国家电网数据同步完成",
            f"> 同步时间：<font color=\"comment\">{now}</font>",
            f"> 成功户号：<font color=\"info\">{len(records)}</font> 个",
            "",
        ]
    else:
        lines = [
            f"同步时间：{now}",
            f"成功户号：{len(records)} 个",
            "",
        ]

    for item in records:
        user_id = item.get("user_id", "")
        user_name = item.get("user_name") or user_id
        balance = item.get("balance")
        balance_text = f"{balance} 元" if balance is not None else "—"
        if rich:
            balance_color = (
                "warning" if balance is not None and balance < _balance_threshold() else "info"
            )
            lines.extend([
                f"### {user_name}",
                f"> 户号：<font color=\"comment\">{user_id}</font>",
                f"> 余额：<font color=\"{balance_color}\">{balance_text}</font>",
            ])
            prefix = "> "
        else:
            lines.extend([f"【{user_name}】", f"户号：{user_id}", f"余额：{balance_text}"])
            prefix = ""

        if item.get("last_daily_date") and item.get("last_daily_usage") is not None:
            lines.append(
                f"{prefix}最近用电：{item['last_daily_usage']} kWh ({item['last_daily_date']})"
            )
        if item.get("month_usage") is not None or item.get("month_charge") is not None:
            period = item.get("last_month_period") or "账单月"
            lines.append(
                f"{prefix}上月（{period}）：{item.get('month_usage', '—')} kWh / "
                f"{item.get('month_charge', '—')} 元"
            )
        tou_data = item.get("tou_data") or {}
        current = _sum_current_month_tou(tou_data)
        if current.get("usage") is not None:
            month_label = _current_month_prefix()
            charge = _resolve_current_month_charge(tou_data)
            charge_part = f" / {charge} 元" if charge is not None else ""
            lines.append(f"{prefix}当月累计（{month_label}）：{current['usage']} kWh{charge_part}")
            tou_text = _format_tou_detail(current)
            if tou_text:
                lines.append(f"{prefix}当月分时：{tou_text} kWh")
        if item.get("yearly_usage") is not None or item.get("yearly_charge") is not None:
            lines.append(
                f"{prefix}年度：{item.get('yearly_usage', '—')} kWh / "
                f"{item.get('yearly_charge', '—')} 元"
            )
        enhanced = item.get("enhanced_balance") or {}
        if enhanced.get("amount_due") is not None:
            lines.append(f"{prefix}应交金额：{enhanced['amount_due']} 元")
        lines.append("")
    return lines


class WeworkSummaryNotify(typ.NamedTuple):
    """企业微信推送户号数据汇总（拉取成功后）。"""

    def __call__(self, records: list) -> bool:
        webhook = os.getenv("WEWORK_WEBHOOK_URL", "").strip()
        if not webhook or not records:
            return False
        content = "\n".join(_iter_summary_lines(records, rich=True)).strip()
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        ok = _post_wework(webhook, payload)
        if ok:
            logging.info("已发送企业微信数据汇总，共 %s 个户号", len(records))
        return ok


class BarkSummaryNotify(typ.NamedTuple):
    """Bark 推送户号数据汇总（拉取成功后）。"""

    def __call__(self, records: list) -> bool:
        if not records or not _bark_endpoints():
            return False
        title = os.getenv("BARK_SUMMARY_TITLE", "国家电网数据同步完成").strip() or "国家电网数据同步完成"
        body = "\n".join(_iter_summary_lines(records, rich=False)).strip()
        ok = _post_bark(title, body)
        if ok:
            logging.info("已发送 Bark 数据汇总，共 %s 个户号", len(records))
        return ok


def push_fetch_summary(records: list) -> bool:
    """拉取成功后按 PUSH_TYPE 推送汇总（wework / bark 可分别开关）。"""
    if not records:
        return False
    push_type = os.getenv("PUSH_TYPE", "none").strip().lower()
    if push_type == "wework":
        if not _env_truthy("WEWORK_PUSH_SUMMARY", "true"):
            return False
        if not os.getenv("WEWORK_WEBHOOK_URL", "").strip():
            logging.warning("WEWORK_WEBHOOK_URL 未配置，跳过汇总推送")
            return False
        return WeworkSummaryNotify()(records)
    if push_type == "bark":
        if not _env_truthy("BARK_PUSH_SUMMARY", "true"):
            return False
        if not _bark_endpoints():
            logging.warning("BARK_KEY 未配置，跳过汇总推送")
            return False
        return BarkSummaryNotify()(records)
    return False


class UrlLoginQrCodeNotify(typ.NamedTuple):

    def __call__(self, qrcode) -> bool:
        url = os.getenv("PUSH_QRCODE_URL", "").strip()
        if not url:
            return False
        try:
            files = {"file": ("qrcode.png", io.BytesIO(qrcode), "image/png")}
            resp = requests.post(url, files=files, timeout=15)
            if resp.status_code == 200:
                logging.info("已推送登录二维码到自定义 URL")
                return True
            logging.warning("自定义 URL 二维码推送 HTTP 失败: %s", resp.status_code)
        except Exception as exc:
            logging.warning("自定义 URL 二维码推送异常: %s", exc)
        return False


class WeworkQrCodeNotify(typ.NamedTuple):
    """企业微信群机器人推送登录二维码（image 类型）。"""

    def __call__(self, qrcode) -> bool:
        webhook = os.getenv("WEWORK_WEBHOOK_URL", "").strip()
        if not webhook:
            return False
        if isinstance(qrcode, str):
            qrcode = qrcode.encode("utf-8")
        image_md5 = hashlib.md5(qrcode).hexdigest()
        image_base64 = base64.b64encode(qrcode).decode("ascii")
        payload = {
            "msgtype": "image",
            "image": {"base64": image_base64, "md5": image_md5},
        }
        ok = _post_wework(webhook, payload)
        if ok:
            logging.info("已推送登录二维码到企业微信")
        return ok


def get_qrcode_notifier():
    """兼容旧调用：返回单一推送器（优先企微）。"""
    wework = os.getenv("WEWORK_WEBHOOK_URL", "").strip()
    if wework:
        return WeworkQrCodeNotify()
    if os.getenv("PUSH_QRCODE_URL", "").strip():
        return UrlLoginQrCodeNotify()
    return None


def _ensure_env_loaded() -> None:
    if "PYTHON_IN_DOCKER" not in os.environ:
        from const import load_project_env
        load_project_env()


def _push_wework_login_text(webhook: str, reason: str, tip: str = "") -> bool:
    """企微 markdown 登录提醒；tip 可补充「正在获取二维码 / 取图失败」等说明。"""
    scene = reason.strip() or "扫码登录"
    extra = f"\n> {tip}" if tip else ""
    content = (
        "**国家电网登录提醒**\n"
        f"> 场景：<font color=\"comment\">{scene}</font>\n"
        "> 请使用 **国网 App** 扫描二维码完成登录"
        f"{extra}"
    )
    return _post_wework(webhook, {"msgtype": "markdown", "markdown": {"content": content}})


def _format_fail_alert_plain(payload: dict) -> tuple[str, str]:
    """失败告警纯文本标题与正文，供 Bark / 日志复用。"""
    streak = payload.get("streak") or 0
    threshold = payload.get("threshold") or 0
    last_ok = payload.get("last_success_date") or "无记录"
    last_ok_at = payload.get("last_success_at") or ""
    last_error = (payload.get("last_error") or "").strip() or "未知"
    reasons = payload.get("reasons") or []
    reason_lines = "\n".join(f"· {r}" for r in reasons[:5]) or f"· {last_error}"
    last_ok_line = last_ok if not last_ok_at else f"{last_ok}（{last_ok_at}）"
    title = "国家电网同步失败告警"
    body = (
        f"已连续 {streak} 天未成功（阈值 {threshold} 天）\n"
        f"最近成功：{last_ok_line}\n"
        f"最近错误：{last_error}\n"
        f"近期失败原因：\n{reason_lines}\n"
        "请检查验证码/登录、容器日志或 Web 控制台后手动同步"
    )
    return title, body


def push_fetch_fail_alert(payload: dict) -> bool:
    """连续多日抓取失败告警：企微 webhook 与/或 Bark（按已配置渠道发送）。"""
    _ensure_env_loaded()
    webhook = os.getenv("WEWORK_WEBHOOK_URL", "").strip()
    push_type = os.getenv("PUSH_TYPE", "none").strip().lower()
    bark_ready = push_type == "bark" and bool(_bark_endpoints())

    if not webhook and not bark_ready:
        logging.info("未配置 WEWORK_WEBHOOK_URL / Bark，跳过抓取失败告警")
        return False

    streak = payload.get("streak") or 0
    threshold = payload.get("threshold") or 0
    last_ok = payload.get("last_success_date") or "无记录"
    last_ok_at = payload.get("last_success_at") or ""
    last_error = (payload.get("last_error") or "").strip() or "未知"
    reasons = payload.get("reasons") or []
    reason_lines = "\n".join(f"> · {r}" for r in reasons[:5]) or f"> · {last_error}"
    last_ok_line = last_ok if not last_ok_at else f"{last_ok}（{last_ok_at}）"

    ok = False
    if webhook:
        content = (
            "**国家电网同步失败告警**\n"
            f"> 已连续 <font color=\"warning\">{streak}</font> 天未成功"
            f"（阈值 {threshold} 天）\n"
            f"> 最近成功：<font color=\"comment\">{last_ok_line}</font>\n"
            f"> 最近错误：<font color=\"warning\">{last_error}</font>\n"
            "> 近期失败原因：\n"
            f"{reason_lines}\n"
            "> 请检查验证码/登录、容器日志或 Web 控制台后手动同步"
        )
        if _post_wework(webhook, {"msgtype": "markdown", "markdown": {"content": content}}):
            logging.info("已推送抓取失败告警到企业微信（连续 %s 天）", streak)
            ok = True

    if bark_ready:
        title, body = _format_fail_alert_plain(payload)
        if _post_bark(title, body):
            logging.info("已推送抓取失败告警到 Bark（连续 %s 天）", streak)
            ok = True
    return ok


def _push_bark_login_text(reason: str, tip: str = "") -> bool:
    """Bark 扫码文字提醒；图片需走企微或 PUSH_QRCODE_URL。"""
    scene = reason.strip() or "扫码登录"
    tip_line = f"\n{tip}" if tip else ""
    body = (
        f"场景：{scene}\n"
        "请使用国网 App 扫描二维码完成登录"
        f"{tip_line}"
    )
    return _post_bark("国家电网登录提醒", body)


def push_login_need_scan(reason: str = "", tip: str = "正在获取登录二维码，稍后将推送图片") -> bool:
    """在拿到二维码图片之前先发文字提醒，避免取图失败时完全无通知。"""
    _ensure_env_loaded()
    wework = os.getenv("WEWORK_WEBHOOK_URL", "").strip()
    push_type = os.getenv("PUSH_TYPE", "none").strip().lower()
    bark_ready = push_type == "bark" and bool(_bark_endpoints())

    if not wework and not bark_ready:
        logging.info("未配置扫码文字推送渠道，跳过提醒")
        return False

    ok = False
    if wework:
        if _push_wework_login_text(wework, reason, tip=tip):
            logging.info("已推送扫码登录文字提醒到企业微信")
            ok = True
    if bark_ready:
        bark_tip = tip
        if "图片" in tip and not os.getenv("PUSH_QRCODE_URL", "").strip():
            bark_tip = "请打开 Web 控制台查看登录二维码"
        if _push_bark_login_text(reason, tip=bark_tip):
            logging.info("已推送扫码登录文字提醒到 Bark")
            ok = True
    return ok


def push_login_qrcode(qrcode: bytes, reason: str = "", with_text: bool = True) -> bool:
    """按 PUSH_TYPE / 环境变量推送登录二维码；Bark 不支持图片，仅补文字并尽量走 PUSH_QRCODE_URL。"""
    _ensure_env_loaded()
    if isinstance(qrcode, str):
        qrcode = qrcode.encode("utf-8")

    push_type = os.getenv("PUSH_TYPE", "none").strip().lower()
    wework = os.getenv("WEWORK_WEBHOOK_URL", "").strip()
    qrcode_url = os.getenv("PUSH_QRCODE_URL", "").strip()

    if push_type == "wework" and wework:
        ok = False
        if with_text:
            ok = _push_wework_login_text(wework, reason) or ok
        if WeworkQrCodeNotify()(qrcode):
            ok = True
        return ok

    if push_type == "bark":
        ok = False
        if with_text and _bark_endpoints():
            tip = "二维码已生成"
            if qrcode_url:
                tip += "，同时尝试推送到自定义 URL"
            else:
                tip += "，请打开 Web 控制台扫码（Bark 无法推送图片）"
            ok = _push_bark_login_text(reason, tip=tip) or ok
        if qrcode_url and UrlLoginQrCodeNotify()(qrcode):
            ok = True
        return ok

    if qrcode_url:
        return UrlLoginQrCodeNotify()(qrcode)
    if wework:
        ok = False
        if with_text:
            ok = _push_wework_login_text(wework, reason) or ok
        if WeworkQrCodeNotify()(qrcode):
            ok = True
        return ok

    logging.info(
        "未配置二维码推送渠道 (wework / bark+PUSH_QRCODE_URL / PUSH_QRCODE_URL)"
    )
    return False
