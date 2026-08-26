"""
Tick Data - Market tick data structure
"""
from datetime import datetime
from typing import Optional
from dataclasses import dataclass


@dataclass
class TickData:
    """
    Tick data object for market price updates

    Compatible with both crypto (CCXT) and traditional markets (CTP, XTP, etc.)
    """
    # Basic information
    gateway_name: str = ""
    symbol: str = ""
    exchange: str = ""
    datetime: Optional[datetime] = None

    # Names
    name: str = ""
    product_class: Optional[str] = None  # spot, futures, options, etc.

    # Price data
    last_price: float = 0.0
    last_volume: float = 0.0
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    pre_close: float = 0.0

    # Bid/Ask (Level 1)
    bid_price_1: float = 0.0
    bid_volume_1: float = 0.0
    ask_price_1: float = 0.0
    ask_volume_1: float = 0.0

    # Volume data
    volume: float = 0.0          # Total volume
    turnover: float = 0.0        # Total turnover
    open_interest: float = 0.0    # Open interest (futures)
    pre_open_interest: float = 0.0  # Previous open interest (futures)

    # Additional info
    leverage: int = 1            # Leverage for crypto futures

    def __repr__(self):
        return f"TickData({self.symbol}, {self.last_price}, {self.datetime})"
