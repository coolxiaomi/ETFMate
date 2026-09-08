"""Derive settlement-eligible inventory from the synchronized account ledger."""
from __future__ import annotations

import re
from datetime import date, datetime
from math import isfinite
from typing import Any

from etfmate.analysis import account_strategy
from etfmate.analysis.instrument_rules import get_instrument_rule


INVENTORY_CONTRACT = "ledger_settlement_inventory_v1"


def build_inventory_plan(account: dict, as_of_date: str | date | datetime) -> dict[str, dict[str, Any]]:
    """This is a ledger derivation, not a broker's unfilled-order balance.

    Current quantity already reflects completed sells. T+1 therefore subtracts
    today's gross buys only; subtracting completed sells again double-counts them.
    """
    observation_date = _date(as_of_date)
    if observation_date is None:
        raise ValueError("库存推导需要有效的采集日期")
    facts = getattr(account_strategy, "USER_ACCOUNT_FACTS", {})
    auto_sync = facts.get("auto_sync_fills") is True
    upload_time = _latest_upload_time(account)
    # The upload label is provenance, not a later fill cutoff, once auto-sync is confirmed.
    ledger_date = observation_date if auto_sync or upload_time is None else _date(upload_time)
    trade_snapshots = account.get("trade_snapshots") or {}
    month = trade_snapshots.get("本月") if isinstance(trade_snapshots, dict) else None
    trades_complete = isinstance(month, dict) and month.get("scroll_complete") is True
    positions_complete = (account.get("snapshot") or {}).get("scroll_complete") is True
    daily = _daily_buys(account, ledger_date)
    result = {}
    for position in account.get("positions") or []:
        if not isinstance(position, dict):
            continue
        code = _code(_pick(position, "code", "symbol", "stockCode", "zqdm", "证券代码", "代码"))
        if not code:
            continue
        quantity = _number(_pick(position, "quantity", "amount", "holdAmount", "current_amount", "持仓数量", "持有数量", "股份余额"))
        instrument = get_instrument_rule(code)
        settlement = instrument.get("settlement", "UNKNOWN")
        buys = daily.get(code, {"quantity": 0.0, "ambiguous": False, "invalid": False, "evidence": []})
        valid_quantity = quantity is not None and quantity >= 0 and quantity.is_integer()
        observed_buys = buys["quantity"]
        remaining = quantity - observed_buys if valid_quantity else None
        quality = "AS_OF_COLLECTION_DERIVED" if auto_sync else "LEDGER_SNAPSHOT"
        sellable = None
        if not valid_quantity:
            quality, note = "INVALID_POSITION", "账本持仓数量不是有效的非负整数，保留原始持仓证据后重采。"
        elif settlement == "UNKNOWN":
            quality, note = "UNKNOWN_SETTLEMENT", "该标的交易回转规则尚未核实，保留持仓数量，不默认按T+1或T+0计算。"
        elif not positions_complete:
            quality, note = "PENDING_POSITION_COMPLETENESS", "持仓列表未确认采齐，先完成采集再推导库存。"
        elif settlement == "T0":
            sellable = quantity
            note = f"按已核实T+0规则，账本持仓{quantity:g}份均具备当日卖出资格。"
        elif buys["invalid"]:
            quality, note = "PENDING_TRADE_FIELDS", "该标的买入记录日期、方向或数量不完整，不能确定当日新增库存。"
        elif buys["ambiguous"]:
            quality, note = "AMBIGUOUS_TODAY_BUYS", "该标的当日买入记录存在去重歧义；已观察买入仅是下限，可卖量不能按该下限认定。"
        elif not trades_complete:
            quality, note = "PENDING_TRADE_COMPLETENESS", "本月交易列表未确认完整，缺少当日买入记录不能解释为买入0份。"
        elif remaining is not None and remaining < 0:
            quality, note = "INCONSISTENT_INVENTORY", "T+1当日累计买入多于当前持仓，持仓与成交时点或记录口径不一致，需重采核对。"
        else:
            sellable = remaining
            note = f"按T+1规则：账本持仓{quantity:g}−当日累计买入{observed_buys:g}＝可卖{sellable:g}份；当日已成交卖出已反映在持仓中，不再重复扣减。"
        if not auto_sync:
            note += " 此为账本上传时点推导，未确认成交自动同步，不能称为当前券商可卖量。"
        sync_note = (
            "用户已确认Touker条件单成交自动同步同花顺账本；上传时间仅作来源记录，以本次完整采集的持仓与当日成交推导。"
            if auto_sync else "未确认条件单成交自动同步，以账本上传时点说明数据范围。"
        )
        result[code] = {
            "contract": INVENTORY_CONTRACT, "code": code, "quantity": quantity,
            "settlement": settlement, "sellable_quantity": sellable,
            "settlement_eligible_quantity": sellable,
            "today_buy_quantity": observed_buys if trades_complete and not buys["ambiguous"] and not buys["invalid"] else None,
            "observed_today_buy_quantity": observed_buys,
            "sellable_quantity_upper_bound": max(0.0, remaining) if settlement == "T1" and remaining is not None and sellable is None else None,
            "quantity_basis": "SETTLEMENT_ELIGIBLE_BEFORE_UNFILLED_SELL_ORDERS",
            "quality": quality, "source": "THS_LEDGER_DERIVED", "broker_verified": False,
            "as_of_date": observation_date.isoformat(), "ledger_date": ledger_date.isoformat(),
            "upload_time": upload_time, "syncnote": sync_note, "note": note,
            "user_fact_basis": {"auto_sync_fills": auto_sync, "confirmed_on": facts.get("confirmed_on")},
            "rule_source_urls": list(instrument.get("source_urls") or []),
            "rule_verified_on": instrument.get("verified_on"),
            "trade_source_evidence": buys["evidence"],
            "reservation_note": "未扣已触发但未成交卖单占用；监控中的条件本身不等于冻结库存，重叠卖单由条件单配置方案统一约束。",
        }
    return result


def _daily_buys(account: dict, as_of_date: date) -> dict[str, dict]:
    result: dict[str, dict] = {}
    quality = account.get("trade_collection_quality") or {}
    ambiguous_keys = {str(item.get("key") or "") for item in quality.get("ambiguities") or [] if isinstance(item, dict)}
    seen_ids: dict[tuple[str, str], tuple] = {}
    for trade in account.get("trades") or []:
        if not isinstance(trade, dict):
            continue
        code = _code(_pick(trade, "code", "symbol", "stockCode", "zqdm", "证券代码", "代码"))
        if not code:
            continue
        row = result.setdefault(code, {"quantity": 0.0, "ambiguous": False, "invalid": False, "evidence": []})
        trade_date = _date(_pick(trade, "trade_date", "成交日期", "日期"))
        side = str(_pick(trade, "side", "bsFlag", "business_name", "买卖方向", "方向", "类型") or "").strip().upper()
        is_buy = side in {"买入", "证券买入", "基金买入", "买", "BUY", "B"}
        is_sell = side in {"卖出", "证券卖出", "基金卖出", "卖", "SELL", "S"}
        if (is_buy and trade_date is None) or (trade_date == as_of_date and not is_buy and not is_sell):
            row["invalid"] = True
        if trade_date != as_of_date or not is_buy:
            continue
        quantity = _number(_pick(trade, "quantity", "dealAmount", "成交数量", "数量"))
        if quantity is None or quantity <= 0 or not quantity.is_integer():
            row["invalid"] = True
            continue
        identity = _pick(trade, "trade_id", "成交编号")
        if identity not in (None, ""):
            id_key = (code, str(identity))
            economic = (trade_date, side, quantity, _pick(trade, "price", "成交价"))
            if id_key in seen_ids:
                row["ambiguous"] = row["ambiguous"] or seen_ids[id_key] != economic
                continue
            seen_ids[id_key] = economic
        row["quantity"] += quantity
        row["ambiguous"] = row["ambiguous"] or trade.get("occurrence_ambiguous") is True or str(trade.get("source_occurrence_key") or "") in ambiguous_keys
        row["evidence"].extend(trade.get("source_evidence") or [])
    # A quality record may outlive its discarded duplicate row. Scope it to code/date/buy.
    for key in ambiguous_keys:
        parts = key.split(":")
        if len(parts) < 4 or parts[0] != "fields" or _date(parts[2]) != as_of_date:
            continue
        if parts[3].strip().upper() not in {"买入", "证券买入", "基金买入", "买", "BUY", "B"}:
            continue
        code = _code(parts[1])
        if code:
            result.setdefault(code, {"quantity": 0.0, "ambiguous": False, "invalid": False, "evidence": []})["ambiguous"] = True
    return result


def _latest_upload_time(account: dict) -> str | None:
    text = str((account.get("snapshot") or {}).get("text") or "")
    values = re.findall(r"最新上传时间\s*[:：]?\s*(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})\s+(\d{1,2}:\d{2}(?::\d{2})?)", text)
    parsed = []
    for day, clock in values:
        normalized = _date(day)
        if normalized is not None:
            try:
                parsed.append(datetime.fromisoformat(f"{normalized.isoformat()} {clock}"))
            except ValueError:
                pass
    return max(parsed).isoformat(sep=" ", timespec="minutes") if parsed else None


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    match = re.match(r"^(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", str(value or "").strip())
    if match:
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            pass
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
        return number if isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _code(value: Any) -> str:
    text = re.sub(r"^(sh|sz)|\.(sh|sz)$", "", str(value or "").strip(), flags=re.I)
    return text if re.fullmatch(r"\d{6}", text) else ""


def _pick(row: dict, *keys: str) -> Any:
    return next((row[key] for key in keys if row.get(key) not in (None, "")), None)
