"""Web 仪表盘只读数据查询（仅数据库，不读本地 cache）。"""

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, List, Optional

from const import get_data_dir

try:
    import mysql.connector
except ImportError:
    mysql = None


def is_db_enabled() -> bool:
    return os.getenv("DB_TYPE", "sqlite").lower() not in ("none", "")


def db_available() -> bool:
    if not is_db_enabled():
        return False
    try:
        return bool(_query("SELECT 1 AS ok LIMIT 1"))
    except Exception:
        return False


def _previous_month_key() -> str:
    first = datetime.now().replace(day=1).date()
    prev = first - timedelta(days=1)
    return prev.strftime("%Y-%m")


def _current_month_key() -> str:
    return datetime.now().strftime("%Y-%m")


def _sqlite_conn(readonly: bool = True):
    db_path = os.path.join(get_data_dir(), os.getenv("DB_NAME", "homeassistant.db"))
    if not os.path.isfile(db_path):
        return None
    if readonly:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _mysql_conn():
    if mysql is None:
        return None
    try:
        return mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DATABASE", "sgcc"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
        )
    except Exception:
        return None


def _rows_to_dicts(cursor, rows) -> List[dict]:
    if not rows:
        return []
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


def _query(sql: str, params: tuple = ()) -> List[dict]:
    if not is_db_enabled():
        return []
    db_type = os.getenv("DB_TYPE", "sqlite").lower()
    if db_type == "mysql":
        sql = sql.replace("?", "%s")
    conn = _mysql_conn() if db_type == "mysql" else _sqlite_conn(readonly=True)
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        if db_type == "mysql":
            return _rows_to_dicts(cur, rows)
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _execute(sql: str, params: tuple = ()) -> bool:
    if not is_db_enabled():
        return False
    db_type = os.getenv("DB_TYPE", "sqlite").lower()
    if db_type == "mysql":
        sql = sql.replace("?", "%s")
    conn = _mysql_conn() if db_type == "mysql" else _sqlite_conn(readonly=False)
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass



def _format_datetime(val) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    text = str(val).strip()
    if not text:
        return None
    text = text.replace("Z", "").split("+")[0].strip()
    normalized = text[:19].replace("T", " ")
    for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            dt = datetime.strptime(normalized[:size], fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return normalized


def list_balance_logs(per_user: int = 5) -> List[dict]:
    """按户号分组，每户保留最近 per_user 条 balance_log（按 created_at 同步完成时间）。"""
    if not is_db_enabled():
        return []
    per_user = max(1, min(per_user, 20))
    rows = _query(
        "SELECT user_id, user_name, balance, amount_due, created_at "
        "FROM balance_log ORDER BY created_at DESC LIMIT 500"
    )
    counts: dict[str, int] = {}
    grouped: dict[str, dict] = {}
    for row in rows:
        uid = str(row.get("user_id") or "")
        if not uid or counts.get(uid, 0) >= per_user:
            continue
        counts[uid] = counts.get(uid, 0) + 1
        record = {
            "sync_at": _format_datetime(row.get("created_at")),
            "balance": row.get("balance"),
            "amount_due": row.get("amount_due"),
        }
        if uid not in grouped:
            grouped[uid] = {
                "user_id": uid,
                "user_name": row.get("user_name") or uid,
                "records": [],
            }
        grouped[uid]["records"].append(record)
    return sorted(grouped.values(), key=lambda x: x["user_id"])


def latest_balance_log_timestamp() -> Optional[float]:
    rows = _query("SELECT created_at FROM balance_log ORDER BY created_at DESC LIMIT 1")
    if not rows:
        return None
    created = rows[0].get("created_at")
    if created is None:
        return None
    try:
        if isinstance(created, (int, float)):
            return float(created)
        dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        return dt.timestamp()
    except (TypeError, ValueError):
        return None


def list_users() -> List[dict]:
    if not is_db_enabled():
        return []
    ignore = {
        x.strip()
        for x in os.getenv("IGNORE_USER_ID", "").split(",")
        if x.strip()
    }
    users = _query(
        "SELECT user_id, user_name, phone_number, updated_at FROM users ORDER BY user_id"
    )
    return [u for u in users if u.get("user_id") not in ignore]


def get_user_summary(user_id: str) -> dict:
    if not is_db_enabled():
        return {"user_id": user_id, "db_enabled": False}

    balance_row = _query(
        "SELECT balance, amount_due, as_of, user_name FROM balance_log "
        "WHERE user_id = ? ORDER BY as_of DESC LIMIT 1",
        (user_id,),
    )
    last_daily = _query(
        "SELECT date, total_usage FROM daily_usage WHERE user_id = ? ORDER BY date DESC LIMIT 1",
        (user_id,),
    )
    yearly = _query(
        "SELECT year, total_usage, total_charge FROM yearly_usage "
        "WHERE user_id = ? ORDER BY year DESC LIMIT 1",
        (user_id,),
    )

    prev_month = _previous_month_key()
    bill_month_row = _query(
        "SELECT month, total_usage, total_charge, valley_usage, flat_usage, peak_usage, tip_usage "
        "FROM monthly_usage WHERE user_id = ? AND month = ? LIMIT 1",
        (user_id, prev_month),
    )
    if not bill_month_row:
        current = _current_month_key()
        bill_month_row = _query(
            "SELECT month, total_usage, total_charge, valley_usage, flat_usage, peak_usage, tip_usage "
            "FROM monthly_usage WHERE user_id = ? AND month < ? ORDER BY month DESC LIMIT 1",
            (user_id, current),
        )

    current_month_row = _query(
        "SELECT month, total_usage, total_charge, valley_usage, flat_usage, peak_usage, tip_usage "
        "FROM monthly_usage WHERE user_id = ? AND month = ? LIMIT 1",
        (user_id, _current_month_key()),
    )

    step = _query(
        "SELECT year_month, used_step1, remain_step1, used_step2, remain_step2, "
        "used_step3, total_usage, step_stage FROM step_usage "
        "WHERE user_id = ? ORDER BY year_month DESC LIMIT 1",
        (user_id,),
    )

    user_row = _query("SELECT user_name FROM users WHERE user_id = ? LIMIT 1", (user_id,))
    user_name = user_id
    if user_row:
        user_name = user_row[0].get("user_name") or user_id
    if balance_row:
        user_name = balance_row[0].get("user_name") or user_name

    summary: dict[str, Any] = {
        "user_id": user_id,
        "user_name": user_name,
        "balance": None,
        "amount_due": None,
        "balance_as_of": None,
        "last_daily_date": None,
        "last_daily_usage": None,
        "yearly_usage": None,
        "yearly_charge": None,
        "yearly_label": None,
        "bill_month": None,
        "month_usage": None,
        "month_charge": None,
        "bill_month_tou": None,
        "month_tou_summary": None,
        "step_data": None,
        "db_enabled": True,
    }

    if balance_row:
        row = balance_row[0]
        summary["balance"] = row.get("balance")
        summary["amount_due"] = row.get("amount_due")
        summary["balance_as_of"] = row.get("as_of")
    if last_daily:
        summary["last_daily_date"] = last_daily[0].get("date")
        summary["last_daily_usage"] = last_daily[0].get("total_usage")
    if yearly:
        summary["yearly_usage"] = yearly[0].get("total_usage")
        summary["yearly_charge"] = yearly[0].get("total_charge")
        summary["yearly_label"] = yearly[0].get("year")
    if bill_month_row:
        m = bill_month_row[0]
        summary["bill_month"] = m.get("month")
        summary["month_usage"] = m.get("total_usage")
        summary["month_charge"] = m.get("total_charge")
        summary["bill_month_tou"] = {
            "valley": m.get("valley_usage"),
            "flat": m.get("flat_usage"),
            "peak": m.get("peak_usage"),
            "tip": m.get("tip_usage"),
        }
    if current_month_row:
        cm = current_month_row[0]
        summary["month_tou_summary"] = {
            "month": cm.get("month"),
            "valley": cm.get("valley_usage"),
            "flat": cm.get("flat_usage"),
            "peak": cm.get("peak_usage"),
            "tip": cm.get("tip_usage"),
        }
    if step:
        summary["step_data"] = step[0]

    name = summary.get("user_name") or ""
    summary["is_residential"] = "住宅" in name or bool(summary.get("step_data"))
    return summary


def get_daily_chart(user_id: str, days: int = 30) -> List[dict]:
    if not is_db_enabled():
        return []
    days = max(7, min(days, 90))
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return _query(
        "SELECT date, total_usage, valley_usage, flat_usage, peak_usage, tip_usage "
        "FROM daily_usage WHERE user_id = ? AND date >= ? ORDER BY date",
        (user_id, start),
    )


def get_monthly_chart(user_id: str, months: int = 12) -> List[dict]:
    if not is_db_enabled():
        return []
    months = max(3, min(months, 24))
    rows = _query(
        "SELECT month, total_usage, total_charge, valley_usage, flat_usage, peak_usage, tip_usage "
        "FROM monthly_usage WHERE user_id = ? ORDER BY month DESC LIMIT ?",
        (user_id, months),
    )
    return list(reversed(rows))


def tail_log(lines: int = 200) -> List[str]:
    """保留 app.log 读取；运行日志 Tab 主表为 balance_log。"""
    lines = max(50, min(lines, 1000))
    path = os.path.join(get_data_dir(), "app.log")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.readlines()
        return [ln.rstrip("\n") for ln in content[-lines:]]
    except Exception:
        return []
