"""
Trade Data - Trade execution information structure
"""
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from .order import Direction, Offset


@dataclass
class TradeData:
    """
    Trade data object

    Represents a filled trade (execution)
    """
    # Basic information
    gateway_name: str = ""
    tradeid: str = ""
    orderid: str = ""
    symbol: str = ""
    exchange: str = ""

    # Trade specifications
    direction: Optional[Direction] = None
    offset: Optional[Offset] = None
    price: float = 0.0
    volume: float = 0.0
    datetime: Optional[datetime] = None

    # Fee information
    commission: float = 0.0

    # Additional info
    remark: str = ""

    def __repr__(self):
        return f"TradeData({self.tradeid}, {self.symbol}, {self.price}, {self.volume})"

    @property
    def value(self) -> float:
        """Get trade value (price * volume)"""
        return self.price * self.volume
