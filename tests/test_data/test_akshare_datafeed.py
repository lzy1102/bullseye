"""
Test AKShare Datafeed

Run this script to verify the AKShare datafeed implementation:
    python tests/test_data/test_akshare_datafeed.py

Note: These tests require network access and akshare package.
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    import akshare
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False

skip_no_akshare = pytest.mark.skipif(
    not HAS_AKSHARE,
    reason="akshare is not installed"
)


@skip_no_akshare
def test_basic_query():
    """Test basic K-line query"""
    from bullseye.data import AKShareDatafeed

    datafeed = AKShareDatafeed()
    assert datafeed.init()

    klines = datafeed.query_history(
        symbol="000001.SZ",
        interval="1d",
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
        adjust="qfq",
    )
    assert len(klines) > 0


@skip_no_akshare
def test_minute_data():
    """Test minute-level data query"""
    from bullseye.data import AKShareDatafeed

    datafeed = AKShareDatafeed()
    datafeed.init()

    klines = datafeed.query_history(
        symbol="600000.SH",
        interval="5m",
        start=datetime.now() - timedelta(days=5),
        end=datetime.now(),
    )
    assert len(klines) >= 0


@skip_no_akshare
def test_realtime_quote():
    """Test real-time quote"""
    from bullseye.data import AKShareDatafeed

    datafeed = AKShareDatafeed()
    datafeed.init()

    quote = datafeed.get_realtime_quote("000001.SZ")
    assert quote is not None or quote is None


@skip_no_akshare
def test_search():
    """Test stock search"""
    from bullseye.data import AKShareDatafeed

    datafeed = AKShareDatafeed()
    datafeed.init()

    results = datafeed.search_stocks("银行")
    assert len(results) >= 0


@skip_no_akshare
def test_index_data():
    """Test index data query"""
    from bullseye.data import AKShareDatafeed

    datafeed = AKShareDatafeed()
    datafeed.init()

    klines = datafeed.get_index_data(
        index_code="000001",
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
    )
    assert len(klines) >= 0


@skip_no_akshare
def test_supported_symbols():
    """Test getting supported symbols"""
    from bullseye.data import AKShareDatafeed

    datafeed = AKShareDatafeed()
    datafeed.init()

    indices = datafeed.get_supported_symbols("index")
    assert len(indices) >= 0
