from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd


@dataclass
class TGridConfig:
    lookback_days: int = 60
    range_window: int = 20
    amplitude_window: int = 20
    atr_window: int = 14
    boll_window: int = 20
    boll_std: float = 2.0
    adx_window: int = 14
    grid_qty: int = 1000
    min_avg_amount_20: float = 30_000_000
    preferred_avg_amount_20: float = 50_000_000
    min_grid_step_pct: float = 0.8
    max_grid_step_pct: float = 3.0
    volatility_ratio_min: float = 1.5
    volatility_ratio_preferred: float = 2.0
    max_adx: float = 25
    preferred_adx: float = 20
    max_abs_ma20_slope_pct: float = 5
    preferred_abs_ma20_slope_pct: float = 2
    max_boll_width_pct: float = 25
    reserve_ratio: float = 0.2
    backtest_days: int = 60
    max_holding_days: int = 5
    annual_trade_days: int = 250
    path_mode: str = "conservative"


@dataclass
class TGridBacktestResult:
    backtest_days: int = 0
    triggered_grid_count: int = 0
    closed_grid_count: int = 0
    unclosed_grid_count: int = 0
    trigger_probability: float | None = None
    hit_rate: float | None = None
    avg_close_days: float | None = None
    avg_triggered_grids_per_day: float | None = None
    avg_closed_grids_per_day: float | None = None
    gross_profit: float = 0.0
    floating_pnl: float = 0.0
    net_profit: float = 0.0
    max_drawdown_pct: float = 0.0
    expected_annual_return_pct: float | None = None
    risk_adjusted_annual_return_pct: float | None = None


@dataclass
class TGridResult:
    code: str
    name: str | None = None
    source: str = "ths_watchlist"
    data_source: str | None = None
    data_sufficient: bool = False

    is_t_grid_candidate: bool = False
    t_grid_score: float = 0.0
    t_grid_level: str = "不适合T网格"
    t_grid_action: str = "观察，不开启T网格"

    close: float | None = None
    avg_amount_20: float | None = None
    avg_amplitude_20: float | None = None
    atr_pct: float | None = None
    boll_width_pct: float | None = None
    boll_position: float | None = None
    ma20_slope_pct: float | None = None
    ma60_slope_pct: float | None = None
    adx14: float | None = None
    adx_available: bool = False
    range_position: float | None = None
    range_width_pct: float | None = None

    suggest_grid_step_pct: float | None = None
    grid_upper: float | None = None
    grid_lower: float | None = None
    grid_count_up: int = 0
    grid_count_down: int = 0
    grid_qty: int = 1000

    one_grid_cash: float | None = None
    buy_cash_required: float | None = None
    base_position_cash_required: float | None = None
    basic_required_cash: float | None = None
    reserve_cash: float | None = None
    suggest_total_cash: float | None = None

    can_open_t_grid: bool = False
    should_pause_buy: bool = False
    should_pause_sell: bool = False
    should_close_t_grid: bool = False

    trigger_probability: float | None = None
    hit_rate: float | None = None
    avg_close_days: float | None = None
    avg_triggered_grids_per_day: float | None = None
    avg_closed_grids_per_day: float | None = None

    one_grid_profit: float | None = None
    expected_daily_profit: float | None = None
    expected_annual_profit: float | None = None
    expected_annual_return_pct: float | None = None
    conservative_annual_return_pct: float | None = None
    risk_adjusted_annual_return_pct: float | None = None

    score_parts: dict[str, float] = field(default_factory=dict)
    backtest: dict[str, Any] = field(default_factory=dict)
    reason: list[str] = field(default_factory=list)
    risk: list[str] = field(default_factory=list)
    reject_reason: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_t_grid_candidates(
    etf_daily_data_map: dict[str, pd.DataFrame],
    etf_name_map: dict[str, str] | None = None,
    user_grid_step_pct: float | None = None,
    grid_qty: int = 1000,
    min_avg_amount_20: float = 30_000_000,
    reserve_ratio: float = 0.2,
    data_source_map: dict[str, str] | None = None,
) -> list[TGridResult]:
    config = TGridConfig(grid_qty=grid_qty, min_avg_amount_20=min_avg_amount_20, reserve_ratio=reserve_ratio)
    results: list[TGridResult] = []
    for code, df in etf_daily_data_map.items():
        try:
            result = analyze_single_etf_for_t_grid(
                code=code,
                df=df,
                name=(etf_name_map or {}).get(code),
                user_grid_step_pct=user_grid_step_pct,
                config=config,
                data_source=(data_source_map or {}).get(code),
            )
        except Exception as exc:
            result = TGridResult(
                code=code,
                name=(etf_name_map or {}).get(code),
                grid_qty=grid_qty,
                data_source=(data_source_map or {}).get(code),
                reject_reason=[f"T网格分析异常: {type(exc).__name__}"],
                risk=["该 ETF 本次 T网格分析失败，不能据此开启条件单"],
            )
        results.append(result)
    return sorted(results, key=_result_sort_key, reverse=True)


def analyze_single_etf_for_t_grid(
    code: str,
    df: pd.DataFrame,
    name: str | None = None,
    user_grid_step_pct: float | None = None,
    grid_qty: int = 1000,
    min_avg_amount_20: float = 30_000_000,
    reserve_ratio: float = 0.2,
    config: TGridConfig | None = None,
    data_source: str | None = None,
) -> TGridResult:
    cfg = config or TGridConfig(grid_qty=grid_qty, min_avg_amount_20=min_avg_amount_20, reserve_ratio=reserve_ratio)
    result = TGridResult(code=code, name=name, grid_qty=cfg.grid_qty, data_source=data_source)
    if df is None or len(df) < cfg.lookback_days:
        result.reject_reason.append("K线不足60个交易日，无法判断震荡结构")
        result.risk.append("数据不足，不生成T网格建议")
        return result

    indicators = calc_t_grid_indicators(df, cfg)
    latest = indicators.tail(1).iloc[0]
    result.data_sufficient = True
    params = advise_t_grid_params(latest, user_grid_step_pct=user_grid_step_pct, grid_qty=cfg.grid_qty, reserve_ratio=cfg.reserve_ratio, cfg=cfg)
    score, score_parts = calc_t_grid_score(latest, params["grid_step_pct"], cfg)
    reject_reason, risk = _hard_filters(latest, params, cfg)
    lifecycle = decide_t_grid_lifecycle(latest, score, params["grid_step_pct"], params["grid_count_up"], params["grid_count_down"], reject_reason, cfg)
    backtest = estimate_t_grid_backtest_metrics(
        indicators,
        params["grid_step_pct"],
        grid_qty=cfg.grid_qty,
        suggest_total_cash=params["suggest_total_cash"],
        backtest_days=cfg.backtest_days,
        max_holding_days=cfg.max_holding_days,
        annual_trade_days=cfg.annual_trade_days,
        path_mode=cfg.path_mode,
    )

    result.close = _round_or_none(latest.get("close"), 4)
    result.avg_amount_20 = _round_or_none(latest.get("avg_amount_20"), 2)
    result.avg_amplitude_20 = _round_or_none(latest.get("avg_amplitude_20"), 2)
    result.atr_pct = _round_or_none(latest.get("atr_pct"), 2)
    result.boll_width_pct = _round_or_none(latest.get("boll_width_pct"), 2)
    result.boll_position = _round_or_none(latest.get("boll_position"), 4)
    result.ma20_slope_pct = _round_or_none(latest.get("ma20_slope_pct"), 2)
    result.ma60_slope_pct = _round_or_none(latest.get("ma60_slope_pct"), 2)
    result.adx14 = _round_or_none(latest.get("adx14"), 2)
    result.adx_available = result.adx14 is not None
    result.range_position = _round_or_none(latest.get("range_position"), 4)
    result.range_width_pct = _round_or_none(latest.get("range_width_pct"), 2)

    result.suggest_grid_step_pct = _round_or_none(params["grid_step_pct"], 2)
    result.grid_upper = _round_or_none(params["grid_upper"], 4)
    result.grid_lower = _round_or_none(params["grid_lower"], 4)
    result.grid_count_up = params["grid_count_up"]
    result.grid_count_down = params["grid_count_down"]
    result.grid_qty = params["grid_qty"]
    result.one_grid_cash = _round_or_none(params["one_grid_cash"], 2)
    result.buy_cash_required = _round_or_none(params["buy_cash_required"], 2)
    result.base_position_cash_required = _round_or_none(params["base_position_cash_required"], 2)
    result.basic_required_cash = _round_or_none(params["basic_required_cash"], 2)
    result.reserve_cash = _round_or_none(params["reserve_cash"], 2)
    result.suggest_total_cash = _round_or_none(params["suggest_total_cash"], 2)

    result.t_grid_score = round(score, 2)
    result.score_parts = score_parts
    result.t_grid_level = _level(score)
    result.is_t_grid_candidate = score >= 70 and not reject_reason
    result.can_open_t_grid = lifecycle["can_open_t_grid"]
    result.should_pause_buy = lifecycle["should_pause_buy"]
    result.should_pause_sell = lifecycle["should_pause_sell"]
    result.should_close_t_grid = lifecycle["should_close_t_grid"]
    result.t_grid_action = lifecycle["t_grid_action"]

    result.trigger_probability = backtest.trigger_probability
    result.hit_rate = backtest.hit_rate
    result.avg_close_days = backtest.avg_close_days
    result.avg_triggered_grids_per_day = backtest.avg_triggered_grids_per_day
    result.avg_closed_grids_per_day = backtest.avg_closed_grids_per_day
    result.one_grid_profit = _round_or_none(params["one_grid_cash"] * params["grid_step_pct"] / 100, 2)
    result.expected_daily_profit = _round_or_none((backtest.avg_closed_grids_per_day or 0) * (result.one_grid_profit or 0), 2)
    result.expected_annual_profit = _round_or_none((result.expected_daily_profit or 0) * cfg.annual_trade_days, 2)
    result.expected_annual_return_pct = backtest.expected_annual_return_pct
    result.conservative_annual_return_pct = backtest.expected_annual_return_pct
    result.risk_adjusted_annual_return_pct = backtest.risk_adjusted_annual_return_pct
    result.backtest = asdict(backtest)

    result.reason = _positive_reasons(latest, result, params)
    result.risk = list(dict.fromkeys(risk + _risk_tags(latest, params, cfg)))
    result.reject_reason = list(dict.fromkeys(reject_reason))
    if not result.reject_reason and not result.risk:
        result.risk.append("T网格收益为历史估算，不代表未来收益")
    return result


def calc_t_grid_indicators(df: pd.DataFrame, cfg: TGridConfig | None = None) -> pd.DataFrame:
    cfg = cfg or TGridConfig()
    missing = {"open", "high", "low", "close", "volume", "amount"} - set(df.columns)
    if missing:
        raise ValueError(f"T网格K线缺少字段: {', '.join(sorted(missing))}")
    out = df.copy()
    for column in ("open", "high", "low", "close", "volume", "amount"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["open", "high", "low", "close", "volume", "amount"]).reset_index(drop=True)
    close = out["close"].astype(float)
    high = out["high"].astype(float)
    low = out["low"].astype(float)
    amount = out["amount"].astype(float)

    out["daily_amplitude_pct"] = (high - low) / close.replace(0, pd.NA) * 100
    for window in (10, 20, 60):
        out[f"avg_amplitude_{window}"] = out["daily_amplitude_pct"].rolling(window).mean()
    out["avg_amount_20"] = amount.rolling(20).mean()

    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    out["atr14"] = tr.rolling(cfg.atr_window).mean()
    out["atr_pct"] = out["atr14"] / close.replace(0, pd.NA) * 100

    mid = close.rolling(cfg.boll_window).mean()
    std = close.rolling(cfg.boll_window).std()
    out["boll_mid"] = mid
    out["boll_upper"] = mid + cfg.boll_std * std
    out["boll_lower"] = mid - cfg.boll_std * std
    boll_width = out["boll_upper"] - out["boll_lower"]
    out["boll_width_pct"] = boll_width / mid.replace(0, pd.NA) * 100
    out["boll_position"] = (close - out["boll_lower"]) / boll_width.replace(0, pd.NA)

    out["ma20"] = close.rolling(20).mean()
    out["ma60"] = close.rolling(60).mean()
    out["ma20_slope_pct"] = (out["ma20"] / out["ma20"].shift(5) - 1) * 100
    out["ma60_slope_pct"] = (out["ma60"] / out["ma60"].shift(10) - 1) * 100

    out["range_high_20"] = high.rolling(20).max()
    out["range_low_20"] = low.rolling(20).min()
    out["range_high_60"] = high.rolling(60).max()
    out["range_low_60"] = low.rolling(60).min()
    range_width = out["range_high_20"] - out["range_low_20"]
    out["range_position"] = (close - out["range_low_20"]) / range_width.replace(0, pd.NA)
    out["range_width_pct"] = range_width / close.replace(0, pd.NA) * 100
    out["adx14"] = _adx(high, low, close, cfg.adx_window)
    return out


def calc_t_grid_score(latest_row: pd.Series, grid_step_pct: float, cfg: TGridConfig | None = None) -> tuple[float, dict[str, float]]:
    cfg = cfg or TGridConfig()
    avg_amount = _num(latest_row.get("avg_amount_20"))
    avg_amplitude = _num(latest_row.get("avg_amplitude_20"))
    ma20_slope = _num(latest_row.get("ma20_slope_pct"))
    boll_position = _num(latest_row.get("boll_position"))
    range_position = _num(latest_row.get("range_position"))
    adx14 = _maybe_num(latest_row.get("adx14"))

    liquidity = 20 if avg_amount >= 200_000_000 else 16 if avg_amount >= 100_000_000 else 12 if avg_amount >= 50_000_000 else 8 if avg_amount >= cfg.min_avg_amount_20 else 0
    ratio = avg_amplitude / grid_step_pct if grid_step_pct > 0 else 0
    volatility = 25 if ratio >= 2.5 else 22 if ratio >= 2.0 else 16 if ratio >= 1.5 else 10 if ratio >= 1.2 else 0
    abs_slope = abs(ma20_slope)
    ma_score = 10 if abs_slope <= 1 else 8 if abs_slope <= 2 else 5 if abs_slope <= 3 else 0
    boll_score = 8 if 0.25 <= boll_position <= 0.75 else 5 if 0.15 <= boll_position < 0.25 or 0.75 < boll_position <= 0.85 else 0
    range_score = 7 if 0.25 <= range_position <= 0.75 else 4 if 0.15 <= range_position < 0.25 or 0.75 < range_position <= 0.85 else 0
    structure = ma_score + boll_score + range_score
    if adx14 is None:
        trend_risk = _fallback_trend_risk_score(latest_row)
    else:
        trend_risk = 20 if adx14 < 15 else 16 if adx14 < 20 else 10 if adx14 < 25 else 0
    price = 10 if 0.35 <= range_position <= 0.65 else 8 if 0.2 <= range_position < 0.35 else 6 if 0.65 < range_position <= 0.8 else 4 if 0.1 <= range_position < 0.2 else 3 if 0.8 < range_position <= 0.9 else 0
    parts = {
        "liquidity": float(liquidity),
        "volatility": float(volatility),
        "swing_structure": float(structure),
        "trend_risk": float(trend_risk),
        "price_position": float(price),
    }
    return sum(parts.values()), parts


def advise_t_grid_params(
    latest_row: pd.Series,
    user_grid_step_pct: float | None = None,
    grid_qty: int = 1000,
    reserve_ratio: float = 0.2,
    cfg: TGridConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or TGridConfig(grid_qty=grid_qty, reserve_ratio=reserve_ratio)
    close = _num(latest_row.get("close"))
    avg_amplitude = _num(latest_row.get("avg_amplitude_20"))
    atr_pct = _num(latest_row.get("atr_pct"))
    suggested = max(avg_amplitude / 2 if avg_amplitude else 0, atr_pct * 0.8 if atr_pct else 0)
    if suggested <= 0:
        suggested = cfg.min_grid_step_pct
    grid_step_pct = user_grid_step_pct or min(max(suggested, cfg.min_grid_step_pct), cfg.max_grid_step_pct)
    grid_upper = _num(latest_row.get("range_high_20")) * 0.995
    grid_lower = _num(latest_row.get("range_low_20")) * 1.005
    step_ratio = grid_step_pct / 100
    grid_count_up = int(max(0, (grid_upper / close - 1) / step_ratio)) if close > 0 and step_ratio > 0 else 0
    grid_count_down = int(max(0, (1 - grid_lower / close) / step_ratio)) if close > 0 and step_ratio > 0 else 0
    normalized_qty = _round_lot_down(grid_qty)
    one_grid_cash = close * normalized_qty
    buy_cash_required = grid_count_down * one_grid_cash
    base_position_cash_required = grid_count_up * one_grid_cash
    basic_required_cash = buy_cash_required + base_position_cash_required
    reserve_cash = basic_required_cash * reserve_ratio
    return {
        "grid_step_pct": round(grid_step_pct, 2),
        "grid_upper": grid_upper,
        "grid_lower": grid_lower,
        "grid_count_up": grid_count_up,
        "grid_count_down": grid_count_down,
        "grid_qty": normalized_qty,
        "one_grid_cash": one_grid_cash,
        "buy_cash_required": buy_cash_required,
        "base_position_cash_required": base_position_cash_required,
        "basic_required_cash": basic_required_cash,
        "reserve_cash": reserve_cash,
        "suggest_total_cash": basic_required_cash + reserve_cash,
    }


def decide_t_grid_lifecycle(
    latest_row: pd.Series,
    t_grid_score: float,
    grid_step_pct: float,
    grid_count_up: int,
    grid_count_down: int,
    reject_reason: list[str] | None = None,
    cfg: TGridConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or TGridConfig()
    close = _num(latest_row.get("close"))
    range_low_20 = _num(latest_row.get("range_low_20"))
    range_high_20 = _num(latest_row.get("range_high_20"))
    range_low_60 = _num(latest_row.get("range_low_60"))
    ma60 = _num(latest_row.get("ma60"))
    boll_lower = _num(latest_row.get("boll_lower"))
    boll_upper = _num(latest_row.get("boll_upper"))
    ma20_slope = _num(latest_row.get("ma20_slope_pct"))
    adx14 = _maybe_num(latest_row.get("adx14"))
    avg_amount = _num(latest_row.get("avg_amount_20"))
    avg_amplitude = _num(latest_row.get("avg_amplitude_20"))
    boll_width = _num(latest_row.get("boll_width_pct"))
    range_position = _num(latest_row.get("range_position"))

    should_pause_buy = (
        (range_low_20 > 0 and close < range_low_20 * 0.98)
        or (ma60 > 0 and close < ma60 * 0.97)
        or (boll_lower > 0 and close < boll_lower * 0.98)
        or (adx14 is not None and adx14 >= cfg.max_adx and ma20_slope < -3)
    )
    should_pause_sell = (
        (range_high_20 > 0 and close > range_high_20 * 1.02)
        or (boll_upper > 0 and close > boll_upper * 1.02)
        or (adx14 is not None and adx14 >= cfg.max_adx and ma20_slope > 3)
    )
    should_close = (
        (range_low_60 > 0 and close < range_low_60 * 0.95)
        or (ma60 > 0 and close < ma60 * 0.93)
        or t_grid_score < 50
        or avg_amount < 20_000_000
        or boll_width > 35
    )
    can_open = (
        t_grid_score >= 70
        and not reject_reason
        and avg_amount >= cfg.min_avg_amount_20
        and avg_amplitude >= grid_step_pct * cfg.volatility_ratio_min
        and (adx14 is None or adx14 < cfg.max_adx)
        and abs(ma20_slope) <= cfg.max_abs_ma20_slope_pct
        and 0.15 <= range_position <= 0.85
        and grid_count_up >= 2
        and grid_count_down >= 2
    )
    if should_close:
        action = "关闭T网格"
    elif should_pause_buy and should_pause_sell:
        action = "暂停全部T网格"
    elif should_pause_buy:
        action = "暂停T网格买入"
    elif should_pause_sell:
        action = "暂停T网格卖出"
    elif can_open:
        action = "开启T网格"
    elif t_grid_score >= 60:
        action = "观察，不开启T网格"
    else:
        action = "关闭T网格"
    return {
        "can_open_t_grid": can_open,
        "should_pause_buy": should_pause_buy,
        "should_pause_sell": should_pause_sell,
        "should_close_t_grid": should_close,
        "t_grid_action": action,
    }


def estimate_t_grid_backtest_metrics(
    df: pd.DataFrame,
    grid_step_pct: float,
    grid_qty: int = 1000,
    suggest_total_cash: float | None = None,
    backtest_days: int = 60,
    max_holding_days: int = 5,
    annual_trade_days: int = 250,
    path_mode: str = "conservative",
) -> TGridBacktestResult:
    if len(df) < 3 or grid_step_pct <= 0:
        return TGridBacktestResult(backtest_days=0)
    window = df.tail(backtest_days + max_holding_days + 1).reset_index(drop=True)
    usable_days = max(0, min(backtest_days, len(window) - max_holding_days - 1))
    if usable_days <= 0:
        return TGridBacktestResult(backtest_days=0)

    step = grid_step_pct / 100
    triggered = 0
    closed = 0
    triggered_days = 0
    close_days: list[int] = []
    unclosed_drawdowns: list[float] = []
    latest_close = _num(window.iloc[-1].get("close"))
    one_grid_cash = latest_close * _round_lot_down(grid_qty)
    one_grid_profit = one_grid_cash * step
    max_drawdown = 0.0

    for idx in range(1, usable_days + 1):
        prev_close = _num(window.iloc[idx - 1].get("close"))
        row = window.iloc[idx]
        low = _num(row.get("low"))
        high = _num(row.get("high"))
        if prev_close <= 0:
            continue
        buy_price = prev_close * (1 - step)
        sell_price = prev_close * (1 + step)
        buy_triggered = low <= buy_price
        sell_triggered = high >= sell_price
        if not buy_triggered and not sell_triggered:
            continue
        triggered_days += 1
        directions: list[tuple[str, float]] = []
        if path_mode == "conservative" and buy_triggered and sell_triggered:
            directions = [("buy", buy_price)] if abs(_num(row.get("open")) - buy_price) <= abs(_num(row.get("open")) - sell_price) else [("sell", sell_price)]
        else:
            if buy_triggered:
                directions.append(("buy", buy_price))
            if sell_triggered:
                directions.append(("sell", sell_price))
        for direction, price in directions:
            triggered += 1
            closed_flag = False
            worst_drawdown = 0.0
            for offset in range(1, max_holding_days + 1):
                future = window.iloc[idx + offset]
                future_high = _num(future.get("high"))
                future_low = _num(future.get("low"))
                if direction == "buy":
                    if future_high >= price * (1 + step):
                        closed += 1
                        close_days.append(offset)
                        closed_flag = True
                        break
                    worst_drawdown = max(worst_drawdown, max(0.0, (price - future_low) / price * 100))
                else:
                    if future_low <= price * (1 - step):
                        closed += 1
                        close_days.append(offset)
                        closed_flag = True
                        break
                    worst_drawdown = max(worst_drawdown, max(0.0, (future_high - price) / price * 100))
            if not closed_flag:
                unclosed_drawdowns.append(worst_drawdown)
                max_drawdown = max(max_drawdown, worst_drawdown)

    unclosed = max(0, triggered - closed)
    trigger_probability = triggered_days / usable_days if usable_days else None
    hit_rate = closed / triggered if triggered else None
    avg_close_days = sum(close_days) / len(close_days) if close_days else None
    avg_triggered = triggered / usable_days if usable_days else None
    avg_closed = closed / usable_days if usable_days else None
    gross_profit = closed * one_grid_profit
    floating_loss = sum(one_grid_cash * drawdown / 100 for drawdown in unclosed_drawdowns)
    net_profit = gross_profit - floating_loss
    total_cash = suggest_total_cash or one_grid_cash
    expected_annual = ((avg_closed or 0) * one_grid_profit * annual_trade_days / total_cash * 100) if total_cash > 0 else None
    risk_adjusted = ((net_profit / usable_days * annual_trade_days) / total_cash * 100) if total_cash > 0 and usable_days else None
    return TGridBacktestResult(
        backtest_days=usable_days,
        triggered_grid_count=triggered,
        closed_grid_count=closed,
        unclosed_grid_count=unclosed,
        trigger_probability=_round_or_none(trigger_probability, 4),
        hit_rate=_round_or_none(hit_rate, 4),
        avg_close_days=_round_or_none(avg_close_days, 2),
        avg_triggered_grids_per_day=_round_or_none(avg_triggered, 4),
        avg_closed_grids_per_day=_round_or_none(avg_closed, 4),
        gross_profit=round(gross_profit, 2),
        floating_pnl=round(-floating_loss, 2),
        net_profit=round(net_profit, 2),
        max_drawdown_pct=round(max_drawdown, 2),
        expected_annual_return_pct=_round_or_none(expected_annual, 2),
        risk_adjusted_annual_return_pct=_round_or_none(risk_adjusted, 2),
    )


def results_to_dicts(results: list[TGridResult]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in results]


def _hard_filters(latest: pd.Series, params: dict[str, Any], cfg: TGridConfig) -> tuple[list[str], list[str]]:
    reject: list[str] = []
    risk: list[str] = []
    close = _num(latest.get("close"))
    avg_amount = _num(latest.get("avg_amount_20"))
    avg_amplitude = _num(latest.get("avg_amplitude_20"))
    grid_step = _num(params.get("grid_step_pct"))
    adx14 = _maybe_num(latest.get("adx14"))
    ma20_slope = _num(latest.get("ma20_slope_pct"))
    ma20 = _num(latest.get("ma20"))
    ma60 = _num(latest.get("ma60"))
    range_low_20 = _num(latest.get("range_low_20"))
    boll_lower = _num(latest.get("boll_lower"))
    boll_width = _num(latest.get("boll_width_pct"))
    if avg_amount < cfg.min_avg_amount_20:
        reject.append("20日平均成交额低于3000万，T网格成交质量不稳定")
    if avg_amplitude < grid_step * cfg.volatility_ratio_min:
        reject.append("20日日均振幅不足，无法覆盖建议网格间距")
    if adx14 is not None and adx14 >= cfg.max_adx:
        reject.append("ADX较高，趋势性较强，不适合普通T网格")
    if abs(ma20_slope) > cfg.max_abs_ma20_slope_pct:
        reject.append("MA20斜率过大，震荡结构不稳定")
    if ma20 > 0 and close > ma20 * 1.12:
        reject.append("价格显著高于MA20，单边上涨卖飞风险高")
    if ma20 > 0 and close < ma20 * 0.88:
        reject.append("价格显著低于MA20，单边下跌接飞刀风险高")
    if range_low_20 > 0 and close < range_low_20 * 0.98:
        reject.append("价格跌破20日箱体下沿，存在破位风险")
    if ma60 > 0 and close < ma60 * 0.97:
        reject.append("价格明显跌破MA60，不适合新开T网格")
    if boll_lower > 0 and close < boll_lower * 0.98:
        reject.append("价格跌破BOLL下轨，震荡结构失效")
    if boll_width > cfg.max_boll_width_pct:
        reject.append("BOLL带宽过大，当前不是稳定震荡结构")
    if params["grid_count_up"] < 2:
        reject.append("向上可卖空间不足2格，当前价格过于接近箱体上沿")
    if params["grid_count_down"] < 2:
        reject.append("向下可买空间不足2格，当前价格过于接近箱体下沿")
    if avg_amount < cfg.preferred_avg_amount_20:
        risk.append("成交额低于优选阈值5000万，可能存在滑点和成交不稳定")
    return reject, risk


def _risk_tags(latest: pd.Series, params: dict[str, Any], cfg: TGridConfig) -> list[str]:
    risks: list[str] = ["T网格收益为历史估算，不代表未来收益"]
    adx14 = _maybe_num(latest.get("adx14"))
    range_position = _num(latest.get("range_position"))
    avg_amount = _num(latest.get("avg_amount_20"))
    avg_amplitude = _num(latest.get("avg_amplitude_20"))
    boll_width = _num(latest.get("boll_width_pct"))
    grid_step = _num(params.get("grid_step_pct"))
    if adx14 is not None and adx14 >= cfg.max_adx:
        risks.append("ADX较高，趋势性较强，T网格可能卖飞或接飞刀")
    if range_position > 0.85:
        risks.append("价格接近20日箱体上沿，追高开启T网格风险较高")
    if range_position < 0.15:
        risks.append("价格接近20日箱体下沿，存在破位风险")
    if avg_amplitude < grid_step * cfg.volatility_ratio_min:
        risks.append("平均日内振幅不足，T网格空间可能不够")
    if avg_amount < cfg.preferred_avg_amount_20:
        risks.append("成交额偏低，可能存在滑点和成交不稳定")
    if boll_width > cfg.max_boll_width_pct:
        risks.append("BOLL带宽过大，可能不是稳定震荡")
    risks.append("当前未采集可卖份额和可用现金，执行前需人工核对底仓与资金")
    return risks


def _positive_reasons(latest: pd.Series, result: TGridResult, params: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if result.is_t_grid_candidate:
        reasons.append("成交额、振幅、趋势强度和箱体位置满足T网格候选条件")
    if result.avg_amplitude_20 is not None and result.suggest_grid_step_pct is not None:
        reasons.append(f"20日日均振幅约{result.avg_amplitude_20:.2f}%，建议T网格间距约{result.suggest_grid_step_pct:.2f}%")
    if 0.2 <= _num(latest.get("range_position")) <= 0.8:
        reasons.append("当前价格位于20日箱体中部区域，上下均有操作空间")
    if params["grid_count_up"] >= 2 and params["grid_count_down"] >= 2:
        reasons.append(f"向上约{params['grid_count_up']}格、向下约{params['grid_count_down']}格，具备基础双向空间")
    return list(dict.fromkeys(reasons))


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(window).sum()
    plus_di = 100 * plus_dm.rolling(window).sum() / atr.replace(0, pd.NA)
    minus_di = 100 * minus_dm.rolling(window).sum() / atr.replace(0, pd.NA)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)
    return dx.rolling(window).mean()


def _fallback_trend_risk_score(latest: pd.Series) -> float:
    score = 20
    close = _num(latest.get("close"))
    ma20 = _num(latest.get("ma20"))
    if abs(_num(latest.get("ma20_slope_pct"))) > 2:
        score -= 5
    if ma20 > 0 and close > ma20 * 1.08:
        score -= 5
    if ma20 > 0 and close < ma20 * 0.92:
        score -= 5
    if _num(latest.get("boll_width_pct")) > 25:
        score -= 5
    return float(max(0, score))


def _level(score: float) -> str:
    if score >= 80:
        return "高度适合T网格"
    if score >= 70:
        return "适合T网格"
    if score >= 60:
        return "可观察"
    if score >= 50:
        return "谨慎观察"
    return "不适合T网格"


def _result_sort_key(item: TGridResult) -> tuple[int, float, float, float, float, float]:
    return (
        1 if item.is_t_grid_candidate else 0,
        item.t_grid_score or 0,
        item.risk_adjusted_annual_return_pct or 0,
        item.hit_rate or 0,
        item.avg_amount_20 or 0,
        item.avg_amplitude_20 or 0,
    )


def _round_lot_down(value: float | int) -> int:
    return max(100, int(value) // 100 * 100)


def _num(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if pd.isna(number):
        return 0.0
    return number


def _maybe_num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number):
        return None
    return number


def _round_or_none(value: Any, digits: int) -> float | None:
    number = _maybe_num(value)
    return None if number is None else round(number, digits)
