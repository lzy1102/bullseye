"""
OrderBook Data - Order book snapshot data structure
"""
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class OrderBookData:
    """
    Order book snapshot data object.

    Contains bid/ask price levels with volumes, providing
    market depth information for trading strategies.
    """
    # Basic information
    gateway_name: str = ""
    symbol: str = ""
    exchange: str = ""
    datetime: Optional[datetime] = None

    # Order book levels: [[price, volume], ...]
    bids: List[List[float]] = field(default_factory=list)  # Buy side (descending by price)
    asks: List[List[float]] = field(default_factory=list)  # Sell side (ascending by price)

    def __repr__(self):
        return f"OrderBookData({self.symbol}, bids={len(self.bids)}, asks={len(self.asks)}, {self.datetime})"

    @property
    def best_bid_price(self) -> float:
        """Best (highest) bid price."""
        return self.bids[0][0] if self.bids else 0.0

    @property
    def best_ask_price(self) -> float:
        """Best (lowest) ask price."""
        return self.asks[0][0] if self.asks else 0.0

    @property
    def spread(self) -> float:
        """Best ask minus best bid."""
        return self.best_ask_price - self.best_bid_price

    @property
    def mid_price(self) -> float:
        """Midpoint between best bid and best ask."""
        if not self.bids or not self.asks:
            return 0.0
        return (self.best_bid_price + self.best_ask_price) / 2.0

    @property
    def bid_volume_total(self) -> float:
        """Total volume across all bid levels."""
        return sum(level[1] for level in self.bids)

    @property
    def ask_volume_total(self) -> float:
        """Total volume across all ask levels."""
        return sum(level[1] for level in self.asks)

    @property
    def imbalance(self) -> float:
        """
        Order book imbalance in range [-1, 1].

        Positive = bid-heavy (buying pressure).
        Negative = ask-heavy (selling pressure).
        """
        total = self.bid_volume_total + self.ask_volume_total
        if total == 0:
            return 0.0
        return (self.bid_volume_total - self.ask_volume_total) / total
