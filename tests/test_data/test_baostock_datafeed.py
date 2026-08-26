"""
Test BaoStock Datafeed

Offline unit tests (symbol conversion, row parsing, registry) always run.
Network integration tests are skipped when baostock is not installed.
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    import baostock  # noqa: F401
    HAS_BAOSTOCK = True
except ImportError:
    HAS_BAOSTOCK = False

import os

_skip_network = not HAS_BAOSTOCK or os.environ.get("SKIP_NETWORK_TESTS") == "1"


from bullseye.data.datafeed.baostock_datafeed import BaoStockDatafeed
from bullseye.data.datafeed import get_datafeed


class TestBaoStockOffline:
    """Tests that do not require network or the baostock package."""

    def test_registry_contains_baostock(self):
        datafeed = get_datafeed("baostock")
        assert isinstance(datafeed, BaoStockDatafeed)
        assert datafeed.name == "baostock"

    def test_supported_intervals(self):
        datafeed = BaoStockDatafeed()
        intervals = datafeed.get_supported_intervals()
        assert "1d" in intervals
        assert "5m" in intervals and "1h" in intervals
        assert "2h" not in intervals

    def test_symbol_conversion(self):
        assert BaoStockDatafeed._to_baostock_code("000001", "SZ") == "sz.000001"
        assert BaoStockDatafeed._to_baostock_code("600000", "SH") == "sh.600000"

    def test_symbol_conversion_rejects_bj(self):
        with pytest.raises(ValueError, match="Beijing"):
            BaoStockDatafeed._to_baostock_code("430047", "BJ")

    def test_unsupported_interval_returns_empty(self):
        datafeed = BaoStockDatafeed()
        # Not initialized: query path short-circuits on interval check first
        assert datafeed.query_history(symbol="000001.SZ", interval="2h") == []

    def test_row_to_kline_daily(self):
        datafeed = BaoStockDatafeed()
        row = ["2024-01-04", "sz.000001", "10.00", "10.50", "9.80", "10.20",
               "12345678", "98765432.10"]
        kline = datafeed._row_to_kline(row, "000001.SZ", "1d", "d")

        assert kline is not None
        assert kline.datetime == datetime(2024, 1, 4)
        assert kline.open_price == pytest.approx(10.00)
        assert kline.high_price == pytest.approx(10.50)
        assert kline.low_price == pytest.approx(9.80)
        assert kline.close_price == pytest.approx(10.20)
        assert kline.volume == pytest.approx(12345678)

    def test_row_to_kline_minute(self):
        datafeed = BaoStockDatafeed()
        row = ["20240104093500000", "sz.000001", "10.00", "10.50", "9.80", "10.20",
               "12345678", "98765432.10"]
        kline = datafeed._row_to_kline(row, "000001.SZ", "5m", "5")

        assert kline is not None
        assert kline.datetime == datetime(2024, 1, 4, 9, 35)
        assert kline.interval == "5m"

    @pytest.mark.parametrize(
        "row",
        [
            ["garbage-date", "sz.000001", "", "", "", "", "", ""],   # unparsable date
            ["2024-01-04"],                                          # truncated row
        ],
    )
    def test_row_to_kline_skips_bad_rows(self, row):
        datafeed = BaoStockDatafeed()
        assert datafeed._row_to_kline(row, "000001.SZ", "1d", "d") is None


@pytest.mark.skipif(_skip_network, reason="baostock not installed or network tests disabled")
class TestBaoStockIntegration:
    """Live tests against the real BaoStock service (network required)."""

    def test_login_and_daily_query(self):
        datafeed = BaoStockDatafeed()
        try:
            assert datafeed.init()
            klines = datafeed.query_history(
                symbol="000001.SZ",
                interval="1d",
                start=datetime(2024, 1, 2),
                end=datetime(2024, 1, 31),
                adjust="qfq",
            )
            assert len(klines) > 0
            assert klines[0].datetime <= klines[-1].datetime
            assert all(k.close_price > 0 for k in klines)
        finally:
            datafeed.close()

    def test_query_before_init_lazy_connects(self):
        datafeed = BaoStockDatafeed()
        try:
            klines = datafeed.query_history(
                symbol="600000.SH",
                interval="1d",
                start=datetime(2024, 1, 2),
                end=datetime(2024, 1, 10),
            )
            assert len(klines) > 0
        finally:
            datafeed.close()
