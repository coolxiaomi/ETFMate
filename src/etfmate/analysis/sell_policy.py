from __future__ import annotations

from math import isfinite
from etfmate.storage.models import MarketSnapshot, Position

NO_LOSS_RULE = "允许浮亏及低于成本的部分卖出；最终清仓须收回本轮净投入本金，交易费用忽略。分批卖出和连续网格不得绕过清仓核验。"


def assess_sell_policy(position: Position | None, market: MarketSnapshot, *,
                       sell_price: float | None = None, sell_quantity: float | None = None) -> dict:
    """Unknown quantity is liquidation. Displayed average cost is not proof of net investment."""
    quantity = position.quantity if position else 0
    price = market.last_price if sell_price is None else sell_price
    proposed = quantity if sell_quantity is None else sell_quantity
    valid = all(isfinite(v) and v > 0 for v in (quantity, price, proposed)) and proposed <= quantity
    partial = valid and proposed < quantity
    net = position.net_invested_amount if position else None
    verified = bool(position and position.cost_basis_verified and net is not None and isfinite(net))
    floor = max(0.0, net / quantity) if verified and quantity > 0 else None
    cost = position.cost_price if position else None
    reference = cost if cost is not None and isfinite(cost) and cost > 0 else None
    if not valid:
        status, allowed, reason = "PENDING_VERIFICATION", False, "持仓、卖价或卖出数量无效，暂不输出卖出指令。"
    elif partial:
        status, allowed = "PARTIAL_ALLOWED", True
        reason = "部分卖出允许低于成本；成交后须更新剩余净投入与清仓回本价。最后一笔另行核验，不能靠多次触发清空持仓。"
    elif not verified:
        status, allowed = "PENDING_COST_BASIS", False
        reason = "等待清仓成本核验：页面成本仅作参考，需核实本轮累计买入、已成交卖出及分红后的剩余净投入。"
    elif price * quantity + 1e-8 < net:
        status, allowed = "BLOCKED_LIQUIDATION_LOSS", False
        reason = f"清仓会亏本，等待可执行卖价不低于 {floor:.3f}；交易费用忽略。"
    else:
        status, allowed = "LIQUIDATION_CONDITIONAL", True
        reason = f"参考价满足清仓回本条件；执行前更新净投入，以不低于 {floor:.3f} 的有效限价卖出，交易费用忽略。"
    remaining_quantity = quantity - proposed if valid else None
    remaining_net = net - proposed * price if valid and verified else None
    return {
        "rule": "NO_LOSS_ON_LIQUIDATION", "status": status, "sell_allowed": allowed,
        "sale_scope": "PARTIAL" if partial else "LIQUIDATION", "fees_ignored": True,
        "minimum_sell_price": None if partial else floor,
        "liquidation_floor": floor, "cost_price_reference": reference,
        "cost_basis_verified": verified, "remaining_net_investment": net if verified else None,
        "projected_remaining_quantity": remaining_quantity,
        "projected_remaining_net_investment": remaining_net,
        "projected_liquidation_floor": max(0.0, remaining_net / remaining_quantity) if partial and verified else None,
        "reason": reason,
    }
