import pytest
from etfmate.analysis.grid_advisor import advise_grid
from etfmate.storage.models import GridConfig, MarketSnapshot, Position


def advice(total=50, quantity=2100):
    market = MarketSnapshot("510500", "中证500ETF", 1, 0, 1000000, 300000000, atr14_pct=2)
    position = Position("510500", "中证500ETF", quantity, 1.2, 1, quantity, 0, 0)
    grid = GridConfig("510500", "中证500ETF", True, base_price=1, buy_quantity=500, sell_quantity=300)
    return advise_grid(grid, market, position, {"portfolio": {"total_position_pct": total}})


@pytest.mark.parametrize("total", [80, 90.83])
def test_portfolio_limit_disables_buy_without_blocking_partial_loss_sale(total):
    result = advice(total)
    assert result["buy_execution_status"] == "DISABLED"
    assert result["candidate_buy_quantity"] is None
    assert result["sell_policy"]["sell_allowed"] is True
    assert result["candidate_sell_quantity"] == 300
    assert result["suggested_sell_quantity"] is None  # Inventory still unverified.
    assert result["minimum_sell_price"] is None


def test_below_limit_still_requires_budget():
    result = advice(79.9)
    assert result["buy_execution_status"] == "PENDING_BUDGET"
    assert result["candidate_buy_quantity"] == 500
    assert result["suggested_buy_quantity"] is None
    assert result["grid_applicable"] is False


@pytest.mark.parametrize("quantity", [100, 199, 200, 399, 2100])
def test_grid_sell_never_exhausts_inventory(quantity):
    result = advice(quantity=quantity)
    sell = result["candidate_sell_quantity"]
    if sell is not None:
        assert sell > 0 and sell % 100 == 0
        assert quantity - sell >= result["suggested_min_base_quantity"] >= 100
    else:
        assert result["sell_execution_status"] == "DISABLED"
