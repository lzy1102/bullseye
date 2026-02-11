"""
Kline Data - OHLCV candlestick data structure
"""
from datetime import datetime
from typing import Optional
from dataclasses import dataclass


@dataclass
class KlineData:
    """
    Kline (candlestick) data object

    Compatible with Freqtrade dataframe format and CCXT OHLCV data
    """
    # Basic information
    gateway_name: str = ""
    symbol: str = ""
    exchange: str = ""
    datetime: Optional[datetime] = None

    # Timeframe
    interval: str = ""  # 1m, 5m, 15m, 1h, 4h, 1d, etc.

    # OHLCV data
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    close_price: float = 0.0
    volume: float = 0.0
    turnover: float = 0.0        # Not always available
    open_interest: float = 0.0    # For futures

    def __repr__(self):
        return f"KlineData({self.symbol}, {self.interval}, {self.close_price}, {self.datetime})"

    def to_ohlcv_list(self) -> list:
        """
        Convert to CCXT OHLCV format

        Returns:
            [timestamp_ms, open, high, low, close, volume]
        """
        if self.datetime:
            timestamp = int(self.datetime.timestamp() * 1000)
        else:
            timestamp = 0

        return [
            timestamp,
            self.open_price,
            self.high_price,
            self.low_price,
            self.close_price,
            self.volume
        ]

    @classmethod
    def from_ohlcv_list(cls, ohlcv: list, symbol: str = "", interval: str = "") -> "KlineData":
        """
        Create from CCXT OHLCV list

        Args:
            ohlcv: [timestamp_ms, open, high, low, close, volume]
            symbol: Trading pair symbol
            interval: Timeframe

        Returns:
            KlineData object
        """
        from datetime import timezone

        return cls(
            symbol=symbol,
            interval=interval,
            datetime=datetime.fromtimestamp(ohlcv[0] / 1000, tz=timezone.utc),
            open_price=float(ohlcv[1]),
            high_price=float(ohlcv[2]),
            low_price=float(ohlcv[3]),
            close_price=float(ohlcv[4]),
            volume=float(ohlcv[5])
        )
