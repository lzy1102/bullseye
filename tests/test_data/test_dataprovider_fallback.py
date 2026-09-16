"""
Test DataProvider fallback datafeed (gateways without historical bars).
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from bullseye.configuration.config import Config
from bullseye.data.dataprovider import DataProvider
from bullseye.trader.object import KlineData


class NoBarsGateway:
    """Gateway without historical bars (e.g. order-bridge / CTP)."""

    def get_bars(self, **kwargs):
        return []


class StubDatafeed:
    def __init__(self, bars=3):
        self._bars = bars

    def query_history(self, symbol, interval, limit=None, **kwargs):
        start = datetime(2024, 1, 1)
        return [
            KlineData(
                symbol=symbol,
                interval=interval,
                datetime=start + timedelta(days=i),
                open_price=10.0 + i,
                high_price=11.0 + i,
                low_price=9.0 + i,
                close_price=10.5 + i,
                volume=1000.0,
            )
            for i in range(self._bars)
        ]


def make_config(**entries) -> Config:
    config = Config()
    for key, value in entries.items():
        config.set(key, value)
    return config


class TestFallbackCreation:
    def test_no_datafeed_configured(self):
        assert DataProvider._create_fallback_datafeed(make_config()) is None

    def test_unknown_datafeed_degrades_gracefully(self):
        config = make_config(market_type="custom", custom={"datafeed": "nonexistent"})
        assert DataProvider._create_fallback_datafeed(config) is None

    def test_market_section_takes_precedence(self):
        # Top-level absent, custom section present -> attempted
        config = make_config(market_type="custom", custom={"datafeed": "nonexistent"})
        assert DataProvider._create_fallback_datafeed(config) is None  # tried & failed


class TestFallbackQuery:
    def test_used_when_gateway_returns_nothing(self):
        config = make_config()
        dp = DataProvider(config, gateway=NoBarsGateway())
        dp._datafeed = StubDatafeed(bars=3)

        df = dp.historic_ohlcv("000001.SZ", "1d")

        assert len(df) == 3
        assert list(df.columns[:6]) == ["date", "open", "high", "low", "close", "volume"]
        assert df["close"].iloc[-1] == pytest.approx(12.5)

    def test_empty_when_no_fallback_either(self):
        config = make_config()
        dp = DataProvider(config, gateway=NoBarsGateway())

        df = dp.historic_ohlcv("000001.SZ", "1d")

        assert df.empty
