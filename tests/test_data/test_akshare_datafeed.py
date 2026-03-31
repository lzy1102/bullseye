"""
Test AKShare Datafeed

Run this script to verify the AKShare datafeed implementation:
    python tests/test_data/test_akshare_datafeed.py
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def test_basic_query():
    """Test basic K-line query"""
    print("=" * 60)
    print("Test 1: Basic K-line Query")
    print("=" * 60)

    from bullseye.data import AKShareDatafeed

    datafeed = AKShareDatafeed()
    datafeed.init()

    # Query daily data for 平安银行
    print("\nQuerying daily data for 000001.SZ (平安银行)...")
    klines = datafeed.query_history(
        symbol="000001.SZ",
        interval="1d",
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
        adjust="qfq",
    )

    print(f"Total candles: {len(klines)}")
    if klines:
        print(f"First candle: {klines[0]}")
        print(f"Last candle: {klines[-1]}")

    return len(klines) > 0


def test_minute_data():
    """Test minute-level data query"""
    print("\n" + "=" * 60)
    print("Test 2: Minute Data Query")
    print("=" * 60)

    from bullseye.data import AKShareDatafeed

    datafeed = AKShareDatafeed()
    datafeed.init()

    # Query 5-minute data for the last 5 days
    print("\nQuerying 5-minute data for 600000.SH (浦发银行)...")
    klines = datafeed.query_history(
        symbol="600000.SH",
        interval="5m",
        start=datetime.now() - timedelta(days=5),
        end=datetime.now(),
    )

    print(f"Total candles: {len(klines)}")
    if klines:
        print(f"First candle: {klines[0]}")
        print(f"Last candle: {klines[-1]}")

    return len(klines) > 0


def test_realtime_quote():
    """Test real-time quote"""
    print("\n" + "=" * 60)
    print("Test 3: Real-time Quote")
    print("=" * 60)

    from bullseye.data import AKShareDatafeed

    datafeed = AKShareDatafeed()
    datafeed.init()

    # Get real-time quote
    print("\nGetting real-time quote for 000001 (平安银行)...")
    quote = datafeed.get_realtime_quote("000001.SZ")

    if quote:
        print(f"Name: {quote.get('name')}")
        print(f"Price: {quote.get('price')}")
        print(f"Change: {quote.get('change_pct')}%")
        print(f"Volume: {quote.get('volume')}")
        print(f"Turnover: {quote.get('turnover')}")
    else:
        print("No quote data (market may be closed)")

    return quote is not None


def test_search():
    """Test stock search"""
    print("\n" + "=" * 60)
    print("Test 4: Stock Search")
    print("=" * 60)

    from bullseye.data import AKShareDatafeed

    datafeed = AKShareDatafeed()
    datafeed.init()

    # Search for banks
    print("\nSearching for '银行'...")
    results = datafeed.search_stocks("银行")

    print(f"Found {len(results)} results:")
    for stock in results[:10]:
        print(f"  {stock['symbol']} - {stock['name']}")

    return len(results) > 0


def test_index_data():
    """Test index data query"""
    print("\n" + "=" * 60)
    print("Test 5: Index Data Query")
    print("=" * 60)

    from bullseye.data import AKShareDatafeed

    datafeed = AKShareDatafeed()
    datafeed.init()

    # Query Shanghai Composite Index
    print("\nQuerying 上证指数 (000001)...")
    klines = datafeed.get_index_data(
        index_code="000001",
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
    )

    print(f"Total candles: {len(klines)}")
    if klines:
        print(f"First candle: {klines[0]}")
        print(f"Last candle: {klines[-1]}")

    return len(klines) > 0


def test_supported_symbols():
    """Test getting supported symbols"""
    print("\n" + "=" * 60)
    print("Test 6: Supported Symbols")
    print("=" * 60)

    from bullseye.data import AKShareDatafeed

    datafeed = AKShareDatafeed()
    datafeed.init()

    # Get index list
    print("\nSupported indices:")
    indices = datafeed.get_supported_symbols("index")
    for idx in indices:
        print(f"  {idx}")

    return len(indices) > 0


def main():
    """Run all tests"""
    print("AKShare Datafeed Test Suite")
    print("=" * 60)

    tests = [
        ("Basic Query", test_basic_query),
        ("Minute Data", test_minute_data),
        ("Real-time Quote", test_realtime_quote),
        ("Stock Search", test_search),
        ("Index Data", test_index_data),
        ("Supported Symbols", test_supported_symbols),
    ]

    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, "PASS" if success else "FAIL"))
        except Exception as e:
            print(f"\nError in {name}: {e}")
            results.append((name, "ERROR"))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for name, status in results:
        print(f"  {name}: {status}")

    passed = sum(1 for _, s in results if s == "PASS")
    print(f"\nTotal: {passed}/{len(tests)} passed")


if __name__ == "__main__":
    main()
