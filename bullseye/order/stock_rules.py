"""
Stock Rules - Shared A-share microstructure helpers.

Single source of truth used by BOTH the backtest engine and the live
order path, so paper and live behave identically on:
- market-type detection from pair format,
- 100-share lot rounding,
- daily price-limit (涨跌停) locked-fill checks,
- minimal fill notices for the order_filled() callback.
"""
import logging
import math
import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: Standard A-share board lot.
LOT_SIZE = 100


def detect_market_type(pair: str) -> str:
    """Infer market type from pair format: 'stock', 'future' or 'crypto'."""
    upper = (pair or "").upper()
    if re.match(r"^\d{6}\.(SZ|SH|BJ)$", upper) or re.match(r"^[036]\d{5}$", upper):
        return "stock"
    if re.match(r"^[A-Z]+\d+@[A-Z]+$", upper) or re.match(r"^\d+@[A-Z]+$", upper):
        return "future"
    return "crypto"


def price_limit_ratio(pair: str) -> float:
    """Daily price-limit ratio for an A-share code.

    Main board 10%; ChiNext (30xxxx) / STAR (688xxx) 20%; Beijing Stock
    Exchange (.BJ) 30%. ST/*ST (5%) cannot be identified from the code
    alone — override per pair.
    """
    upper = (pair or "").upper()
    m = re.match(r"^(\d{6})(\.(SZ|SH|BJ))?$", upper)
    if m:
        code, exchange = m.group(1), (m.group(3) or "").upper()
        if exchange == "BJ":
            return 0.30
        if code.startswith("30") or code.startswith("688"):
            return 0.20
    return 0.10


def limit_ratio_for(config: Any, pair: str) -> float:
    """Limit ratio honoring backtest.price_limit_overrides."""
    try:
        overrides = config.get("backtest.price_limit_overrides", {}) or {}
        if pair in overrides:
            return float(overrides[pair])
        upper = (pair or "").upper()
        for key, value in overrides.items():
            if str(key).upper() == upper:
                return float(value)
    except Exception:
        pass
    return price_limit_ratio(pair)


def locked_at_limit_up(current_rate: float, prev_close: float, ratio: float) -> bool:
    """True when a buy fill at current_rate is unobtainable (limit-up)."""
    if not prev_close or prev_close <= 0 or current_rate <= 0:
        return False
    return current_rate >= prev_close * (1 + ratio) * 0.999


def locked_at_limit_down(current_rate: float, prev_close: float, ratio: float) -> bool:
    """True when a sell fill at current_rate is unobtainable (limit-down)."""
    if not prev_close or prev_close <= 0 or current_rate <= 0:
        return False
    return current_rate <= prev_close * (1 - ratio) * 1.001


def floor_to_lots(amount: float, lot_size: int = LOT_SIZE) -> float:
    """Round a share amount down to whole lots."""
    if amount <= 0:
        return 0.0
    return math.floor(amount / lot_size) * lot_size


def make_fill_order(
    pair: str,
    side: str,
    price: float,
    amount: float,
    current_date: Optional[datetime] = None,
    order_type: str = "market",
) -> SimpleNamespace:
    """Minimal Freqtrade-compatible fill notice for order_filled().

    Backtest and dry-run fills are immediate; live gateway fills are booked
    from actual fill price/quantity by the caller. Documented subset —
    strategies needing full Order books should run live.
    """
    import uuid

    cost = (price or 0.0) * (amount or 0.0)
    return SimpleNamespace(
        order_id=str(uuid.uuid4())[:8],
        pair=pair,
        side=side,
        ft_order_side=side,
        order_type=order_type,
        status="closed",
        ft_is_open=False,
        price=price,
        average=price,
        amount=amount,
        filled=amount,
        remaining=0.0,
        cost=cost,
        order_date=current_date,
        order_filled_date=current_date,
    )


def describe_rules() -> Dict[str, Any]:
    """Human-readable summary of enforced rules (for logs/docs)."""
    return {
        "lot_size": LOT_SIZE,
        "price_limits": "10% main board / 20% ChiNext-STAR, per-pair override",
        "t_plus_1": "A-share sells blocked before settlement date",
    }
