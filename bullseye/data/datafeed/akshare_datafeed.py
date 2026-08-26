"""
AKShare Datafeed - Free Chinese stock market data source

AKShare is an open-source financial data interface library that provides
free access to Chinese stock market data without requiring a token.

Features:
- A-share stock historical K-line data
- Index data
- ETF data
- Real-time quotes
- Fund flow data

Installation:
    pip install akshare
"""
import logging
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Dict, List, Optional, Any

from .base import BaseDatafeed
from bullseye.trader.object.kline import KlineData

logger = logging.getLogger(__name__)


def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    """Decorator to retry function on failure"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying in {delay}s...")
                        time.sleep(delay)
            raise last_error
        return wrapper
    return decorator


class AKShareDatafeed(BaseDatafeed):
    """
    AKShare data feed for Chinese stock market.

    Provides free access to:
    - A-share stocks (Shanghai/Shenzhen)
    - Index data (上证指数, 深证成指, etc.)
    - ETF funds
    - Real-time quotes

    Example:
        datafeed = AKShareDatafeed()
        datafeed.init()

        # Get daily K-line data
        klines = datafeed.query_history(
            symbol="000001.SZ",
            interval="1d",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 12, 31),
            adjust="qfq"  # Forward adjusted
        )
    """

    # AKShare period mapping
    PERIOD_MAP = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "1d": "daily",
        "1w": "weekly",
        "1M": "monthly",
    }

    # Supported intervals
    SUPPORTED_INTERVALS = list(PERIOD_MAP.keys())

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._config.name = "akshare"
        self._ak = None

    def _do_init(self) -> None:
        """Initialize AKShare"""
        try:
            import akshare as ak
            self._ak = ak
            logger.info("AKShare initialized successfully")
        except ImportError as e:
            raise ImportError(
                "AKShare is not installed. Please run: pip install akshare"
            ) from e

    @property
    def ak(self):
        """Get AKShare module"""
        if self._ak is None:
            self._do_init()
        return self._ak

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
        Query historical K-line data for A-share stocks.

        Args:
            symbol: Stock code (e.g., "000001.SZ", "600000.SH", "000001")
            interval: Timeframe (1m, 5m, 15m, 30m, 1h, 1d, 1w, 1M)
            start: Start datetime (default: 1 year ago)
            end: End datetime (default: now)
            limit: Maximum number of candles (optional)
            adjust: Price adjustment type
                - "qfq": 前复权 (forward adjusted)
                - "hfq": 后复权 (backward adjusted)
                - None: 不复权 (no adjustment)

        Returns:
            List of KlineData objects
        """
        code, exchange = self._parse_symbol(symbol)

        # Set default date range
        if end is None:
            end = datetime.now()
        if start is None:
            if interval in ["1m", "5m", "15m", "30m", "1h"]:
                # Minute data: last 30 days
                start = end - timedelta(days=30)
            else:
                # Daily/weekly data: last 2 years
                start = end - timedelta(days=730)

        # Convert interval
        period = self.PERIOD_MAP.get(interval, "daily")

        # Adjust type for AKShare
        adjust_map = {
            "qfq": "qfq",
            "hfq": "hfq",
            None: "",
            "": "",
        }
        adjust_type = adjust_map.get(adjust, "")

        try:
            # Query based on period type
            if period in ["1", "5", "15", "30", "60"]:
                # Minute-level data
                df = self._query_minute_data(code, period, start, end, adjust_type)
            else:
                # Daily/weekly/monthly data
                df = self._query_daily_data(code, period, start, end, adjust_type)

            if df is None or df.empty:
                logger.warning(f"No data found for {symbol} {interval}")
                return []

            # Convert to KlineData
            klines = self._dataframe_to_klines(df, symbol, interval)

            # Apply limit
            if limit and len(klines) > limit:
                klines = klines[-limit:]

            return klines

        except Exception as e:
            logger.error(f"Error querying {symbol} {interval}: {e}", exc_info=True)
            return []

    def _query_minute_data(
        self,
        code: str,
        period: str,
        start: datetime,
        end: datetime,
        adjust: str,
    ) -> Any:
        """Query minute-level K-line data"""
        try:
            # Try stock_zh_a_hist_min_em first (东方财富数据源)
            # Note: This API may have different parameters in different akshare versions
            try:
                df = self.ak.stock_zh_a_hist_min_em(
                    symbol=code,
                    period=period,
                    adjust=adjust,
                )
                if df is not None and not df.empty:
                    # Filter by date range
                    import pandas as pd
                    df['时间'] = pd.to_datetime(df['时间'])
                    df = df[(df['时间'] >= start) & (df['时间'] <= end)]
                    return df
            except TypeError:
                # Older API version - different parameters
                pass

            # Alternative: Use stock_intraday_em (东方财富分时数据)
            try:
                df = self.ak.stock_intraday_em(symbol=code)
                if df is not None and not df.empty:
                    return df
            except Exception:
                pass

            # Fallback: Use daily data aggregation for testing
            logger.warning(f"Minute data not available for {code}, falling back to daily data")
            return self._query_daily_data(code, "daily", start, end, adjust)

        except Exception as e:
            logger.error(f"Minute data query failed for {code}: {e}")
            return None

    def _query_daily_data(
        self,
        code: str,
        period: str,
        start: datetime,
        end: datetime,
        adjust: str,
    ) -> Any:
        """Query daily/weekly/monthly K-line data"""
        max_retries = 3
        retry_delay = 2.0

        for attempt in range(max_retries):
            try:
                df = self.ak.stock_zh_a_hist(
                    symbol=code,
                    period=period,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust=adjust,
                )
                return df
            except Exception as e:
                error_msg = str(e)
                if "Connection" in error_msg or "timeout" in error_msg.lower():
                    if attempt < max_retries - 1:
                        logger.warning(f"Network error for {code}, retrying ({attempt + 1}/{max_retries})...")
                        time.sleep(retry_delay * (attempt + 1))
                        continue
                logger.error(f"Daily data query failed for {code}: {e}")
                return None

        return None

    def _dataframe_to_klines(
        self,
        df: Any,
        symbol: str,
        interval: str,
    ) -> List[KlineData]:
        """Convert DataFrame to KlineData list"""
        import pandas as pd

        klines = []

        # Standardize column names
        column_mapping = {
            "日期": "date",
            "时间": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "turnover",
            "振幅": "amplitude",
            "涨跌幅": "change_pct",
            "涨跌额": "change",
            "换手率": "turnover_rate",
        }

        df = df.rename(columns=column_mapping)

        for _, row in df.iterrows():
            try:
                # Parse date
                date_val = row.get("date")
                if pd.isna(date_val):
                    continue

                if isinstance(date_val, str):
                    dt = pd.to_datetime(date_val)
                else:
                    dt = date_val

                # Create KlineData
                kline = KlineData(
                    symbol=symbol,
                    exchange=symbol.split(".")[-1] if "." in symbol else "",
                    datetime=dt.to_pydatetime(),
                    interval=interval,
                    open_price=float(row.get("open", 0)),
                    high_price=float(row.get("high", 0)),
                    low_price=float(row.get("low", 0)),
                    close_price=float(row.get("close", 0)),
                    volume=float(row.get("volume", 0)),
                    turnover=float(row.get("turnover", 0)),
                )
                klines.append(kline)

            except Exception as e:
                logger.debug(f"Error parsing row: {e}")
                continue

        # Sort by datetime
        klines.sort(key=lambda x: x.datetime)
        return klines

    def get_supported_intervals(self) -> List[str]:
        """Get supported timeframes"""
        return self.SUPPORTED_INTERVALS.copy()

    def get_supported_symbols(self, market: str = "stock") -> List[str]:
        """
        Get list of supported trading symbols.

        Args:
            market: Market type
                - "stock": A-share stocks
                - "index": Indices
                - "etf": ETF funds

        Returns:
            List of symbol strings
        """
        try:
            if market == "stock":
                df = self.ak.stock_zh_a_spot_em()
                # Return code + name
                return [f"{row['代码']}.{self._get_exchange(row['代码'])}"
                        for _, row in df.iterrows()]

            elif market == "index":
                # Major indices
                return [
                    "000001.SH",  # 上证指数
                    "399001.SZ",  # 深证成指
                    "399006.SZ",  # 创业板指
                    "000016.SH",  # 上证50
                    "000300.SH",  # 沪深300
                    "000905.SH",  # 中证500
                    "000852.SH",  # 中证1000
                ]

            elif market == "etf":
                df = self.ak.fund_etf_spot_em()
                return [f"{row['代码']}.{self._get_exchange(row['代码'])}"
                        for _, row in df.iterrows()]

            else:
                return []

        except Exception as e:
            logger.error(f"Error getting symbols for {market}: {e}")
            return []

    def _get_exchange(self, code: str) -> str:
        """Get exchange from stock code"""
        if not code:
            return "SZ"
        first_char = code[0]
        if first_char in ["6", "8", "9"]:
            return "SH"
        return "SZ"

    # ==================== Additional Features ====================

    def get_realtime_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get real-time quote for a stock.

        Args:
            symbol: Stock code (e.g., "000001.SZ")

        Returns:
            Dictionary with quote data or None
        """
        code, _ = self._parse_symbol(symbol)

        try:
            df = self.ak.stock_zh_a_spot_em()
            row = df[df["代码"] == code]

            if row.empty:
                return None

            row = row.iloc[0]
            return {
                "symbol": symbol,
                "name": row.get("名称", ""),
                "price": float(row.get("最新价", 0)),
                "change_pct": float(row.get("涨跌幅", 0)),
                "change": float(row.get("涨跌额", 0)),
                "volume": float(row.get("成交量", 0)),
                "turnover": float(row.get("成交额", 0)),
                "high": float(row.get("最高", 0)),
                "low": float(row.get("最低", 0)),
                "open": float(row.get("今开", 0)),
                "prev_close": float(row.get("昨收", 0)),
            }

        except Exception as e:
            logger.error(f"Error getting real-time quote for {symbol}: {e}")
            return None

    def get_index_data(
        self,
        index_code: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[KlineData]:
        """
        Get index K-line data.

        Args:
            index_code: Index code (e.g., "000001" for 上证指数)
            start: Start datetime
            end: End datetime

        Returns:
            List of KlineData objects
        """
        if end is None:
            end = datetime.now()
        if start is None:
            start = end - timedelta(days=365)

        try:
            df = self.ak.stock_zh_index_daily(symbol=f"sh{index_code}")

            if df is None or df.empty:
                return []

            # Filter by date
            df["date"] = df["date"].astype(str)
            df = df[
                (df["date"] >= start.strftime("%Y-%m-%d")) &
                (df["date"] <= end.strftime("%Y-%m-%d"))
            ]

            return self._dataframe_to_klines(df, index_code, "1d")

        except Exception as e:
            logger.error(f"Error getting index data for {index_code}: {e}")
            return []

    def get_stock_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get stock basic information.

        Args:
            symbol: Stock code

        Returns:
            Dictionary with stock info or None
        """
        code, _ = self._parse_symbol(symbol)

        try:
            df = self.ak.stock_individual_info_em(symbol=code)

            if df is None or df.empty:
                return None

            info = {}
            for _, row in df.iterrows():
                info[row["item"]] = row["value"]

            return info

        except Exception as e:
            logger.error(f"Error getting stock info for {symbol}: {e}")
            return None

    def search_stocks(self, keyword: str) -> List[Dict[str, str]]:
        """
        Search stocks by keyword.

        Args:
            keyword: Search keyword (name or code)

        Returns:
            List of matching stocks
        """
        try:
            df = self.ak.stock_zh_a_spot_em()
            keyword = keyword.upper()

            matches = []
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                name = str(row.get("名称", ""))

                if keyword in code or keyword in name:
                    matches.append({
                        "code": code,
                        "name": name,
                        "symbol": f"{code}.{self._get_exchange(code)}",
                    })

            return matches[:50]  # Limit to 50 results

        except Exception as e:
            logger.error(f"Error searching stocks for {keyword}: {e}")
            return []
