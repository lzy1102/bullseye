"""
Position Data - Position holding information structure
"""
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from .order import Direction


@dataclass
class PositionData:
    """
    Position data object

    Compatible with Freqtrade position format
    """
    # Basic information
    gateway_name: str = ""
    symbol: str = ""
    exchange: str = ""

    # Position specifications
    direction: Optional[Direction] = None
    volume: float = 0.0          # Position volume
    yd_volume: float = 0.0       # Yesterday's volume (for futures)
    price: float = 0.0           # Average open price
    pnl: float = 0.0             # Unrealized PnL
    available: float = 0.0       # Available volume to close

    # Additional info
    leverage: int = 1            # Leverage for crypto futures
    datetime: Optional[datetime] = None

    def __repr__(self):
        direction_str = self.direction.value if self.direction else ""
        return f"PositionData({self.symbol}, {direction_str}, {self.volume})"

    @property
    def market_value(self) -> float:
        """Get market value of position"""
        return self.volume * self.price

    @property
    def is_long(self) -> bool:
        """Check if position is long"""
        return self.direction == Direction.LONG

    @property
    def is_short(self) -> bool:
        """Check if position is short"""
        return self.direction == Direction.SHORT
