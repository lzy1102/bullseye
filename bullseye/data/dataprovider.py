"""
DataProvider - Market data provider for trading strategies.

Provides a Freqtrade-compatible interface for strategies to access
market data, exchange information, and runtime state.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from bullseye.configuration.config import Config
from bullseye.data.market_adapter import MarketAdapterFactory
from bullseye.gateway.base import BaseGateway
from bullseye.trader.object.kline import KlineData
from bullseye.trader.object.orderbook import OrderBookData

logger = logging.getLogger(__name__)


class DataProvider:
    """
    Data provider for trading strategies.

    This class provides a Freqtrade-compatible interface for strategies
    to access market data, exchange information, and runtime state.

    The DataProvider is injected into strategies via the `dp` attribute
    and can be used within strategy methods to access additional data.

    Example:
        def populate_indicators(self, dataframe, metadata):
            # Get additional data
            btc_data = self.dp.historic_ohlcv("BTC/USDT", "1h")
            dataframe['btc_close'] = btc_data['close']
            return dataframe
    """

    def __init__(
        self,
        config: Config,
        gateway: BaseGateway,
        pairlist: Optional[List[str]] = None,
    ):
        """
        Initialize the DataProvider.

        Args:
            config: Configuration object
            gateway: Trading gateway for fetching data
            pairlist: List of trading pairs (optional, will use config if not provided)
        """
        self._config = config
        self._gateway = gateway
        self._pairlist = pairlist or []

        # Market adapter for pair format conversion
        self._market_adapter = MarketAdapterFactory.auto_detect(
            self._pairlist[0] if self._pairlist else "BTC/USDT"
        )

        # OHLCV data cache: {(pair, timeframe): DataFrame}
        self._ohlcv_cache: Dict[Tuple[str, str], pd.DataFrame] = {}

        # Cache expiration time in seconds
        self._cache_timeout = 60

        # Last cache update time
        self._cache_updated: Dict[Tuple[str, str], datetime] = {}

        # Run mode
        self._runmode = "dry_run" if config.dry_run else "live"

        # Order book cache: {pair: (OrderBookData, datetime)}
        self._orderbook_cache: Dict[str, Tuple[OrderBookData, datetime]] = {}
        self._orderbook_cache_timeout = 5  # seconds

        # Pending messages for strategy
        self._messages: List[str] = []

    def historic_ohlcv(
        self,
        pair: str,
        timeframe: str,
        limit: Optional[int] = None,
        startup_candles: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Get historical OHLCV data for a pair.

        Args:
            pair: Trading pair (e.g., "BTC/USDT")
            timeframe: Timeframe (e.g., "5m", "1h", "1d")
            limit: Maximum number of candles to return
            startup_candles: Number of startup candles (for indicators)

        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        cache_key = (pair, timeframe)

        # Check cache
        if self._is_cache_valid(cache_key):
            cached = self._ohlcv_cache.get(cache_key)
            if cached is not None:
                if limit:
                    return cached.tail(limit).reset_index(drop=True)
                return cached.copy()

        # Fetch from gateway
        try:
            klines = self._gateway.get_bars(
                symbol=pair,
                interval=timeframe,
                limit=limit or startup_candles or 500,
            )

            if not klines:
                logger.warning(f"No OHLCV data available for {pair} {timeframe}")
                return self._empty_dataframe()

            # Convert to DataFrame
            df = self._klines_to_dataframe(klines)

            # Update cache
            self._ohlcv_cache[cache_key] = df
            self._cache_updated[cache_key] = datetime.now()

            return df

        except Exception as e:
            logger.error(f"Error fetching OHLCV for {pair} {timeframe}: {e}")
            return self._empty_dataframe()

    def latest_ohlcv(
        self,
        pair: str,
        timeframe: str,
        limit: int = 1,
    ) -> pd.DataFrame:
        """
        Get the latest OHLCV data.

        This is a convenience method that calls historic_ohlcv with a limit.

        Args:
            pair: Trading pair
            timeframe: Timeframe
            limit: Number of latest candles (default 1)

        Returns:
            DataFrame with the latest candles
        """
        return self.historic_ohlcv(pair, timeframe, limit=limit)

    def orderbook(
        self,
        pair: str,
        limit: int = 10,
        *,
        cache_timeout: Optional[float] = None,
    ) -> Optional[OrderBookData]:
        """
        Get order book snapshot for a pair.

        Results are cached for ``_orderbook_cache_timeout`` seconds (default 5s)
        to avoid hitting exchange rate limits when called repeatedly within
        a single strategy cycle.

        Args:
            pair: Trading pair (e.g., "BTC/USDT")
            limit: Number of price levels per side
            cache_timeout: Override default cache timeout in seconds.
                           Pass 0 or negative to force a fresh fetch.

        Returns:
            OrderBookData or None on failure
        """
        # Check cache
        cache_timeout = cache_timeout if cache_timeout is not None else self._orderbook_cache_timeout
        if cache_timeout > 0 and pair in self._orderbook_cache:
            ob, ts = self._orderbook_cache[pair]
            if (datetime.now() - ts).total_seconds() < cache_timeout:
                return ob

        # Fetch from gateway
        try:
            ob = self._gateway.get_order_book(pair, limit)
            if ob is not None:
                self._orderbook_cache[pair] = (ob, datetime.now())
            return ob
        except Exception as e:
            logger.error(f"Error fetching order book for {pair}: {e}")
            return None

    def _klines_to_dataframe(self, klines: List[KlineData]) -> pd.DataFrame:
        """
        Convert list of KlineData to DataFrame.

        Args:
            klines: List of KlineData objects

        Returns:
            DataFrame with OHLCV data
        """
        data = []
        for kline in klines:
            data.append({
                "date": kline.datetime,
                "open": kline.open_price,
                "high": kline.high_price,
                "low": kline.low_price,
                "close": kline.close_price,
                "volume": kline.volume,
            })

        df = pd.DataFrame(data)

        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

        return df

    def _empty_dataframe(self) -> pd.DataFrame:
        """Return an empty OHLCV DataFrame."""
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    def _is_cache_valid(self, cache_key: Tuple[str, str]) -> bool:
        """Check if cached data is still valid."""
        if cache_key not in self._cache_updated:
            return False

        elapsed = (datetime.now() - self._cache_updated[cache_key]).total_seconds()
        return elapsed < self._cache_timeout

    def clear_cache(self, pair: Optional[str] = None, timeframe: Optional[str] = None) -> None:
        """
        Clear the OHLCV and order book cache.

        Args:
            pair: Clear cache for this pair only (optional)
            timeframe: Clear cache for this timeframe only (optional)
        """
        if pair is None and timeframe is None:
            self._ohlcv_cache.clear()
            self._cache_updated.clear()
            self._orderbook_cache.clear()
        elif pair and timeframe:
            cache_key = (pair, timeframe)
            self._ohlcv_cache.pop(cache_key, None)
            self._cache_updated.pop(cache_key, None)
        elif pair:
            # Clear all timeframes for this pair
            keys_to_remove = [k for k in self._ohlcv_cache if k[0] == pair]
            for key in keys_to_remove:
                self._ohlcv_cache.pop(key, None)
                self._cache_updated.pop(key, None)
            # Clear order book cache for this pair
            self._orderbook_cache.pop(pair, None)

    def current_whitelist(self) -> List[str]:
        """
        Get the current list of whitelisted trading pairs.

        Returns:
            List of trading pair strings
        """
        return self._pairlist.copy()

    def get_pairlist(self) -> List[str]:
        """
        Get the current pairlist (alias for current_whitelist).

        Returns:
            List of trading pair strings
        """
        return self.current_whitelist()

    def set_pairlist(self, pairlist: List[str]) -> None:
        """
        Set the pairlist.

        Args:
            pairlist: List of trading pairs
        """
        self._pairlist = pairlist

    def runmode(self) -> str:
        """
        Get the current run mode.

        Returns:
            "dry_run" or "live"
        """
        return self._runmode

    def send_msg(self, message: str, *, msg_type: str = "info") -> None:
        """
        Send a message to the bot.

        This method allows strategies to send notifications or log messages.
        In a full implementation, this could integrate with Telegram, Discord, etc.

        Args:
            message: Message to send
            msg_type: Message type (info, warning, error)
        """
        self._messages.append(message)
        logger.info(f"Strategy message [{msg_type}]: {message}")

    def get_messages(self) -> List[str]:
        """
        Get pending messages and clear the message queue.

        Returns:
            List of pending messages
        """
        messages = self._messages.copy()
        self._messages.clear()
        return messages

    def refresh(
        self,
        pair: str,
        timeframe: str,
    ) -> pd.DataFrame:
        """
        Refresh OHLCV data for a pair, bypassing cache.

        Args:
            pair: Trading pair
            timeframe: Timeframe

        Returns:
            Fresh DataFrame with OHLCV data
        """
        cache_key = (pair, timeframe)
        if cache_key in self._ohlcv_cache:
            del self._ohlcv_cache[cache_key]
        if cache_key in self._cache_updated:
            del self._cache_updated[cache_key]

        return self.historic_ohlcv(pair, timeframe)

    def get_analyzed_dataframe(
        self,
        pair: str,
        timeframe: str,
    ) -> Tuple[pd.DataFrame, datetime]:
        """
        Get the analyzed dataframe for a pair.

        This method is used by the strategy runner to get the latest
        analyzed data with all indicators populated.

        Args:
            pair: Trading pair
            timeframe: Timeframe

        Returns:
            Tuple of (DataFrame, last_analyzed_time)
        """
        df = self.historic_ohlcv(pair, timeframe)
        last_time = df["date"].iloc[-1] if not df.empty else datetime.now()
        return df, last_time

    @property
    def exchange(self) -> Any:
        """
        Get the exchange/gateway object.

        Returns:
            The gateway instance
        """
        return self._gateway

    @property
    def wallet(self) -> Any:
        """
        Get wallet information.

        Note: This is a placeholder. The actual wallet is managed separately.

        Returns:
            None (placeholder)
        """
        return None

    def custom_store(self, key: str, value: Any) -> None:
        """
        Store a custom value for later retrieval.

        Args:
            key: Storage key
            value: Value to store
        """
        if not hasattr(self, "_custom_storage"):
            self._custom_storage = {}
        self._custom_storage[key] = value

    def custom_get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a custom stored value.

        Args:
            key: Storage key
            default: Default value if key not found

        Returns:
            Stored value or default
        """
        if not hasattr(self, "_custom_storage"):
            return default
        return self._custom_storage.get(key, default)
