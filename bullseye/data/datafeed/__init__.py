"""
Datafeed Module - Market data sources for backtesting and analysis

Provides unified interface for different data sources:
- AKShare (free Chinese stock market data)
- TuShare (requires token, more features)
- BaoStock (free, registration-free historical data)
"""
from .base import BaseDatafeed, DatafeedConfig
from .akshare_datafeed import AKShareDatafeed
from .tushare_datafeed import TuShareDatafeed
from .baostock_datafeed import BaoStockDatafeed

__all__ = [
    "BaseDatafeed",
    "DatafeedConfig",
    "AKShareDatafeed",
    "TuShareDatafeed",
    "BaoStockDatafeed",
    "get_datafeed",
]


def get_datafeed(name: str = "akshare", config: dict = None):
    """
    Get datafeed instance by name.

    Args:
        name: Datafeed name (akshare, tushare, baostock)
        config: Configuration dictionary
            - For TuShare: {"token": "your_token"} or set TUSHARE_TOKEN env var

    Returns:
        Datafeed instance
    """
    datafeeds = {
        "akshare": AKShareDatafeed,
        "tushare": TuShareDatafeed,
        "baostock": BaoStockDatafeed,
    }

    name_lower = name.lower()
    if name_lower not in datafeeds:
        raise ValueError(f"Unknown datafeed: {name}. Available: {list(datafeeds.keys())}")

    return datafeeds[name_lower](config or {})
