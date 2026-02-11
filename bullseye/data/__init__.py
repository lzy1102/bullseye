"""
Data Module - Market data adapters and data providers

This module provides:
- Market adapters for different markets (crypto, stock, futures)
- DataProvider compatible with Freqtrade
"""

from .market_adapter import (
    MarketAdapterFactory,
    MarketType,
    BaseMarketAdapter,
    CryptoMarketAdapter,
    StockMarketAdapter,
    FutureMarketAdapter,
)

__all__ = [
    "MarketAdapterFactory",
    "MarketType",
    "BaseMarketAdapter",
    "CryptoMarketAdapter",
    "StockMarketAdapter",
    "FutureMarketAdapter",
]
