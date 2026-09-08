from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etfmate.analysis.t_grid import analyze_single_etf_for_t_grid, estimate_t_grid_backtest_metrics
from etfmate.report.daily_report import render_html


def test_t_grid_candidate_uses_t_grid_name_and_default_1000_qty():
    result = analyze_single_etf_for_t_grid("159999", _sideways_df(), name="测试ETF")

    assert result.is_t_grid_candidate is True
    assert result.t_grid_action == "观察，待不亏卖出核验"
    assert result.can_open_t_grid is False
    assert result.should_pause_sell is True
    assert result.should_pause_buy is True
    assert result.grid_qty == 1000
    assert result.grid_count_up >= 2
    assert result.grid_count_down >= 2
    assert "SwingGrid" not in str(result.to_dict())


def test_t_grid_rejects_low_liquidity_with_reason():
    result = analyze_single_etf_for_t_grid("159999", _sideways_df(amount=10_000_000), name="测试ETF")

    assert result.is_t_grid_candidate is False
    assert any("成交额" in reason for reason in result.reject_reason)
    assert result.t_grid_action in {"关闭T网格", "观察，不开启T网格"}


def test_t_grid_rejects_edge_range_without_two_sided_space():
    df = _sideways_df()
    df.loc[df.index[-1], "close"] = df["high"].tail(20).max() * 0.999
    df.loc[df.index[-1], "high"] = df.loc[df.index[-1], "close"] * 1.01
    df.loc[df.index[-1], "low"] = df.loc[df.index[-1], "close"] * 0.99

    result = analyze_single_etf_for_t_grid("159999", df, name="测试ETF")

    assert result.is_t_grid_candidate is False
    assert any("向上可卖空间不足2格" in reason or "箱体上沿" in reason for reason in result.reject_reason)


def test_t_grid_backtest_conservative_path_does_not_double_count_same_day_loop():
    df = pd.DataFrame(
        {
            "open": [1.0] * 80,
            "high": [1.04] * 80,
            "low": [0.96] * 80,
            "close": [1.0] * 80,
            "volume": [1_000_000] * 80,
            "amount": [100_000_000] * 80,
        }
    )

    result = estimate_t_grid_backtest_metrics(df, grid_step_pct=2.0, grid_qty=1000, backtest_days=40, max_holding_days=5)

    assert result.triggered_grid_count == result.backtest_days
    assert result.avg_triggered_grids_per_day == 1.0


def _sideways_df(days: int = 123, amount: float = 120_000_000) -> pd.DataFrame:
    rows = []
    pattern = [0.94, 1.06, 1.0]
    for idx in range(days):
        close = pattern[idx % len(pattern)]
        rows.append(
            {
                "trade_date": f"2026-01-{idx + 1:02d}",
                "open": close,
                "high": close + 0.03,
                "low": close - 0.03,
                "close": close,
                "volume": 1_000_000,
                "amount": amount,
            }
        )
    return pd.DataFrame(rows)


def _report_item(code: str, name: str) -> dict:
    return {
        "code": code,
        "name": name,
        "action": "观察",
        "quantity": None,
        "last_price": 1.0,
        "pct_chg": 0.0,
        "is_watchlist_candidate": True,
        "candidate_source": "自选ETF池",
        "rule_trend_score": 60,
        "rule_decision": {"trend_score": 60, "trend_level": "震荡观察", "risk_level": "LOW"},
    }
