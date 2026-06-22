from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Position:
    code: str
    name: str
    quantity: float
    available_quantity: float | None
    cost_price: float
    last_price: float
    market_value: float
    pnl: float
    pnl_pct: float
    position_pct: float | None = None
    note: str | None = None
    source: str = "ths"


@dataclass
class Trade:
    trade_date: str
    trade_time: str | None
    code: str
    name: str
    side: str
    price: float
    quantity: float
    amount: float
    fee: float | None
    source: str = "ths"


@dataclass
class GridConfig:
    code: str
    name: str
    enabled: bool
    status: str | None = None
    base_price: float | None = None
    last_price: float | None = None
    distance_from_base_pct: float | None = None
    lower_price: float | None = None
    upper_price: float | None = None
    grid_step_pct: float | None = None
    grid_step_amount: float | None = None
    order_amount: float | None = None
    order_quantity: float | None = None
    buy_quantity: float | None = None
    sell_quantity: float | None = None
    sell_rise_pct: float | None = None
    sell_pullback_pct: float | None = None
    buy_fall_pct: float | None = None
    buy_rebound_pct: float | None = None
    min_base_quantity: float | None = None
    max_position_quantity: float | None = None
    last_trigger_time: str | None = None


@dataclass
class MarketSnapshot:
    code: str
    name: str
    last_price: float
    pct_chg: float
    volume: float
    amount: float
    amplitude_pct: float | None = None
    turnover_pct: float | None = None
    vol_ratio: float | None = None
    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    ma120: float | None = None
    ma200: float | None = None
    boll_upper: float | None = None
    boll_mid: float | None = None
    boll_lower: float | None = None
    atr7: float | None = None
    atr7_pct: float | None = None
    atr14: float | None = None
    atr14_pct: float | None = None
    atr30: float | None = None
    atr30_pct: float | None = None
    atr60: float | None = None
    atr60_pct: float | None = None
    bias6: float | None = None
    bias12: float | None = None
    bias24: float | None = None
    vol_ma5: float | None = None
    vol_ma20: float | None = None
    amount_avg20: float | None = None
    amount_ratio20: float | None = None
    rsi14: float | None = None
    ret3: float | None = None
    ret5: float | None = None
    ret20: float | None = None
    ret60: float | None = None
    max_drawdown_60: float | None = None
    ma20_slope_pct: float | None = None
    kline_days: int | None = None
    data_quality: str = "ok"


def to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value
