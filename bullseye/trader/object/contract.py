"""
Contract Data - Contract/Instrument information structure
"""
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from enum import Enum


class ProductClass(Enum):
    """Product class enumeration"""
    SPOT = "spot"
    MARGIN = "margin"
    SWAP = "swap"           # Perpetual futures
    FUTURES = "futures"
    OPTIONS = "options"
    EQUITY = "equity"       # Stock
    INDEX = "index"
    FOREX = "forex"


class OptionType(Enum):
    """Option type enumeration"""
    CALL = "call"
    PUT = "put"


@dataclass
class ContractData:
    """
    Contract data object

    Contains trading instrument information
    """
    # Basic information
    gateway_name: str = ""
    symbol: str = ""
    exchange: str = ""
    name: str = ""

    # Product information
    product_class: Optional[ProductClass] = None
    size: float = 1.0            # Contract multiplier
    pricetick: float = 0.0       # Minimum price tick

    # Volume limits
    min_volume: float = 1.0
    max_volume: float = 0.0

    # Option specific
    option_type: Optional[OptionType] = None
    underlying_symbol: str = ""
    strike_price: float = 0.0
    expiry_date: Optional[datetime] = None

    # Additional info
    leverage: int = 1            # Leverage for crypto futures
    list_date: Optional[datetime] = None

    def __repr__(self):
        return f"ContractData({self.symbol}, {self.name})"

    @property
    def is_spot(self) -> bool:
        """Check if contract is spot"""
        return self.product_class == ProductClass.SPOT

    @property
    def is_futures(self) -> bool:
        """Check if contract is futures"""
        return self.product_class == ProductClass.FUTURES

    @property
    def is_perpetual(self) -> bool:
        """Check if contract is perpetual swap"""
        return self.product_class == ProductClass.SWAP

    @property
    def is_option(self) -> bool:
        """Check if contract is option"""
        return self.product_class == ProductClass.OPTIONS

    @property
    def is_stock(self) -> bool:
        """Check if contract is stock"""
        return self.product_class == ProductClass.EQUITY
