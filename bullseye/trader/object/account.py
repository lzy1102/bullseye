"""
Account Data - Account information structure
"""
from datetime import datetime
from typing import Optional
from dataclasses import dataclass


@dataclass
class AccountData:
    """
    Account data object

    Compatible with Freqtrade wallet format
    """
    # Basic information
    gateway_name: str = ""
    accountid: str = ""

    # Balance information
    balance: float = 0.0        # Total balance
    available: float = 0.0      # Available balance
    frozen: float = 0.0         # Frozen balance (for open orders)
    margin: float = 0.0         # Margin used (for futures)

    # Currency information
    currency: str = "USDT"

    # Additional info
    datetime: Optional[datetime] = None
    risk_ratio: float = 0.0     # Risk ratio (for futures)

    def __repr__(self):
        return f"AccountData({self.accountid}, {self.balance}, {self.currency})"

    @property
    def margin_available(self) -> float:
        """Get available margin for trading"""
        return self.available - self.margin

    @property
    def pnl(self) -> float:
        """Get unrealized PnL"""
        return self.balance - (self.available + self.frozen)
