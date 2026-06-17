from etfmate.analysis.grid_advisor import advise_grid
from etfmate.storage.models import GridConfig, MarketSnapshot


def test_grid_too_dense():
    grid = GridConfig(code="510300", name="沪深300ETF", enabled=True, grid_step_pct=0.3)
    market = MarketSnapshot(code="510300", name="沪深300ETF", last_price=4, pct_chg=0, volume=1, amount=1, atr14_pct=1)
    assert advise_grid(grid, market)["action"] == "调宽网格"
