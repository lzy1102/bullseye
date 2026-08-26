"""
Base Datafeed - Abstract base class for market data sources
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Any
import logging

from bullseye.trader.object.kline import KlineData

logger = logging.getLogger(__name__)


@dataclass
class DatafeedConfig:
    """Datafeed configuration"""
    # General settings
    name: str = "akshare"

    # Cache settings
    cache_enabled: bool = True
    cache_dir: str = "user_data/cache"
    cache_expire_hours: int = 24

    # Rate limiting
    rate_limit: int = 10  # requests per second
    rate_limit_period: int = 1  # seconds

    # Retry settings
    max_retries: int = 3
    retry_delay: float = 1.0

    # Extra settings
    extra: Dict[str, Any] = field(default_factory=dict)


class BaseDatafeed(ABC):
    """
    Abstract base class for market data feeds.

    Provides unified interface for fetching historical market data
    from different sources (AKShare, TuShare, etc.)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize datafeed.

        Args:
            config: Configuration dictionary
        """
        self._config = DatafeedConfig(**(config or {}))
        self._initialized = False
        self._cache: Dict[str, Any] = {}

    @property
    def name(self) -> str:
        """Get datafeed name"""
        return self._config.name

    def init(self, output: Callable = print) -> bool:
        """
        Initialize datafeed connection.

        Args:
            output: Output function for messages

        Returns:
            True if initialization successful
        """
        try:
            self._do_init()
            self._initialized = True
            output(f"[{self.name}] Datafeed initialized successfully")
            return True
        except Exception as e:
            output(f"[{self.name}] Initialization failed: {e}")
            logger.error(f"Datafeed initialization failed: {e}", exc_info=True)
            return False

    @abstractmethod
    def _do_init(self) -> None:
        """Subclass implementation of initialization"""
        pass

    @abstractmethod
    def query_history(
        self,
        symbol: str,
        interval: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
        adjust: Optional[str] = None,
    ) -> List[KlineData]:
        """
        Query historical K-line data.

        Args:
            symbol: Trading symbol (e.g., "000001.SZ", "BTC/USDT")
            interval: Timeframe (e.g., "1m", "5m", "1h", "1d")
            start: Start datetime
            end: End datetime
            limit: Maximum number of candles
            adjust: Price adjustment type ("qfq"=前复权, "hfq"=后复权, None=不复权)

        Returns:
            List of KlineData objects
        """
        pass

    def query_latest(
        self,
        symbol: str,
        interval: str,
        limit: int = 100,
    ) -> List[KlineData]:
        """
        Query latest K-line data.

        Args:
            symbol: Trading symbol
            interval: Timeframe
            limit: Number of candles

        Returns:
            List of KlineData objects
        """
        return self.query_history(symbol, interval, limit=limit)

    @abstractmethod
    def get_supported_intervals(self) -> List[str]:
        """
        Get supported timeframes.

        Returns:
            List of interval strings
        """
        pass

    @abstractmethod
    def get_supported_symbols(self, market: str = "stock") -> List[str]:
        """
        Get list of supported trading symbols.

        Args:
            market: Market type (stock, index, etf, etc.)

        Returns:
            List of symbol strings
        """
        pass

    def is_initialized(self) -> bool:
        """Check if datafeed is initialized"""
        return self._initialized

    def close(self) -> None:
        """Close datafeed connection"""
        self._cache.clear()
        self._initialized = False

    # ==================== Utility Methods ====================

    def _parse_symbol(self, symbol: str) -> tuple:
        """
        Parse symbol into code and exchange.

        Args:
            symbol: Symbol string (e.g., "000001.SZ", "000001/SZ", "000001")

        Returns:
            (code, exchange) tuple
        """
        symbol = symbol.upper().strip()

        if "/" in symbol:
            code, exchange = symbol.split("/")
        elif "." in symbol:
            code, exchange = symbol.split(".")
        elif len(symbol) == 6 and symbol.isdigit():
            # Auto-detect exchange from code
            if symbol[0] in ["6", "8", "9"]:
                code, exchange = symbol, "SH"
            elif symbol[0] in ["0", "2", "3"]:
                code, exchange = symbol, "SZ"
            else:
                code, exchange = symbol, "SZ"
        else:
            code, exchange = symbol, "SZ"

        return code, exchange

    def _interval_to_akshare(self, interval: str) -> str:
        """
        Convert interval to AKShare format.

        Args:
            interval: Standard interval (1m, 5m, 1h, 1d)

        Returns:
            AKShare period string
        """
        mapping = {
            "1m": "1",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "1d": "daily",
            "1w": "weekly",
            "1M": "monthly",
        }
        return mapping.get(interval, interval)

    def _generate_cache_key(
        self,
        symbol: str,
        interval: str,
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> str:
        """Generate cache key for query"""
        start_str = start.strftime("%Y%m%d") if start else "none"
        end_str = end.strftime("%Y%m%d") if end else "now"
        return f"{symbol}_{interval}_{start_str}_{end_str}"
