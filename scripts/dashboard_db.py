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

try:
    import psycopg2
except ImportError:
    psycopg2 = None


def is_db_enabled() -> bool:
    return os.getenv("DB_TYPE", "sqlite").lower() not in ("",)


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


def _next_month_key(ym: str) -> str:
    """自然月 +1，入参 YYYY-MM。"""
    dt = datetime.strptime(str(ym)[:7], "%Y-%m")
    if dt.month == 12:
        return f"{dt.year + 1}-01"
    return f"{dt.year}-{dt.month + 1:02d}"


def _round_step_kwh(v: float) -> float:
    """阶梯电量四舍五入为整数 kWh。"""
    return float(round(v))


def _step_tiers_equal(a: dict, b: dict) -> bool:
    """比较两月阶梯快照是否一致（用于识别「同步月新行但统计仍停在上月」）。"""
    keys = (
        "used_step1", "remain_step1", "used_step2", "remain_step2",
        "used_step3", "total_usage", "step_stage",
    )
    for key in keys:
        av = round(float(a.get(key) or 0))
        bv = round(float(b.get(key) or 0))
        if av != bv:
            return False
    return True


def _month_usage_kwh(user_id: str, month: str) -> float:
    """指定自然月用电量：优先日表汇总（更实时），否则用月表。"""
    start = f"{month}-01"
    end = f"{_next_month_key(month)}-01"
    daily = _query(
        "SELECT total_usage FROM daily_usage WHERE user_id = ? AND date >= ? AND date < ?",
        (user_id, start, end),
    )
    if daily:
        total = sum(float(r.get("total_usage") or 0) for r in daily)
        if total > 0:
            return _round_step_kwh(total)
    monthly = _query(
        "SELECT total_usage FROM monthly_usage WHERE user_id = ? AND month = ? LIMIT 1",
        (user_id, month),
    )
    if monthly and monthly[0].get("total_usage") is not None:
        val = float(monthly[0]["total_usage"])
        if val > 0:
            return _round_step_kwh(val)
    return 0.0


def _normalize_step_integers(step: dict) -> dict:
    """阶梯相关电量字段统一四舍五入为整数。"""
    st = dict(step)
    for key in ("used_step1", "used_step2", "used_step3", "total_usage", "live_extra_kwh"):
        if st.get(key) is not None:
            st[key] = _round_step_kwh(float(st[key]))
    for key in ("remain_step1", "remain_step2"):
        if st.get(key) is not None:
            st[key] = _round_step_kwh(float(st[key]))
    return st


def _resolve_step_stat_month(step_row: dict, prev_row: Optional[dict], bill_month: Optional[str], user_id: Optional[str] = None) -> str:
    """
    推断阶梯快照的「真实统计截止月」。

    国网 step_usage 的 year_month 比真实统计截止月晚约 1 个月
    (国网在 N 月初同步时，阶梯数据实际只统计到 N-1 月底)。
    通过把 step.total_usage 与 monthly_usage 的逐月累计值对比，
    找到 step.total == monthly累计[某月] 的那个月，即为真实截止月。
    匹配不到时回退到 year_month 的上一月。
    """
    ym = str(step_row.get("year_month") or _current_month_key())[:7]
    step_total = round(float(step_row.get("total_usage") or 0))

    # 对比法：用 monthly_usage 逐月累计，找 step_total 匹配的月份
    if user_id and step_total > 0:
        monthly_rows = _query(
            "SELECT month, total_usage FROM monthly_usage WHERE user_id = ? ORDER BY month ASC",
            (user_id,),
        )
        if monthly_rows:
            cumulative = 0.0
            matched: Optional[str] = None
            for r in monthly_rows:
                cumulative += float(r.get("total_usage") or 0)
                # 容差 3 kWh(四舍五入/抄表口径差异)
                if abs(round(cumulative) - step_total) <= 3:
                    matched = str(r.get("month"))[:7]
            if matched:
                return matched

    # 回退：无法匹配时，year_month 退一个月(国网滞后规律)
    dt = datetime.strptime(ym, "%Y-%m")
    if dt.month == 1:
        return f"{dt.year - 1}-12"
    return f"{dt.year}-{dt.month - 1:02d}"


def _apply_extra_kwh_to_step(step: dict, extra: float) -> dict:
    """将额外用电量按当前阶梯阶段依次扣减剩余额度。"""
    if extra <= 0:
        return step
    st = dict(step)
    stage = int(st.get("step_stage") or 1)
    u1 = float(st.get("used_step1") or 0)
    r1_raw = st.get("remain_step1")
    r1 = float(r1_raw) if r1_raw is not None else None
    u2 = float(st.get("used_step2") or 0)
    r2_raw = st.get("remain_step2")
    r2 = float(r2_raw) if r2_raw is not None else None
    u3 = float(st.get("used_step3") or 0)
    rem = extra
    eps = 1e-6

    while rem > eps and stage <= 3:
        if stage == 1:
            if r1 is None or r1 <= eps:
                stage = 2
                continue
            take = min(rem, r1)
            u1 += take
            r1 -= take
            rem -= take
            if r1 <= eps:
                r1 = 0.0
                stage = 2
        elif stage == 2:
            if r2 is None or r2 <= eps:
                stage = 3
                continue
            take = min(rem, r2)
            u2 += take
            r2 -= take
            rem -= take
            if r2 <= eps:
                r2 = 0.0
                stage = 3
        else:
            u3 += rem
            rem = 0

    st["used_step1"] = _round_step_kwh(u1)
    st["remain_step1"] = _round_step_kwh(r1) if r1 is not None else None
    st["used_step2"] = _round_step_kwh(u2)
    st["remain_step2"] = _round_step_kwh(r2) if r2 is not None else None
    st["used_step3"] = _round_step_kwh(u3)
    st["step_stage"] = stage
    st["total_usage"] = _round_step_kwh(float(st.get("total_usage") or 0) + extra)
    return st


def _merge_step_with_live_usage(
    step_row: dict,
    user_id: str,
    prev_row: Optional[dict] = None,
    bill_month: Optional[str] = None,
) -> dict:
    """
    阶梯饼图 = 国网快照额度(已统计到 stat_month) + 之后各月实时用电拼接。
    stat_month 通过 step.total 与 monthly 累计对比反推(国网 year_month 滞后 1 月)。
    仅用于控制台展示，不回写表。
    """
    # 对比法反推真实统计截止月；base_row 用最新 step 行(它已含到 stat_month 的累计)
    stat_month = _resolve_step_stat_month(step_row, prev_row, bill_month, user_id)
    current = _current_month_key()
    result = _normalize_step_integers(step_row)
    result["stat_month"] = stat_month
    # 基础快照原始累计：供前端展示「截止 X 月国网统计 N kWh」
    result["base_total"] = _round_step_kwh(float(step_row.get("total_usage") or 0))
    result["live_adjusted"] = False
    result["live_extra_kwh"] = 0.0
    result["live_extra_months"] = []

    if stat_month >= current:
        return result

    extra_total = 0.0
    extra_months: List[dict] = []
    cursor = _next_month_key(stat_month)
    while cursor <= current:
        usage = _month_usage_kwh(user_id, cursor)
        if usage > 0:
            extra_total += usage
            extra_months.append({"month": cursor, "kwh": usage})
        cursor = _next_month_key(cursor)

    if extra_total <= 0:
        return result

    merged = _apply_extra_kwh_to_step(result, extra_total)
    merged["live_adjusted"] = True
    merged["live_extra_kwh"] = _round_step_kwh(extra_total)
    merged["live_extra_months"] = [
        {"month": m["month"], "kwh": _round_step_kwh(m["kwh"])} for m in extra_months
    ]
    last_extra = extra_months[-1]["month"]
    merged["year_month"] = f"{stat_month} ~ {last_extra}" if stat_month < last_extra else stat_month
    return merged


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


def _pg_conn():
    if psycopg2 is None:
        return None
    try:
        dsn_parts = []
        host = os.getenv("PG_HOST") or os.getenv("POSTGRES_HOST")
        if host:
            dsn_parts.append(f"host={host}")
        port = os.getenv("PG_PORT") or os.getenv("POSTGRES_PORT", "5432")
        dsn_parts.append(f"port={port}")
        dbname = os.getenv("PG_DATABASE") or os.getenv("POSTGRES_DB") or os.getenv("PG_DB")
        if dbname:
            dsn_parts.append(f"dbname={dbname}")
        user = os.getenv("PG_USER") or os.getenv("POSTGRES_USER")
        if user:
            dsn_parts.append(f"user={user}")
        password = os.getenv("PG_PASSWORD") or os.getenv("POSTGRES_PASSWORD")
        if password:
            dsn_parts.append(f"password={password}")
        sslmode = os.getenv("PG_SSLMODE", "")
        if sslmode:
            dsn_parts.append(f"sslmode={sslmode}")
        return psycopg2.connect(" ".join(dsn_parts))
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
    if db_type in ("mysql", "postgresql"):
        sql = sql.replace("?", "%s")
    if db_type == "mysql":
        conn = _mysql_conn()
    elif db_type == "postgresql":
        conn = _pg_conn()
    else:
        conn = _sqlite_conn(readonly=True)
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        if db_type == "sqlite":
            return [dict(r) for r in rows]
        return _rows_to_dicts(cur, rows)
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
    if db_type in ("mysql", "postgresql"):
        sql = sql.replace("?", "%s")
    if db_type == "mysql":
        conn = _mysql_conn()
    elif db_type == "postgresql":
        conn = _pg_conn()
    else:
        conn = _sqlite_conn(readonly=False)
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

    step_rows = _query(
        "SELECT year_month, used_step1, remain_step1, used_step2, remain_step2, "
        "used_step3, total_usage, step_stage FROM step_usage "
        "WHERE user_id = ? ORDER BY year_month DESC LIMIT 2",
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
        "month_tou_is_current": True,
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
            "total_usage": cm.get("total_usage"),
            "valley": cm.get("valley_usage"),
            "flat": cm.get("flat_usage"),
            "peak": cm.get("peak_usage"),
            "tip": cm.get("tip_usage"),
        }
        summary["month_tou_is_current"] = True
    elif bill_month_row:
        # 跨月当天本月尚无数据：回退到上月(账单月)分时，避免卡片显示空。
        # bill_month_row 已按「上月→再上月最新」回退，字段与 monthly_usage 一致。
        m = bill_month_row[0]
        summary["month_tou_summary"] = {
            "month": m.get("month"),
            "total_usage": m.get("total_usage"),
            "valley": m.get("valley_usage"),
            "flat": m.get("flat_usage"),
            "peak": m.get("peak_usage"),
            "tip": m.get("tip_usage"),
        }
        summary["month_tou_is_current"] = False
    name = summary.get("user_name") or ""
    is_ev = "电动车" in name or "充电" in name
    summary["is_residential"] = "住宅" in name and not is_ev
    if step_rows and not is_ev:
        prev_step = step_rows[1] if len(step_rows) > 1 else None
        bill_month = summary.get("bill_month")
        summary["step_data"] = _merge_step_with_live_usage(
            step_rows[0], user_id, prev_step, bill_month,
        )
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
    """读取 app.log 全部内容（由 TimedRotatingFileHandler 按天轮转管理文件大小）。"""
    path = os.path.join(get_data_dir(), "app.log")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.readlines()
        return [ln.rstrip("\n") for ln in content]
    except Exception:
        return []
