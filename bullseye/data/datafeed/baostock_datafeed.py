"""
BaoStock Datafeed - Free Chinese stock market historical data source.

BaoStock is a free, registration-free interface providing A-share history:
- Daily/weekly/monthly K-line (1990+)
- Minute K-line (5/15/30/60 min, recent years only)
- Adjusted prices server-side via adjustflag (qfq/hfq)

Notes:
- Session based: requires explicit login/logout per process.
- Code format differs: "sh.600000" instead of "600000.SH".
- No Beijing Stock Exchange (BJ) support.
- Data updates after market close (not suitable for intraday quotes).

Installation:
    pip install baostock
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from .base import BaseDatafeed
from bullseye.trader.object.kline import KlineData

logger = logging.getLogger(__name__)


class BaoStockDatafeed(BaseDatafeed):
    """
    BaoStock data feed for Chinese A-share historical data.

    Example:
        datafeed = BaoStockDatafeed()
        datafeed.init()

        klines = datafeed.query_history(
            symbol="000001.SZ",
            interval="1d",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 12, 31),
            adjust="qfq",
        )
    """

    # Standard interval -> BaoStock frequency
    FREQ_MAP = {
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "1d": "d",
        "1w": "w",
        "1M": "m",
    }

    SUPPORTED_INTERVALS = list(FREQ_MAP.keys())

    # Price adjustment flags
    ADJUST_MAP = {
        "qfq": "2",   # 前复权
        "hfq": "1",   # 后复权
        None: "3",    # 不复权
    }

    # Fields requested from query_history_k_data_plus
    DAILY_FIELDS = "date,code,open,high,low,close,volume,amount"
    MINUTE_FIELDS = "time,code,open,high,low,close,volume,amount"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._config.name = "baostock"

    def _do_init(self) -> None:
        """Login to the BaoStock session."""
        try:
            import baostock as bs
        except ImportError as e:
            raise ImportError(
                "BaoStock is not installed. Please run: pip install baostock"
            ) from e

        self._bs = bs
        result = bs.login()
        if result is None or getattr(result, "error_code", "1") != "0":
            msg = getattr(result, "error_msg", "unknown error") if result else "no response"
            raise ConnectionError(f"BaoStock login failed: {msg}")
        logger.info("BaoStock logged in successfully")

    @property
    def bs(self):
        """Get the baostock module (lazy init)."""
        if not getattr(self, "_bs", None):
            self._do_init()
        return self._bs

    def close(self) -> None:
        """Logout from the BaoStock session."""
        try:
            if getattr(self, "_bs", None):
                self._bs.logout()
        except Exception as e:
            logger.debug(f"BaoStock logout ignored: {e}")
        super().close()

    # ==================== Symbol Conversion ====================

    @staticmethod
    def _to_baostock_code(code: str, exchange: str) -> str:
        """Convert "000001.SZ"-style parts into "sz.000001"."""
        exchange = exchange.upper()
        if exchange == "BJ":
            raise ValueError("BaoStock does not support Beijing Stock Exchange (BJ)")
        return f"{exchange.lower()}.{code}"

    # ==================== Data Query ====================

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
            symbol: Stock code (e.g. "000001.SZ", "600000.SH", "000001")
            interval: Timeframe (5m, 15m, 30m, 1h, 1d, 1w, 1M)
            start: Start datetime (default: 2 years ago for daily, 30 days for minute)
            end: End datetime (default: now)
            limit: Maximum number of candles
            adjust: "qfq" | "hfq" | None (default)

        Returns:
            List of KlineData objects
        """
        code, exchange = self._parse_symbol(symbol)
        bs_code = self._to_baostock_code(code, exchange)

        freq = self.FREQ_MAP.get(interval)
        if freq is None:
            logger.warning(f"BaoStock does not support interval '{interval}'")
            return []

        if end is None:
            end = datetime.now()
        if start is None:
            # Minute history on BaoStock only covers recent years
            days_back = 30 if freq in ("5", "15", "30", "60") else 730
            start = end - timedelta(days=days_back)

        adjustflag = self.ADJUST_MAP.get(adjust, "3")

        try:
            rows = self._query_rows(
                bs_code,
                start.strftime("%Y-%m-%d"),
                end.strftime("%Y-%m-%d"),
                freq,
                adjustflag,
            )

            klines = [
                k for k in (
                    self._row_to_kline(r, symbol, interval, freq)
                    for r in rows
                )
                if k is not None
            ]
            klines.sort(key=lambda x: x.datetime)

            if limit and len(klines) > limit:
                klines = klines[-limit:]
            return klines

        except Exception as e:
            logger.error(f"BaoStock query failed for {symbol} {interval}: {e}")
            return []

    def _query_rows(
        self,
        bs_code: str,
        start_str: str,
        end_str: str,
        freq: str,
        adjustflag: str,
    ) -> List[List[str]]:
        """Execute query_history_k_data_plus and drain the ResultData cursor."""
        fields = self.MINUTE_FIELDS if freq in ("5", "15", "30", "60") else self.DAILY_FIELDS

        rs = self.bs.query_history_k_data_plus(
            bs_code,
            fields,
            start_date=start_str,
            end_date=end_str,
            frequency=freq,
            adjustflag=adjustflag,
        )

        rows = []
        while (getattr(rs, "error_code", "1") == "0") and rs.next():
            rows.append(rs.get_row_data())

        if getattr(rs, "error_code", "0") != "0":
            logger.warning(
                f"BaoStock returned error for {bs_code}: {rs.error_msg}"
            )
        return rows

    def _row_to_kline(
        self, row: List[str], symbol: str, interval: str, freq: str
    ) -> Optional[KlineData]:
        """Convert a raw BaoStock row into KlineData (None if unparsable)."""
        try:
            if freq in ("5", "15", "30", "60"):
                # time format: "YYYYMMDDHHMMSSsss"
                dt = datetime.strptime(row[0][:14], "%Y%m%d%H%M%S")
            else:
                dt = datetime.strptime(row[0], "%Y-%m-%d")

            def num(value: str) -> float:
                return float(value) if value not in ("", None) else 0.0

            # Daily row layout: date,code,open,high,low,close,volume,amount
            # Minute row layout: time,code,open,high,low,close,volume,amount
            return KlineData(
                symbol=symbol,
                exchange=symbol.split(".")[-1] if "." in symbol else "",
                datetime=dt,
                interval=interval,
                open_price=num(row[2]),
                high_price=num(row[3]),
                low_price=num(row[4]),
                close_price=num(row[5]),
                volume=num(row[6]),
                turnover=num(row[7]),
            )
        except (ValueError, IndexError) as e:
            logger.debug(f"Skipping unparsable BaoStock row ({e}): {row}")
            return None

    # ==================== Interface Methods ====================

    def get_supported_intervals(self) -> List[str]:
        """Get supported timeframes."""
        return self.SUPPORTED_INTERVALS.copy()

    def get_supported_symbols(self, market: str = "stock") -> List[str]:
        """
        Get list of tradable symbols (A-shares only).

        Returns listed stocks in standard bullseye format, e.g. "000001.SZ".
        """
        try:
            rs = self.bs.query_stock_basic()
            symbols = []
            while (getattr(rs, "error_code", "1") == "0") and rs.next():
                row = rs.get_row_data()
                # fields: code, code_name, ipoDate, outDate, type, status
                code, out_date, stock_type, status = row[0], row[3], row[4], row[5]
                if stock_type != "1":  # 1 = stock
                    continue
                if status != "1" and not market == "all":  # delisted
                    continue
                if "." not in code:
                    continue
                suffix, num = code.split(".", 1)
                symbols.append(f"{num}.{suffix.upper()}")
            return symbols
        except Exception as e:
            logger.error(f"BaoStock get_supported_symbols failed: {e}")
            return []
