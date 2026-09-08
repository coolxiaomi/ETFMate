from dataclasses import replace

import pytest

from etfmate.analysis.sell_policy import assess_sell_policy
from etfmate.storage.models import MarketSnapshot, Position


def inputs():
    return (Position("510500", "测试", 1000, 1, 0.8, 800, -200, -20,
                     net_invested_amount=1000, cost_basis_verified=True),
            MarketSnapshot("510500", "测试", 0.8, 0, 1000000, 300000000))


def test_partial_loss_changes_final_liquidation_floor():
    position, market = inputs()
    partial = assess_sell_policy(position, market, sell_quantity=200)
    assert partial["sell_allowed"] is True
    assert partial["minimum_sell_price"] is None
    assert partial["projected_remaining_net_investment"] == 840
    assert partial["projected_liquidation_floor"] == 1.05
    remaining = replace(position, quantity=800, net_invested_amount=840)
    assert assess_sell_policy(remaining, market, sell_price=1)["status"] == "BLOCKED_LIQUIDATION_LOSS"
    assert assess_sell_policy(remaining, market, sell_price=1.05)["sell_allowed"] is True


@pytest.mark.parametrize("quantity", [None, 1000])
def test_unknown_or_full_quantity_cannot_bypass_liquidation(quantity):
    position, market = inputs()
    assert assess_sell_policy(position, market, sell_quantity=quantity)["sell_allowed"] is False


@pytest.mark.parametrize("quantity", [0, -100, 1100, float("nan"), float("inf")])
def test_invalid_quantity_is_blocked(quantity):
    position, market = inputs()
    assert assess_sell_policy(position, market, sell_quantity=quantity)["status"] == "PENDING_VERIFICATION"


@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf")])
def test_invalid_price_is_blocked(price):
    position, market = inputs()
    assert assess_sell_policy(position, market, sell_price=price, sell_quantity=200)["sell_allowed"] is False


def test_displayed_profit_or_cost_does_not_verify_net_investment():
    position, market = inputs()
    position.cost_basis_verified = False
    position.pnl_pct = 99
    assert assess_sell_policy(position, market, sell_price=2)["status"] == "PENDING_COST_BASIS"
    assert assess_sell_policy(position, market, sell_quantity=200)["sell_allowed"] is True


@pytest.mark.parametrize("net", [0, -100])
def test_recovered_principal_allows_positive_price_liquidation(net):
    position, market = inputs()
    position.net_invested_amount = net
    policy = assess_sell_policy(position, market)
    assert policy["sell_allowed"] is True
    assert policy["minimum_sell_price"] == 0
    assert policy["fees_ignored"] is True
