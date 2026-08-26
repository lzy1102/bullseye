"""
TuShare Datafeed - Professional Chinese financial data source

TuShare is a professional financial data interface that provides comprehensive
Chinese market data. Requires a free token from https://tushare.pro/

Features:
- A-share stock historical K-line data
- Index data
- Fund/ETF data
- Financial statements
- Real-time quotes (Pro version)

Installation:
    pip install tushare

Get token:
    1. Register at https://tushare.pro/
    2. Get your token from "个人中心" -> "接口Token"
"""
import logging
import time
from datetime import datetime, timedelta
from functools import wraps

import pandas as pd
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


class TuShareDatafeed(BaseDatafeed):
    """
    TuShare data feed for Chinese stock market.

    Provides access to:
    - A-share stocks (Shanghai/Shenzhen)
    - Index data (上证指数, 深证成指, etc.)
    - ETF/LOF funds
    - Futures data
    - Financial data

    Requires TuShare token:
        1. Register at https://tushare.pro/
        2. Get token from "个人中心" -> "接口Token"
        3. Pass token in config or set TUSHARE_TOKEN env var

    Example:
        datafeed = TuShareDatafeed({"token": "your_token"})
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

    # TuShare frequency mapping
    FREQ_MAP = {
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "1h": "60min",
        "1d": "D",
        "1w": "W",
        "1M": "M",
    }

    # Supported intervals
    SUPPORTED_INTERVALS = list(FREQ_MAP.keys())

    # Exchange codes for TuShare
    EXCHANGE_MAP = {
        "SH": "SSE",  # 上海证券交易所
        "SZ": "SZSE", # 深圳证券交易所
        "BJ": "BSE",  # 北京证券交易所
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # Extract token before passing to parent
        config = config or {}
        self._token = config.pop("token", None) or config.pop("tushare_token", None)

        super().__init__(config)
        self._config.name = "tushare"
        self._ts = None
        self._ts_pro = None

        # Get token from environment if not in config
        if not self._token:
            import os
            self._token = os.environ.get("TUSHARE_TOKEN")

    def _do_init(self) -> None:
        """Initialize TuShare"""
        try:
            import tushare as ts

            if not self._token:
                raise ValueError(
                    "TuShare token is required. "
                    "Get your token from https://tushare.pro/ and pass it in config "
                    "or set TUSHARE_TOKEN environment variable."
                )

            # Set token
            ts.set_token(self._token)

            # Initialize pro API
            self._ts = ts
            self._ts_pro = ts.pro_api()

            logger.info("TuShare initialized successfully")

        except ImportError as e:
            raise ImportError(
                "TuShare is not installed. Please run: pip install tushare"
            ) from e

    @property
    def ts(self):
        """Get TuShare module"""
        if self._ts is None:
            self._do_init()
        return self._ts

    @property
    def pro(self):
        """Get TuShare Pro API"""
        if self._ts_pro is None:
            self._do_init()
        return self._ts_pro

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
        ts_code = f"{code}.{exchange}"

        # Set default date range
        if end is None:
            end = datetime.now()
        if start is None:
            if interval in ["1m", "5m", "15m", "30m", "1h"]:
                # Minute data: last 30 days (TuShare limits)
                start = end - timedelta(days=30)
            else:
                # Daily/weekly data: last 2 years
                start = end - timedelta(days=730)

        # Convert interval
        freq = self.FREQ_MAP.get(interval, "D")

        try:
            # Query based on frequency type
            if freq in ["1min", "5min", "15min", "30min", "60min"]:
                df = self._query_minute_data(ts_code, freq, start, end)
            else:
                df = self._query_daily_data(ts_code, freq, start, end, adjust)

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
        ts_code: str,
        freq: str,
        start: datetime,
        end: datetime,
    ) -> Any:
        """
        Query minute-level K-line data using pro_bar.

        Note: Minute data requires higher TuShare permission level.
        """
        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                # Use pro_bar for minute data
                df = self.ts.pro_bar(
                    ts_code=ts_code,
                    freq=freq,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                )
                return df
            except Exception as e:
                error_msg = str(e)
                if "权限" in error_msg or "permission" in error_msg.lower():
                    logger.warning(f"Minute data requires higher TuShare permission: {e}")
                    return None
                if attempt < max_retries - 1:
                    logger.warning(f"Minute data query retry ({attempt + 1}/{max_retries})...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Minute data query failed for {ts_code}: {e}")
                    return None

        return None

    def _query_daily_data(
        self,
        ts_code: str,
        freq: str,
        start: datetime,
        end: datetime,
        adjust: Optional[str] = None,
    ) -> Any:
        """Query daily/weekly/monthly K-line data"""
        max_retries = 3
        retry_delay = 1.0

        # Map adjust type
        adj_map = {
            "qfq": "qfq",
            "hfq": "hfq",
            None: None,
        }
        adj = adj_map.get(adjust)

        for attempt in range(max_retries):
            try:
                # Try pro_bar first (supports adjustment)
                df = self.ts.pro_bar(
                    ts_code=ts_code,
                    freq=freq,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adj=adj,
                )
                return df
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Daily data query retry ({attempt + 1}/{max_retries})...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Daily data query failed for {ts_code}: {e}")
                    return None

        return None

    def _dataframe_to_klines(
        self,
        df: Any,
        symbol: str,
        interval: str,
    ) -> List[KlineData]:
        """Convert TuShare DataFrame to KlineData list"""

        if df is None or df.empty:
            return []

        klines = []

        for _, row in df.iterrows():
            try:
                # TuShare columns: trade_date, open, high, low, close, vol, amount
                # For minute data: trade_time instead of trade_date

                # Parse date/time
                if "trade_date" in row:
                    date_str = str(row["trade_date"])
                    dt = datetime.strptime(date_str, "%Y%m%d")
                elif "trade_time" in row:
                    date_str = str(row["trade_time"])
                    # Format: YYYYMMDD HH:MM or YYYY-MM-DD HH:MM:SS
                    try:
                        dt = datetime.strptime(date_str, "%Y%m%d %H:%M")
                    except ValueError:
                        dt = pd.to_datetime(date_str).to_pydatetime()
                else:
                    continue

                # Create KlineData
                kline = KlineData(
                    symbol=symbol,
                    exchange=symbol.split(".")[-1] if "." in symbol else "",
                    datetime=dt,
                    interval=interval,
                    open_price=float(row.get("open", 0) or 0),
                    high_price=float(row.get("high", 0) or 0),
                    low_price=float(row.get("low", 0) or 0),
                    close_price=float(row.get("close", 0) or 0),
                    volume=float(row.get("vol", 0) or row.get("volume", 0) or 0),
                    turnover=float(row.get("amount", 0) or 0),
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
                - "fund": Public funds

        Returns:
            List of symbol strings
        """
        try:
            if market == "stock":
                df = self.pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name")
                return [row["ts_code"] for _, row in df.iterrows()]

            elif market == "index":
                df = self.pro.index_basic(market="SSE")
                df2 = self.pro.index_basic(market="SZSE")
                df = pd.concat([df, df2])
                return [row["ts_code"] for _, row in df.iterrows()]

            elif market == "etf":
                df = self.pro.fund_basic(market="E")
                return [row["ts_code"] for _, row in df.iterrows()]

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

        Note: Real-time quotes require TuShare Pro permission.

        Args:
            symbol: Stock code (e.g., "000001.SZ")

        Returns:
            Dictionary with quote data or None
        """
        code, exchange = self._parse_symbol(symbol)
        ts_code = f"{code}.{exchange}"

        try:
            # Get latest daily data as quote
            df = self.pro.daily(
                ts_code=ts_code,
                start_date=(datetime.now() - timedelta(days=7)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
            )

            if df is None or df.empty:
                return None

            row = df.iloc[0]
            return {
                "symbol": symbol,
                "name": "",
                "price": float(row.get("close", 0)),
                "change_pct": float(row.get("pct_chg", 0)),
                "change": float(row.get("change", 0)),
                "volume": float(row.get("vol", 0)),
                "turnover": float(row.get("amount", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "open": float(row.get("open", 0)),
                "prev_close": float(row.get("pre_close", 0)),
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
            index_code: Index code (e.g., "000001.SH" for 上证指数)
            start: Start datetime
            end: End datetime

        Returns:
            List of KlineData objects
        """
        if end is None:
            end = datetime.now()
        if start is None:
            start = end - timedelta(days=365)

        # Ensure proper format
        if "." not in index_code:
            code = index_code
            exchange = "SH" if code[0] in ["0", "8", "9"] else "SZ"
            index_code = f"{code}.{exchange}"

        try:
            df = self.pro.index_daily(
                ts_code=index_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )

            if df is None or df.empty:
                return []

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
        code, exchange = self._parse_symbol(symbol)
        ts_code = f"{code}.{exchange}"

        try:
            df = self.pro.stock_basic(
                ts_code=ts_code,
                fields="ts_code,symbol,name,area,industry,market,list_date"
            )

            if df is None or df.empty:
                return None

            row = df.iloc[0]
            return {
                "code": row.get("symbol", ""),
                "name": row.get("name", ""),
                "ts_code": row.get("ts_code", ""),
                "area": row.get("area", ""),
                "industry": row.get("industry", ""),
                "market": row.get("market", ""),
                "list_date": row.get("list_date", ""),
            }

        except Exception as e:
            logger.error(f"Error getting stock info for {symbol}: {e}")
            return None

    def get_financial_data(
        self,
        symbol: str,
        report_type: str = "income",
        period: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get financial data for a stock.

        Args:
            symbol: Stock code
            report_type: Type of report ("income", "balance", "cashflow")
            period: Report period (e.g., "20241231")

        Returns:
            Dictionary with financial data or None
        """
        code, exchange = self._parse_symbol(symbol)
        ts_code = f"{code}.{exchange}"

        try:
            if report_type == "income":
                df = self.pro.income(ts_code=ts_code, period=period)
            elif report_type == "balance":
                df = self.pro.balancesheet(ts_code=ts_code, period=period)
            elif report_type == "cashflow":
                df = self.pro.cashflow(ts_code=ts_code, period=period)
            else:
                return None

            if df is None or df.empty:
                return None

            return df.iloc[0].to_dict()

        except Exception as e:
            logger.error(f"Error getting financial data for {symbol}: {e}")
            return None

    def get_trade_calendar(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[datetime]:
        """
        Get trade calendar.

        Args:
            start: Start date
            end: End date

        Returns:
            List of trade dates
        """
        if end is None:
            end = datetime.now()
        if start is None:
            start = end - timedelta(days=365)

        try:
            df = self.pro.trade_cal(
                exchange="SSE",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                is_open="1",
            )

            if df is None or df.empty:
                return []

            dates = []
            for _, row in df.iterrows():
                date_str = str(row["cal_date"])
                dates.append(datetime.strptime(date_str, "%Y%m%d"))

            return sorted(dates)

        except Exception as e:
            logger.error(f"Error getting trade calendar: {e}")
            return []

    def search_stocks(self, keyword: str) -> List[Dict[str, str]]:
        """
        Search stocks by keyword.

        Args:
            keyword: Search keyword (name or code)

        Returns:
            List of matching stocks
        """
        try:
            df = self.pro.stock_basic(exchange="", list_status="L")
            keyword = keyword.upper()

            matches = []
            for _, row in df.iterrows():
                code = str(row.get("symbol", ""))
                name = str(row.get("name", ""))

                if keyword in code or keyword in name:
                    matches.append({
                        "code": code,
                        "name": name,
                        "symbol": row.get("ts_code", ""),
                        "industry": row.get("industry", ""),
                    })

            return matches[:50]  # Limit to 50 results

        except Exception as e:
            logger.error(f"Error searching stocks for {keyword}: {e}")
            return []

    # ==================== TuShare Specific Features ====================

    def get_money_flow(self, symbol: str, start: datetime = None, end: datetime = None) -> Any:
        """
        Get money flow data (资金流向).

        Args:
            symbol: Stock code
            start: Start date
            end: End date

        Returns:
            DataFrame with money flow data
        """
        code, exchange = self._parse_symbol(symbol)
        ts_code = f"{code}.{exchange}"

        if end is None:
            end = datetime.now()
        if start is None:
            start = end - timedelta(days=30)

        try:
            df = self.pro.moneyflow(
                ts_code=ts_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            return df
        except Exception as e:
            logger.error(f"Error getting money flow for {symbol}: {e}")
            return None

    def get_limit_price(self, trade_date: datetime = None) -> Any:
        """
        Get limit up/down stocks (涨跌停).

        Args:
            trade_date: Trade date

        Returns:
            DataFrame with limit price data
        """
        if trade_date is None:
            trade_date = datetime.now()

        try:
            df = self.pro.limit_list(
                trade_date=trade_date.strftime("%Y%m%d"),
            )
            return df
        except Exception as e:
            logger.error(f"Error getting limit price for {trade_date}: {e}")
            return None

