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

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def get_token():
    """Get TuShare token from environment or user input"""
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        print("TuShare token not found in environment.")
        print("Get your token from https://tushare.pro/")
        token = input("Enter your TuShare token (or press Enter to skip): ").strip()
        if not token:
            print("No token provided, skipping TuShare tests.")
            return None
    return token


def test_basic_query(token):
    """Test basic K-line query"""
    print("=" * 60)
    print("Test 1: Basic K-line Query")
    print("=" * 60)

    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": token})
    if not datafeed.init():
        print("Failed to initialize TuShare")
        return False

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
        return True
    return False


def test_index_data(token):
    """Test index data query"""
    print("\n" + "=" * 60)
    print("Test 2: Index Data Query")
    print("=" * 60)

    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": token})
    datafeed.init()

    # Query Shanghai Composite Index
    print("\nQuerying 上证指数 (000001.SH)...")
    klines = datafeed.get_index_data(
        index_code="000001.SH",
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
    )

    print(f"Total candles: {len(klines)}")
    if klines:
        print(f"First candle: {klines[0]}")
        print(f"Last candle: {klines[-1]}")
        return True
    return False


def test_stock_info(token):
    """Test stock info query"""
    print("\n" + "=" * 60)
    print("Test 3: Stock Info Query")
    print("=" * 60)

    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": token})
    datafeed.init()

    print("\nGetting stock info for 000001.SZ...")
    info = datafeed.get_stock_info("000001.SZ")

    if info:
        print(f"Code: {info.get('code')}")
        print(f"Name: {info.get('name')}")
        print(f"Industry: {info.get('industry')}")
        print(f"Market: {info.get('market')}")
        print(f"List Date: {info.get('list_date')}")
        return True
    return False


def test_trade_calendar(token):
    """Test trade calendar"""
    print("\n" + "=" * 60)
    print("Test 4: Trade Calendar")
    print("=" * 60)

    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": token})
    datafeed.init()

    print("\nGetting trade calendar for 2024...")
    dates = datafeed.get_trade_calendar(
        start=datetime(2024, 1, 1),
        end=datetime(2024, 12, 31),
    )

    print(f"Total trading days: {len(dates)}")
    if dates:
        print(f"First trading day: {dates[0]}")
        print(f"Last trading day: {dates[-1]}")
        return True
    return False


def test_search(token):
    """Test stock search"""
    print("\n" + "=" * 60)
    print("Test 5: Stock Search")
    print("=" * 60)

    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": token})
    datafeed.init()

    print("\nSearching for '银行'...")
    results = datafeed.search_stocks("银行")

    print(f"Found {len(results)} results:")
    for stock in results[:10]:
        print(f"  {stock['symbol']} - {stock['name']} ({stock.get('industry', '')})")

    return len(results) > 0


def test_supported_symbols(token):
    """Test getting supported symbols"""
    print("\n" + "=" * 60)
    print("Test 6: Supported Symbols")
    print("=" * 60)

    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": token})
    datafeed.init()

    print("\nGetting index list...")
    indices = datafeed.get_supported_symbols("index")
    print(f"Total indices: {len(indices)}")
    if indices:
        print(f"Sample: {indices[:5]}")

    return len(indices) > 0


def test_minute_data(token):
    """Test minute data query (may require higher permission)"""
    print("\n" + "=" * 60)
    print("Test 7: Minute Data Query (requires permission)")
    print("=" * 60)

    from bullseye.data import TuShareDatafeed

    datafeed = TuShareDatafeed({"token": token})
    datafeed.init()

    print("\nQuerying 5-minute data for 000001.SZ...")
    klines = datafeed.query_history(
        symbol="000001.SZ",
        interval="5m",
        start=datetime.now() - timedelta(days=5),
        end=datetime.now(),
    )

    print(f"Total candles: {len(klines)}")
    if klines:
        print(f"First candle: {klines[0]}")
        print(f"Last candle: {klines[-1]}")
        return True
    else:
        print("Minute data may require higher TuShare permission level")
        return False


def main():
    """Run all tests"""
    print("TuShare Datafeed Test Suite")
    print("=" * 60)

    # Get token
    token = get_token()
    if not token:
        print("\nNo token available. Skipping tests.")
        return

    tests = [
        ("Basic Query", lambda: test_basic_query(token)),
        ("Index Data", lambda: test_index_data(token)),
        ("Stock Info", lambda: test_stock_info(token)),
        ("Trade Calendar", lambda: test_trade_calendar(token)),
        ("Stock Search", lambda: test_search(token)),
        ("Supported Symbols", lambda: test_supported_symbols(token)),
        ("Minute Data", lambda: test_minute_data(token)),
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
