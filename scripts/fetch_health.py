"""每日抓取成败记录与连续失败告警。

解决「好几天没同步成功但无人知晓」：每次 mark_fetch_finished 落盘当日结果，
连续失败天数达到阈值时通过企微等渠道推送，并附带近期失败原因。
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

from const import get_data_dir

_HISTORY_FILE = "fetch_health.json"
_KEEP_DAYS = 60


def _history_path() -> str:
    return os.path.join(get_data_dir(), _HISTORY_FILE)


def _today() -> str:
    return date.today().isoformat()


def _alert_threshold() -> int:
    """连续失败多少个自然日后告警；默认 2。"""
    raw = os.getenv("FETCH_FAIL_ALERT_DAYS", "2").strip() or "2"
    try:
        n = int(raw)
    except ValueError:
        n = 2
    return max(1, n)


def _alert_enabled() -> bool:
    return os.getenv("FETCH_FAIL_ALERT", "true").strip().lower() in ("true", "1", "yes")


def load_health() -> dict:
    path = _history_path()
    if not os.path.isfile(path):
        return {
            "last_success_date": None,
            "last_success_at": None,
            "last_fail_at": None,
            "last_error": "",
            "days": {},
            "last_alert_date": None,
            "last_alert_streak": 0,
        }
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("invalid health json")
        data.setdefault("days", {})
        return data
    except Exception as exc:
        logging.warning("读取抓取健康记录失败，将重建: %s", exc)
        return {
            "last_success_date": None,
            "last_success_at": None,
            "last_fail_at": None,
            "last_error": "",
            "days": {},
            "last_alert_date": None,
            "last_alert_streak": 0,
        }


def save_health(data: dict) -> None:
    os.makedirs(get_data_dir(), exist_ok=True)
    with open(_history_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _prune_days(days: dict) -> dict:
    """只保留近 _KEEP_DAYS 天记录，避免文件无限增长。"""
    cutoff = (date.today() - timedelta(days=_KEEP_DAYS)).isoformat()
    return {k: v for k, v in days.items() if k >= cutoff}


def consecutive_fail_days(data: Optional[dict] = None, on_day: Optional[str] = None) -> int:
    """相对 on_day（默认今天）：距上次成功日连续未成功的自然日数。

    从未成功过时，按 days 里最早失败日算起；仍无记录则返回 0。
    """
    data = data or load_health()
    today = date.fromisoformat(on_day or _today())
    last_ok = data.get("last_success_date")
    if last_ok:
        try:
            last_ok_d = date.fromisoformat(str(last_ok)[:10])
        except ValueError:
            last_ok_d = None
        if last_ok_d:
            # 今天若已成功，连续失败为 0
            day_rec = (data.get("days") or {}).get(today.isoformat()) or {}
            if day_rec.get("ok"):
                return 0
            return max(0, (today - last_ok_d).days)

    days = data.get("days") or {}
    fail_dates = sorted(k for k, v in days.items() if not (v or {}).get("ok"))
    if not fail_dates:
        return 0
    try:
        first_fail = date.fromisoformat(fail_dates[0])
    except ValueError:
        return len(fail_dates)
    day_rec = days.get(today.isoformat()) or {}
    if day_rec.get("ok"):
        return 0
    return max(1, (today - first_fail).days + 1)


def record_fetch_result(success: bool, message: str = "", source: str = "") -> dict:
    """写入当日抓取结果，并在达到失败阈值时触发告警。返回更新后的健康状态。"""
    data = load_health()
    today = _today()
    now_iso = datetime.now().isoformat(timespec="seconds")
    msg = (message or "").strip()
    if len(msg) > 500:
        msg = msg[:500] + "…"

    days = dict(data.get("days") or {})
    prev = dict(days.get(today) or {})

    if success:
        days[today] = {
            "ok": True,
            "at": now_iso,
            "source": source or prev.get("source") or "",
            "message": msg or "同步完成",
            "error": "",
            "attempts": int(prev.get("attempts") or 0) + 1,
        }
        data["last_success_date"] = today
        data["last_success_at"] = now_iso
        data["last_error"] = ""
    else:
        # 当日已成功则保留成功，只追加失败尝试计数（避免晚间失败抹掉早上成功）
        if prev.get("ok"):
            days[today] = {
                **prev,
                "attempts": int(prev.get("attempts") or 0) + 1,
                "last_fail_at": now_iso,
                "last_fail_message": msg or "同步失败",
            }
        else:
            days[today] = {
                "ok": False,
                "at": now_iso,
                "source": source or prev.get("source") or "",
                "message": msg or "同步失败",
                "error": msg or "同步失败",
                "attempts": int(prev.get("attempts") or 0) + 1,
            }
            data["last_fail_at"] = now_iso
            data["last_error"] = msg or "同步失败"

    data["days"] = _prune_days(days)
    streak = consecutive_fail_days(data, today)
    data["consecutive_fail_days"] = streak
    save_health(data)

    if success:
        logging.info("抓取健康记录: 今日同步成功")
    else:
        logging.warning(
            "抓取健康记录: 今日同步失败（连续 %s 天未成功），原因: %s",
            streak,
            msg or "未知",
        )

    if not success and _alert_enabled():
        _maybe_alert(data, streak)

    return data


def _recent_fail_reasons(data: dict, limit: int = 5) -> list[str]:
    days = data.get("days") or {}
    lines = []
    for day in sorted(days.keys(), reverse=True):
        rec = days[day] or {}
        if rec.get("ok"):
            continue
        err = (rec.get("error") or rec.get("message") or "未知错误").strip()
        lines.append(f"{day}: {err}")
        if len(lines) >= limit:
            break
    return lines


def _should_alert(data: dict, streak: int, threshold: int) -> bool:
    if streak < threshold:
        return False
    today = _today()
    last_alert_date = data.get("last_alert_date")
    last_alert_streak = int(data.get("last_alert_streak") or 0)
    # 同一天内：仅当连续失败天数升高时再推，避免同日多次重试刷屏
    if last_alert_date == today and streak <= last_alert_streak:
        return False
    return True


def _maybe_alert(data: dict, streak: int) -> None:
    threshold = _alert_threshold()
    if not _should_alert(data, streak, threshold):
        return
    reasons = _recent_fail_reasons(data)
    last_ok = data.get("last_success_date") or "无记录"
    last_ok_at = data.get("last_success_at") or ""
    payload = {
        "streak": streak,
        "threshold": threshold,
        "last_success_date": last_ok,
        "last_success_at": last_ok_at,
        "last_error": data.get("last_error") or "",
        "reasons": reasons,
    }
    try:
        from notify import push_fetch_fail_alert

        ok = push_fetch_fail_alert(payload)
    except Exception as exc:
        logging.warning("抓取失败告警推送异常: %s", exc)
        ok = False

    if ok:
        data["last_alert_date"] = _today()
        data["last_alert_streak"] = streak
        data["last_alert_at"] = datetime.now().isoformat(timespec="seconds")
        save_health(data)
        logging.info("已推送抓取失败告警（连续 %s 天）", streak)
    else:
        logging.warning("抓取失败告警推送未成功（请检查 WEWORK_WEBHOOK_URL / PUSH_TYPE）")


def check_daily_health(force_alert: bool = False) -> dict:
    """日终/定时巡检：今天仍未成功且连续失败达阈值则告警。

    用于「当天两次任务都失败」或「任务未跑到」后的兜底检查。
    """
    data = load_health()
    today = _today()
    day_rec = (data.get("days") or {}).get(today) or {}
    if day_rec.get("ok"):
        logging.debug("抓取健康巡检: 今日已成功，跳过")
        return data

    # 今天尚无记录：记一笔「未执行/未知」，避免只有空白
    if today not in (data.get("days") or {}):
        data = record_fetch_result(
            False,
            message="当日尚未记录到成功同步（定时巡检）",
            source="health_check",
        )
        if not force_alert:
            return data

    streak = consecutive_fail_days(data, today)
    data["consecutive_fail_days"] = streak
    save_health(data)
    if _alert_enabled() and (force_alert or streak >= _alert_threshold()):
        _maybe_alert(data, streak)
    return data


def health_summary() -> dict[str, Any]:
    """供 Web 状态接口展示的摘要。"""
    data = load_health()
    today = _today()
    day = (data.get("days") or {}).get(today) or {}
    return {
        "today": today,
        "today_ok": bool(day.get("ok")),
        "today_message": day.get("message") or day.get("error") or "",
        "last_success_date": data.get("last_success_date"),
        "last_success_at": data.get("last_success_at"),
        "consecutive_fail_days": consecutive_fail_days(data),
        "last_error": data.get("last_error") or "",
        "alert_threshold_days": _alert_threshold(),
        "recent_days": [
            {"date": d, **(data.get("days") or {}).get(d, {})}
            for d in sorted((data.get("days") or {}).keys(), reverse=True)[:14]
        ],
    }
