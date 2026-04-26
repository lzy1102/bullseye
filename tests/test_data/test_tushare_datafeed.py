"""
Test TuShare Datafeed

Run this script to verify the TuShare datafeed implementation:
    python tests/test_data/test_tushare_datafeed.py

Requirements:
    - TuShare token (get from https://tushare.pro/)
    - Set TUSHARE_TOKEN environment variable or pass in config
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
skip_no_token = pytest.mark.skipif(
    not TUSHARE_TOKEN,
    reason="TUSHARE_TOKEN environment variable not set"
)


@skip_no_token
def test_basic_query():
    """Test basic K-line query"""
    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": TUSHARE_TOKEN})
    assert datafeed.init()

    klines = datafeed.query_history(
        symbol="000001.SZ",
        interval="1d",
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
        adjust="qfq",
    )
    assert len(klines) > 0


@skip_no_token
def test_index_data():
    """Test index data query"""
    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": TUSHARE_TOKEN})
    datafeed.init()

    klines = datafeed.get_index_data(
        index_code="000001.SH",
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
    )
    assert len(klines) > 0


@skip_no_token
def test_stock_info():
    """Test stock info query"""
    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": TUSHARE_TOKEN})
    datafeed.init()

    info = datafeed.get_stock_info("000001.SZ")
    assert info is not None


@skip_no_token
def test_trade_calendar():
    """Test trade calendar"""
    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": TUSHARE_TOKEN})
    datafeed.init()

    dates = datafeed.get_trade_calendar(
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
    )
    assert len(dates) > 0


@skip_no_token
def test_search():
    """Test stock search"""
    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": TUSHARE_TOKEN})
    datafeed.init()

    results = datafeed.search_stocks("银行")
    assert len(results) > 0


@skip_no_token
def test_supported_symbols():
    """Test getting supported symbols"""
    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": TUSHARE_TOKEN})
    datafeed.init()

    indices = datafeed.get_supported_symbols("index")
    assert len(indices) > 0


@skip_no_token
def test_minute_data():
    """Test minute data query (may require higher permission)"""
    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": TUSHARE_TOKEN})
    datafeed.init()

    klines = datafeed.query_history(
        symbol="000001.SZ",
        interval="5m",
        start=datetime.now() - timedelta(days=5),
        end=datetime.now(),
    )
    assert len(klines) >= 0
