"""Closed-pool planning from the captured ledger and original condition settings."""
from __future__ import annotations

from math import floor, isfinite
import re
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", "").replace("−", "-").strip())
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _nonnegative(value: Any) -> float | None:
    result = _number(value)
    return result if result is not None and result >= 0 else None


def _percentage(value: Any) -> float | None:
    result = _number(str(value).replace("%", ""))
    return abs(result) if result is not None else None


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _uploaded_at(account: dict[str, Any]) -> str | None:
    summary = account.get("account_summary") or {}
    direct = summary.get("source_uploaded_at") or account.get("source_uploaded_at")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    snapshot = account.get("snapshot") or {}
    found = re.search(r"最新上传时间\s*[:：]\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)",
                      str(snapshot.get("text") or ""))
    return found.group(1) if found else None


def _condition_estimate(condition: dict[str, Any], index: int,
                        positions: dict[str, float] | None) -> dict[str, Any]:
    code = str(condition.get("code") or "")
    kind = condition.get("condition_type") or "unknown"
    enabled = condition.get("enabled")
    active_buy = enabled is True and kind in {"grid", "buy_only"}
    raw_quantity = condition.get("buy_quantity")
    if raw_quantity is None:
        raw_quantity = condition.get("order_quantity")
    quantity = _number(raw_quantity)
    quantity_valid = quantity is not None and quantity >= 100 and quantity % 100 == 0
    held = positions.get(code, 0.0) if positions is not None else None
    maximum = _nonnegative(condition.get("max_position_quantity"))
    headroom = max(0.0, maximum - held) if maximum is not None and held is not None else None
    trigger = example = None
    basis = "UNAVAILABLE"
    limits: list[str] = []
    limit_codes: list[str] = []

    def limit(identifier: str, message: str) -> None:
        limit_codes.append(identifier)
        limits.append(message)

    if kind == "grid":
        base = _number(condition.get("base_price"))
        fall, rebound = _percentage(condition.get("buy_fall_pct")), _percentage(condition.get("buy_rebound_pct"))
        if base is not None and base > 0 and fall is not None and 0 < fall < 100 and rebound is not None and rebound > 0:
            trigger = base * (1 - fall / 100)
            example = trigger * (1 + rebound / 100)
            basis = "GRID_TRIGGER_TROUGH_EXAMPLE"
        elif active_buy:
            limit("MISSING_PRICE_PARAMETERS", "缺少有效原单基准、下跌或反弹参数，不能估算首轮金额。")
    elif kind == "buy_only":
        # This is an exposure reference, not a claim that the -5% condition starts at this price.
        gate = _number(condition.get("entry_gate_price"))
        if gate is None:
            match = re.search(r"低于\s*[（(]含[）)]\s*([\d.]+)\s*元", str(condition.get("raw_text") or ""))
            gate = _number(match.group(1)) if match else None
        if gate is not None and gate > 0:
            trigger = example = gate
            basis = "ENTRY_GATE_PRICE_REFERENCE"
        elif active_buy:
            limit("MISSING_ENTRY_GATE", "缺少分批建仓门槛价，不能估算首轮金额。")
        if active_buy:
            limit("ENTRY_PATH_UNVERIFIED", "金额仅按入场门槛价估算；后续跌幅基准及即时卖一委托价不等于该门槛价。")
    elif enabled is True and kind != "sell_only":
        limit("UNCLASSIFIED_CONDITION", "条件单类型未识别，不能确认潜在买入金额。")

    if active_buy and not quantity_valid:
        limit("INVALID_BUY_QUANTITY", "原单买入数量缺失或不符合100份起、100份整数倍，不能作为合法首轮买量。")
    if active_buy and maximum is not None and held is None:
        limit("INVENTORY_UNKNOWN", "缺少当前持仓，不能核对最大持仓余量。")
    if active_buy and headroom is not None and quantity is not None and quantity > headroom:
        limit("BUY_EXCEEDS_MAX_POSITION", f"原单买{quantity:g}份超过当前最大持仓余量{headroom:g}份，不能当作可执行单笔量。")
    if active_buy:
        limit("MONITORING_NOT_RESERVATION", "监控中表示潜在触发，不证明已自动委托或冻结；该金额不从账本现金预扣。")
    if enabled is None:
        limit("MONITORING_STATE_UNKNOWN", "缺少条件单是否监控的状态，首轮合计可能不完整。")

    amount = example * quantity if active_buy and example is not None and quantity_valid else None
    return {
        "index": index, "code": code, "name": condition.get("name"), "condition_type": kind,
        "enabled": enabled, "source_status": condition.get("status"), "active_buy": active_buy,
        "buy_quantity": quantity, "buy_quantity_valid": quantity_valid,
        "held_quantity": held, "max_position_quantity": maximum,
        "buy_headroom_quantity": headroom,
        "max_buy_quantity_by_inventory": floor(headroom / 100) * 100 if headroom is not None else None,
        "buy_trigger_reference": _round(trigger), "buy_price_example": _round(example),
        "first_cycle_estimated_cash": _round(amount), "estimate_basis": basis,
        "included_in_first_cycle": amount is not None,
        "broker_order_status": condition.get("broker_order_status") or condition.get("order_status"),
        "last_trigger_time": condition.get("last_trigger_time"),
        "limitation_codes": limit_codes, "limitations": limits,
    }


def build_funding_plan(account: dict[str, Any], conditions: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Use ledger cash once; monitoring exposure is neither reserved cash nor proceeds."""
    summary = account.get("account_summary") or {}
    cash = _nonnegative(summary.get("cash"))
    total = _number(summary.get("total_asset"))
    total = total if total is not None and total > 0 else None
    value = _nonnegative(summary.get("total_market_value"))
    positions: dict[str, float] | None = {} if isinstance(account.get("positions"), list) else None
    for position in account.get("positions") or []:
        quantity = _nonnegative(position.get("quantity"))
        if quantity is None:
            positions = None
            break
        code = str(position.get("code") or "")
        positions[code] = positions.get(code, 0.0) + quantity
    rows = [_condition_estimate(row, index, positions) for index, row in enumerate(conditions or [], start=1)]
    active = [row for row in rows if row["active_buy"]]
    complete = conditions is not None and all(row["first_cycle_estimated_cash"] is not None for row in active)
    complete = complete and not any("UNCLASSIFIED_CONDITION" in row["limitation_codes"] or "MONITORING_STATE_UNKNOWN" in row["limitation_codes"] for row in rows)
    known = sum(row["first_cycle_estimated_cash"] or 0 for row in active)
    estimated = known if complete else None
    cap_room = 0.8 * total - value if total is not None and value is not None else None
    notes = [
        "以用户确认自动同步的账本现金、持仓作为采集时点的封闭资金池计划依据；不追加资金。",
        "监控条件单不是冻结资金；不从现金中预扣名义首轮金额，也不再次累加账本中的历史卖出回款。",
        "80%仅作为新增买入门槛，不是强制降仓或最大回撤限额；买入额度只表示现金与仓位的交集，还需满足价格、风险与各原单库存条件。",
        "首轮金额为每条监控买入条件各触发一笔的名义情景，含超出库存上限的原单；不是执行许可或同时成交预测。",
        "网格按低点恰好等于下跌触发价后反弹估算；分批建仓按入场门槛价估算。实际路径与委托价会改变金额。",
        "源账本上传时间仅保留来源信息，不据此认定自动同步持仓已过期；自动委托和冻结须依据真实订单状态。",
    ]
    if not complete:
        notes.append("部分条件状态或金额不可计算，总首轮金额与总缺口留空；已知金额仅是可计算部分。")
    if cash is None:
        notes.append("缺少有效账本现金余额，不能用总资产减持仓或历史卖出额补造现金基数。")
    return {
        "contract": "closed_pool_funding_v1", "cash": cash, "total_asset": total, "market_value": value,
        "position_pct": _round(value / total * 100) if total is not None and value is not None else None,
        "position_cap_pct": 80.0,
        "buy_capacity_under_cap": _round(min(cash, max(0.0, cap_room))) if cash is not None and cap_room is not None else None,
        "required_net_sell_to_cap": _round(max(0.0, -cap_room)) if cap_room is not None else None,
        "first_cycle_estimated_cash": _round(estimated), "known_first_cycle_estimated_cash": _round(known),
        "shortfall": _round(max(0.0, estimated - cash)) if estimated is not None and cash is not None else None,
        "estimate_complete": complete, "condition_count": len(rows), "active_buy_condition_count": len(active),
        "source_uploaded_at": _uploaded_at(account), "cash_basis": "LEDGER_CASH_BALANCE",
        "monitoring_is_frozen": False, "conditions": rows, "notes": notes,
    }
