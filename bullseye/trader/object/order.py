"""
Order Data - Order information structure
"""
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from enum import Enum


class OrderType(Enum):
    """Order type enumeration"""
    LIMIT = "limit"
    MARKET = "market"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"


class Direction(Enum):
    """Order direction enumeration"""
    LONG = "long"      # Buy
    SHORT = "short"    # Sell


class Offset(Enum):
    """Order offset enumeration (for futures)"""
    OPEN = "open"
    CLOSE = "close"
    CLOSETODAY = "closetoday"
    CLOSEYESTERDAY = "closeyesterday"


class Status(Enum):
    """Order status enumeration"""
    NOTTRADED = "nottraded"
    PARTTRADED = "parttraded"
    ALLTRADED = "alltraded"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class OrderData:
    """
    Order data object

    Compatible with Freqtrade Order format
    """
    # Basic information
    gateway_name: str = ""
    orderid: str = ""
    symbol: str = ""
    exchange: str = ""

    # Order specifications
    type: OrderType = OrderType.LIMIT
    direction: Optional[Direction] = None
    offset: Optional[Offset] = None
    price: float = 0.0
    volume: float = 0.0
    traded: float = 0.0
    status: Status = Status.NOTTRADED

    # Time information
    datetime: Optional[datetime] = None
    reference: str = ""  # Strategy reference

    # Additional info
    time_in_force: str = "GTC"  # Good Till Cancelled
    remark: str = ""

    def __repr__(self):
        return f"OrderData({self.orderid}, {self.symbol}, {self.status.value})"

    @property
    def is_active(self) -> bool:
        """Check if order is still active"""
        return self.status in [Status.NOTTRADED, Status.PARTTRADED]

    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled"""
        return self.status == Status.ALLTRADED

    @property
    def is_cancelled(self) -> bool:
        """Check if order is cancelled"""
        return self.status == Status.CANCELLED

    @property
    def remaining(self) -> float:
        """Get remaining volume to trade"""
        return self.volume - self.traded
