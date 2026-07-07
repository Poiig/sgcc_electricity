"""Vue state injection helpers for reading 95598 page data.

Injects JavaScript into the browser to scan all DOM elements for __vue__ properties,
extracting structured data from the Vue component instances.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional


SELECTED_VUE_DATA_SCRIPT = """
const clone = (value) => {
  try { return JSON.parse(JSON.stringify(value)); } catch (e) { return null; }
};
const wantedKeys = [
  'mixinGetYuEdata',
  'consInfoobj',
  'consInfo',
  'electric',
  'powerData',
  'mothData',
  'tableData',
  'tableData_t',
  'sevenEleList',
  'sevenEleList_t',
  'new_sevenEleList',
  'thirtyEleList',
  'thirtyEleList_t',
  'tariffC',
  'start',
  'end',
  'queryYear',
  'activeName',
  'billNumberList',
  'BillList',
  'billList',
  'billMonth',
  'NewtotalBillProvince',
  'optionalYearArray',
  'selectYear',
  'listData',
  'yeData',
  'elecItemData'
];
return Array.from(document.querySelectorAll('*'))
  .map((el, index) => {
    const vm = el.__vue__;
    if (!vm) return null;
    const data = {};
    wantedKeys.forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(vm, key)) {
        data[key] = clone(vm[key]);
      }
    });
    if (!Object.keys(data).length) return null;
    return {
      index,
      tag: el.tagName,
      id: el.id || '',
      className: String(el.className || '').slice(0, 160),
      text: (el.innerText || el.textContent || '').trim().slice(0, 500),
      data
    };
  })
  .filter(Boolean);
"""


def selected_vue_data(driver) -> list[dict[str, Any]]:
    """Execute JS to extract Vue state from the current page."""
    return driver.execute_script(SELECTED_VUE_DATA_SCRIPT) or []


def normalize_user_info(components: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract user info (name, address) from Vue state."""
    cons = _first_data_value(components, "consInfoobj") or _first_data_value(components, "consInfo") or {}
    if not isinstance(cons, dict):
        cons = {}
    return {
        "user_name": cons.get("consName") or cons.get("custName") or "",
        "address": cons.get("elecAddr") or cons.get("addr") or "",
        "user_id": cons.get("consNo") or cons.get("consId") or "",
    }


def normalize_balance(components: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract amount due (应交金额) from Vue state."""
    raw = _first_data_value(components, "mixinGetYuEdata") or {}
    return {
        "as_of": raw.get("amtTime"),
        "amount_due": _safe_float(raw.get("historyOwe")),
        "user_id": raw.get("consNo"),
    }


def normalize_usage(components: list[dict[str, Any]], fetch_days: int = 7) -> dict[str, Any]:
    """Extract usage data (yearly summary, monthly, daily with TOU) from Vue state."""
    power_data = _first_data_value(components, "powerData") or _first_data_value(components, "tableData_t") or {}
    info = power_data.get("dataInfo") or {}
    month_rows = power_data.get("mothEleList") or _first_data_value(components, "mothData") or []

    if fetch_days == 30:
        daily_keys = ("thirtyEleList", "thirtyEleList_t", "tableData", "new_sevenEleList", "sevenEleList")
    else:
        daily_keys = ("tableData", "new_sevenEleList", "sevenEleList", "thirtyEleList", "thirtyEleList_t")

    daily_rows = _pick_daily_rows(components, daily_keys, require_tou=True)
    if not daily_rows:
        daily_rows = _pick_daily_rows(components, daily_keys, require_tou=False)

    return {
        "year": str(info.get("year") or _first_data_value(components, "queryYear") or ""),
        "yearly_usage": _safe_float(info.get("totalEleNum")),
        "yearly_charge": _safe_float(info.get("totalEleCost")),
        "recent_total_usage": _safe_float(_first_data_value(components, "tariffC")),
        "daily_range": {
            "start": _first_data_value(components, "start"),
            "end": _first_data_value(components, "end"),
        },
        "months": [_normalize_usage_month(row) for row in month_rows if isinstance(row, dict)],
        "daily": [
            row for row in (
                _normalize_daily_row(r, str(info.get("year") or _first_data_value(components, "queryYear") or ""))
                for r in daily_rows if isinstance(r, dict)
            ) if row
        ],
        "raw": power_data,
    }


def normalize_bill_detail(components: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract monthly bill detail with TOU breakdown from Vue state."""
    bill = (_first_data_value(components, "billList") or [{}])[0]
    if not isinstance(bill, dict):
        bill = {}
    basic = bill.get("basicInfo") or {}
    pv_qty = (bill.get("pvQtyList") or [{}])[0]
    return {
        "month": _normalize_ym(bill.get("ym")),
        "user_id": basic.get("consNo"),
        "begin_date": basic.get("begDate"),
        "end_date": basic.get("endDate"),
        "usage": _safe_float(basic.get("monthPq")),
        "charge": _safe_float(basic.get("monthAmt")),
        "year_usage": _safe_float(basic.get("yearPq")),
        "year_charge": _safe_float(basic.get("yearAmt")),
        "valley_usage": _safe_float(pv_qty.get("valQty")),
        "flat_usage": _safe_float(pv_qty.get("flatQty")),
        "peak_usage": _safe_float(pv_qty.get("peakQty")),
        "tip_usage": _safe_float(pv_qty.get("sharpQty")),
        "raw": bill,
    }


def normalize_electric_balance(components: list[dict[str, Any]], expected_user_id: str = "") -> dict[str, Any]:
    """从 userAcc / 电费电量页 Vue state 提取账户余额。

    关键：统一取「账户余额」(剩余可用金额)，与页面 DOM 的「账户余额」字段对齐。
    - sumMoney 是上月用电金额(非余额)，必须排除，否则会把上月金额误当余额
    - oweAmt 对后付费账户是应交金额，不是账户余额，降级处理
    - 优先取预付费/账户余额类字段：prepayBal / acctBalance / surplusAmt / usableAmt / balance
    """
    result = {
        "balance": None,
        "amount_due": None,
        "as_of": None,
        "user_id": None,
    }
    raw = _first_data_value(components, "mixinGetYuEdata")
    if isinstance(raw, dict):
        result["amount_due"] = _safe_float(raw.get("historyOwe"))
        result["as_of"] = raw.get("amtTime") or raw.get("date")
        result["user_id"] = str(raw.get("consNo") or raw.get("consId") or "").strip()
        # 账户余额字段优先级(基于 95598 真实 Vue state 字段含义)：
        #   accountBalance=账户余额(最明确) / prepayBal=预付费余额
        #   排除 sumMoney(上月用电金额，如127) 和 historyOwe(历史欠费，应交金额)
        #
        # For pre-paid customers in Beijing, `sumMoney` is the pre-paid balance while `prepayBal` is 0.
        # I have to make a guess that this difference is handled by `consType` or `sceneType`.
        # "mixinGetYuEdata": {
        # "date": "2026-07-07 13:31:41",
        # "prepayBal": "0",
        # "consType": "1",
        # "amtTime": "2026-07-07 00:00:00",
        # "historyOwe": "0",
        # "proCode": "11102",
        # "sumMoney": "127.0",
        # "sceneType": "03",
        # "penalty": "0",
        # "totalPq": "336.0",
        # "consNo": "12345678",
        # "uuid": "123456789abcdef"
        # }
        # consType=1 北京预付费：sumMoney 是预付费余额，prepayBal 为 0
        # consType=0/其他 后付费：sumMoney 是上月金额(非余额)，取 accountBalance/prepayBal
        try:
            cons_type = int(raw.get("consType") or 0)
        except (TypeError, ValueError):
            cons_type = 0
        if cons_type == 1:
            candidates = ("sumMoney", "prepayBal", "accountBalance")
        else:
            candidates = ("accountBalance", "prepayBal", "balance")
        for key in candidates:
            val = _safe_float(raw.get(key))
            if val is not None:
                result["balance"] = val
                break
            if val is not None:
                result["balance"] = val
                break

    # elecItemData 仅用于补充户号，不再用 oweAmt 覆盖余额
    # (oweAmt 对后付费账户是应交金额，会错误覆盖上面的真实余额)
    elec = _first_data_value(components, "elecItemData")
    if isinstance(elec, dict):
        if not result["user_id"]:
            result["user_id"] = str(elec.get("consNo") or elec.get("consId") or "").strip()

    if not result["user_id"]:
        user_info = normalize_user_info(components)
        result["user_id"] = str(user_info.get("user_id") or "").strip()

    expected = str(expected_user_id or "").strip()
    if expected and result["user_id"] and result["user_id"] != expected:
        result["user_mismatch"] = True
    return result


def _first_data_value(components: list[dict[str, Any]], key: str) -> Any:
    for component in components:
        data = component.get("data") or {}
        if key in data:
            return data[key]
    return None


def _data_values(components: list[dict[str, Any]], key: str) -> list[Any]:
    return [(component.get("data") or {}).get(key) for component in components if key in (component.get("data") or {})]


def _pick_daily_rows(components: list[dict[str, Any]], keys: tuple[str, ...], require_tou: bool) -> list[Any]:
    """从 Vue state 中选择最合适的日用电列表（优先条数更多的）。"""
    best: list[Any] = []
    tou_field = "thisVPq"
    total_field = "dayElePq"
    for key in keys:
        for row in _data_values(components, key):
            if not isinstance(row, list) or not row:
                continue
            if require_tou:
                if not any(item.get(tou_field) is not None for item in row if isinstance(item, dict)):
                    continue
            elif not any(item.get(total_field) is not None for item in row if isinstance(item, dict)):
                continue
            if len(row) > len(best):
                best = row
    return best


def _normalize_usage_month(row: dict[str, Any]) -> dict[str, Any]:
    total = _safe_float(row.get("monthEleNum"))
    charge = _safe_float(row.get("monthEleCost"))
    return {
        "month": _normalize_ym(row.get("month")),
        "total_usage": total,
        "total_charge": charge,
        "begin_date": row.get("begDate"),
        "end_date": row.get("endDate"),
        "meter_read_time": row.get("mrDate"),
        "is_max": bool(row.get("max")),
    }


def _normalize_daily_row(row: dict[str, Any], year: str = "") -> Optional[dict[str, Any]]:
    date = _normalize_date(row.get("day"), year)
    if not date:
        return None
    total = _safe_float(row.get("dayElePq"), default=0.0)
    return {
        "date": date,
        "total_usage": total,
        "valley_usage": _safe_float(row.get("thisVPq"), default=0.0),
        "flat_usage": _safe_float(row.get("thisNPq"), default=0.0),
        "peak_usage": _safe_float(row.get("thisPPq"), default=0.0),
        "tip_usage": _safe_float(row.get("thisTPq"), default=0.0),
    }


def _normalize_date(value: Any, year: str = "") -> str:
    """将日期统一为 YYYY-MM-DD 格式"""
    text = str(value or "").strip()
    if not text:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text
    m = re.match(r"^(\d{1,2})/(\d{1,2})$", text)
    if m:
        y = year or str(datetime.now().year)
        return f"{y}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.match(r"^(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})$", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return text


def _normalize_ym(value: Any) -> str:
    text = str(value or "").strip().replace("/", "-")
    if len(text) == 6 and text.isdigit():
        return f"{text[:4]}-{text[4:]}"
    if len(text) >= 7:
        return text[:7]
    return text


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        text = str(value).strip()
        if text in ("", "-", "—", "None"):
            return default
        return float(text)
    except (TypeError, ValueError):
        return default
