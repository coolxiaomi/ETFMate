"""ETF path prices use a 0.001 CNY tick without early confirmation."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

PRICE_TICK = Decimal("0.001")
CONFIRMATION_PRICE_BASIS = "EXTREME_EQUALS_TRIGGER"


def grid_trigger_price(base: float, pct: float, side: str) -> float:
    direction = Decimal("-1") if side == "buy" else Decimal("1")
    value = Decimal(str(base)) * (Decimal("1") + direction * Decimal(str(pct)) / 100)
    return float(value.quantize(PRICE_TICK, rounding=ROUND_FLOOR if side == "buy" else ROUND_CEILING))


def confirmation_price(trigger_price: float, pct: float, side: str) -> tuple[Decimal, Decimal]:
    """Return the exact boundary and first satisfying tick, assuming extreme=trigger.

    Buy rebound rounds up; sell pullback rounds down. These are path examples,
    not a second activation price or an estimate of the eventual execution price.
    """
    if side not in {"buy", "sell"}:
        raise ValueError("confirmation side must be buy or sell")
    extreme, rate = Decimal(str(trigger_price)), Decimal(str(pct))
    if not extreme.is_finite() or extreme <= 0 or not rate.is_finite() or rate <= 0:
        raise ValueError("confirmation price and percentage must be finite and positive")
    if side == "sell" and rate >= 100:
        raise ValueError("sell pullback percentage must be below 100")
    direction = Decimal("1") if side == "buy" else Decimal("-1")
    theoretical = extreme * (Decimal("1") + direction * rate / 100)
    tick_price = theoretical.quantize(PRICE_TICK, rounding=ROUND_CEILING if side == "buy" else ROUND_FLOOR)
    return theoretical, tick_price
