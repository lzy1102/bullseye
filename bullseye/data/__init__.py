"""
Data Module - Market data adapters and data providers

This module provides:
- Market adapters for different markets (crypto, stock, futures)
- DataProvider compatible with Freqtrade
- Datafeed sources (AKShare, TuShare, etc.)
"""

from .market_adapter import (
    MarketAdapterFactory,
    MarketType,
    BaseMarketAdapter,
    CryptoMarketAdapter,
    StockMarketAdapter,
    FutureMarketAdapter,
)
from .dataprovider import DataProvider
from .datafeed import (
    BaseDatafeed,
    DatafeedConfig,
    AKShareDatafeed,
    TuShareDatafeed,
    get_datafeed,
)

__all__ = [
    "MarketAdapterFactory",
    "MarketType",
    "BaseMarketAdapter",
    "CryptoMarketAdapter",
    "StockMarketAdapter",
    "FutureMarketAdapter",
    "DataProvider",
    "BaseDatafeed",
    "DatafeedConfig",
    "AKShareDatafeed",
    "TuShareDatafeed",
    "get_datafeed",
]
