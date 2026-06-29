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
    assert result.t_grid_action == "开启T网格"
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


def test_report_shows_t_grid_tab_for_all_watchlist_items_without_polluting_grid_tab():
    recommendations = [
        _report_item("159901", "候选ETF"),
        _report_item("159902", "拒绝ETF"),
    ]
    t_grids = [
        {
            "code": "159901",
            "name": "候选ETF",
            "source": "ths_watchlist",
            "is_t_grid_candidate": True,
            "t_grid_score": 78,
            "t_grid_level": "适合T网格",
            "t_grid_action": "开启T网格",
            "suggest_grid_step_pct": 2.0,
            "grid_upper": 1.08,
            "grid_lower": 0.92,
            "grid_count_up": 3,
            "grid_count_down": 3,
            "grid_qty": 1000,
            "one_grid_cash": 1000,
            "suggest_total_cash": 7200,
            "trigger_probability": 0.7,
            "hit_rate": 0.6,
            "avg_close_days": 2.2,
            "risk_adjusted_annual_return_pct": 12.3,
            "reason": ["适合震荡做T"],
            "risk": ["历史估算，不代表未来收益"],
            "reject_reason": [],
        },
        {
            "code": "159902",
            "name": "拒绝ETF",
            "source": "ths_watchlist",
            "is_t_grid_candidate": False,
            "t_grid_score": 42,
            "t_grid_level": "不适合T网格",
            "t_grid_action": "关闭T网格",
            "grid_qty": 1000,
            "reject_reason": ["20日平均成交额低于3000万"],
            "reason": [],
            "risk": ["成交额偏低"],
        },
    ]

    html = render_html("2026-06-29 10:00:00", recommendations, [], {}, {}, t_grids)
    grid_panel = html.split('data-panel="grid"', 1)[1].split('data-panel="strategy"', 1)[0]
    t_grid_panel = html.split('data-panel="tgrid"', 1)[1]

    assert "T网格" in html
    assert "自选池 2 只" in t_grid_panel
    assert 'href="#etf-159901"' in t_grid_panel
    assert 'href="#etf-159902"' in t_grid_panel
    assert 'href="#etf-159901"' not in grid_panel
    assert "20日平均成交额低于3000万" in html
    assert re.search(r"(?<!\d)0股", html) is None
    assert "可用数量为0" not in html
    assert "今日不可卖" not in html


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
