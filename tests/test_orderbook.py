"""
Tests for the order book snapshot feature.

Covers:
- OrderBookData data object and computed properties
- EVENT_ORDERBOOK event type
- BaseGateway.get_order_book / on_orderbook
- CcxtGateway.get_order_book with mocked CCXT
- DryRunGateway.get_order_book delegation
- DataProvider.orderbook() caching behaviour
"""
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# Project root on path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Mock heavy/optional dependencies so we can import bullseye submodules
# without installing sqlalchemy, ccxt, etc.
for mod_name in (
    "sqlalchemy", "sqlalchemy.orm", "sqlalchemy.ext", "sqlalchemy.ext.declarative",
    "ccxt", "ccxt.async_support",
):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()


# ---------------------------------------------------------------------------
# 1. OrderBookData
# ---------------------------------------------------------------------------

class TestOrderBookData:
    """Unit tests for the OrderBookData dataclass and its properties."""

    def _make(self, bids=None, asks=None, **kwargs):
        from bullseye.trader.object.orderbook import OrderBookData
        return OrderBookData(
            bids=bids or [],
            asks=asks or [],
            gateway_name="TEST",
            symbol="BTC/USDT",
            exchange="binance",
            datetime=datetime(2026, 1, 1, 12, 0, 0),
            **kwargs,
        )

    # -- basic construction ------------------------------------------------

    def test_default_empty(self):
        ob = self._make()
        assert ob.bids == []
        assert ob.asks == []
        assert ob.symbol == "BTC/USDT"

    def test_repr(self):
        ob = self._make(bids=[[100, 1]], asks=[[101, 2]])
        r = repr(ob)
        assert "BTC/USDT" in r
        assert "bids=1" in r
        assert "asks=1" in r

    # -- best bid / best ask ------------------------------------------------

    def test_best_bid_price(self):
        ob = self._make(bids=[[50000, 1.5], [49999, 2.0]])
        assert ob.best_bid_price == 50000.0

    def test_best_ask_price(self):
        ob = self._make(asks=[[50001, 1.0], [50002, 0.5]])
        assert ob.best_ask_price == 50001.0

    def test_best_prices_empty(self):
        ob = self._make()
        assert ob.best_bid_price == 0.0
        assert ob.best_ask_price == 0.0

    # -- spread -------------------------------------------------------------

    def test_spread(self):
        ob = self._make(bids=[[50000, 1]], asks=[[50001, 1]])
        assert ob.spread == pytest.approx(1.0)

    def test_spread_empty(self):
        ob = self._make()
        assert ob.spread == 0.0

    # -- mid_price ----------------------------------------------------------

    def test_mid_price(self):
        ob = self._make(bids=[[100, 1]], asks=[[102, 1]])
        assert ob.mid_price == pytest.approx(101.0)

    def test_mid_price_empty(self):
        ob = self._make()
        assert ob.mid_price == 0.0

    def test_mid_price_one_side_missing(self):
        ob = self._make(bids=[[100, 1]], asks=[])
        assert ob.mid_price == 0.0

    # -- volume totals ------------------------------------------------------

    def test_bid_volume_total(self):
        ob = self._make(bids=[[100, 1.5], [99, 2.5]])
        assert ob.bid_volume_total == pytest.approx(4.0)

    def test_ask_volume_total(self):
        ob = self._make(asks=[[101, 3], [102, 4]])
        assert ob.ask_volume_total == pytest.approx(7.0)

    def test_volume_totals_empty(self):
        ob = self._make()
        assert ob.bid_volume_total == 0.0
        assert ob.ask_volume_total == 0.0

    # -- imbalance ----------------------------------------------------------

    def test_imbalance_positive(self):
        """Bid-heavy => positive."""
        ob = self._make(bids=[[100, 3]], asks=[[101, 1]])
        assert ob.imbalance == pytest.approx(0.5)

    def test_imbalance_negative(self):
        """Ask-heavy => negative."""
        ob = self._make(bids=[[100, 1]], asks=[[101, 3]])
        assert ob.imbalance == pytest.approx(-0.5)

    def test_imbalance_balanced(self):
        ob = self._make(bids=[[100, 5]], asks=[[101, 5]])
        assert ob.imbalance == pytest.approx(0.0)

    def test_imbalance_full_bid(self):
        ob = self._make(bids=[[100, 10]], asks=[])
        assert ob.imbalance == pytest.approx(1.0)

    def test_imbalance_full_ask(self):
        ob = self._make(bids=[], asks=[[101, 10]])
        assert ob.imbalance == pytest.approx(-1.0)

    def test_imbalance_empty_book(self):
        ob = self._make()
        assert ob.imbalance == 0.0

    # -- integration-style sanity -------------------------------------------

    def test_realistic_btc_orderbook(self):
        bids = [
            [50000.0, 1.200], [49999.5, 0.800], [49999.0, 2.100],
            [49998.5, 0.500], [49998.0, 3.000],
        ]
        asks = [
            [50000.5, 0.900], [50001.0, 1.500], [50001.5, 0.600],
            [50002.0, 2.200], [50002.5, 1.100],
        ]
        ob = self._make(bids=bids, asks=asks)

        assert ob.best_bid_price == 50000.0
        assert ob.best_ask_price == 50000.5
        assert ob.spread == pytest.approx(0.5)
        assert ob.mid_price == pytest.approx(50000.25)
        assert ob.bid_volume_total == pytest.approx(7.6)
        assert ob.ask_volume_total == pytest.approx(6.3)
        assert ob.imbalance == pytest.approx(
            (7.6 - 6.3) / (7.6 + 6.3), abs=1e-6
        )


# ---------------------------------------------------------------------------
# 2. EVENT_ORDERBOOK
# ---------------------------------------------------------------------------

class TestEventOrderBookEvent:
    """Verify EVENT_ORDERBOOK exists in the EventType enum."""

    def test_event_type_exists(self):
        from bullseye.trader.eventengine import EventType
        assert hasattr(EventType, "EVENT_ORDERBOOK")

    def test_event_type_value(self):
        from bullseye.trader.eventengine import EventType
        assert EventType.EVENT_ORDERBOOK.value == "eOrderBook"


# ---------------------------------------------------------------------------
# 3. BaseGateway optional methods
# ---------------------------------------------------------------------------

class TestBaseGatewayOrderBook:
    """BaseGateway.get_order_book and on_orderbook tests."""

    def test_get_order_book_default_none(self):
        from bullseye.trader.eventengine import EventEngine
        from bullseye.gateway.base import BaseGateway

        # BaseGateway is abstract, create a minimal concrete subclass
        class StubGateway(BaseGateway):
            def connect(self, **kwargs): pass
            def close(self): pass
            def send_order(self, req): return ""
            def cancel_order(self, req): return False
            def query_account(self): return None
            def query_position(self): return []
            def query_order(self, req): return None
            def query_contract(self): return []

        gw = StubGateway(EventEngine())
        assert gw.get_order_book("BTC/USDT") is None

    def test_on_orderbook_publishes_event(self):
        from bullseye.trader.eventengine import EventEngine, EventType
        from bullseye.trader.object.orderbook import OrderBookData
        from bullseye.gateway.base import BaseGateway

        class StubGateway(BaseGateway):
            def connect(self, **kwargs): pass
            def close(self): pass
            def send_order(self, req): return ""
            def cancel_order(self, req): return False
            def query_account(self): return None
            def query_position(self): return []
            def query_order(self, req): return None
            def query_contract(self): return []

        gw = StubGateway(EventEngine(), "TEST_GW")
        ob = OrderBookData(symbol="ETH/USDT", bids=[[3000, 1]], asks=[[3001, 1]])

        # Capture published events
        published = []
        gw.event_engine.put = lambda event: published.append(event)

        gw.on_orderbook(ob)

        assert len(published) == 1
        assert published[0].type == EventType.EVENT_ORDERBOOK
        assert published[0].data is ob
        assert published[0].data.gateway_name == "TEST_GW"


# ---------------------------------------------------------------------------
# 4. CcxtGateway.get_order_book
# ---------------------------------------------------------------------------

class TestCcxtGatewayOrderBook:
    """CcxtGateway.get_order_book with mocked CCXT exchange."""

    def _make_gateway(self):
        from bullseye.trader.eventengine import EventEngine
        from bullseye.gateway.crypto.ccxt_gateway import CcxtGateway

        gw = CcxtGateway(EventEngine(), "binance")
        # Stub the exchange object
        gw._exchange = MagicMock()
        gw._connected = True
        return gw

    def test_normal_response(self):
        gw = self._make_gateway()
        gw._exchange.fetch_order_book.return_value = {
            "bids": [[50000.0, "1.5"], [49999.0, "2.0"]],
            "asks": [[50001.0, "1.0"], [50002.0, "0.5"]],
        }

        ob = gw.get_order_book("BTC/USDT", limit=10)

        gw._exchange.fetch_order_book.assert_called_once_with("BTC/USDT", 10)
        assert ob is not None
        assert ob.symbol == "BTC/USDT"
        assert ob.exchange == "binance"
        assert ob.bids == [[50000.0, 1.5], [49999.0, 2.0]]
        assert ob.asks == [[50001.0, 1.0], [50002.0, 0.5]]
        assert ob.best_bid_price == 50000.0
        assert ob.best_ask_price == 50001.0
        assert ob.spread == pytest.approx(1.0)
        assert ob.bid_volume_total == pytest.approx(3.5)
        assert ob.ask_volume_total == pytest.approx(1.5)

    def test_empty_response(self):
        gw = self._make_gateway()
        gw._exchange.fetch_order_book.return_value = {"bids": [], "asks": []}

        ob = gw.get_order_book("BTC/USDT")

        assert ob is not None
        assert ob.bids == []
        assert ob.asks == []
        assert ob.best_bid_price == 0.0

    def test_exception_returns_none(self):
        gw = self._make_gateway()
        gw._exchange.fetch_order_book.side_effect = Exception("network error")

        ob = gw.get_order_book("BTC/USDT")

        assert ob is None

    def test_string_numeric_values(self):
        """CCXT sometimes returns numeric values as strings."""
        gw = self._make_gateway()
        gw._exchange.fetch_order_book.return_value = {
            "bids": [["50000", "1.5"]],
            "asks": [["50001", "0.5"]],
        }

        ob = gw.get_order_book("BTC/USDT")

        assert ob is not None
        assert ob.bids == [[50000.0, 1.5]]
        assert ob.asks == [[50001.0, 0.5]]


# ---------------------------------------------------------------------------
# 5. DryRunGateway.get_order_book
# ---------------------------------------------------------------------------

class TestDryRunGatewayOrderBook:
    """DryRunGateway delegates order book to real gateway."""

    def _make_dryrun(self, real_gateway=None):
        from bullseye.trader.eventengine import EventEngine
        from bullseye.gateway.dryrun.dryrun_gateway import DryRunGateway
        return DryRunGateway(EventEngine(), real_gateway=real_gateway)

    def test_delegates_to_real_gateway(self):
        from bullseye.trader.object.orderbook import OrderBookData

        real = MagicMock()
        expected = OrderBookData(
            symbol="BTC/USDT",
            bids=[[50000, 1]],
            asks=[[50001, 1]],
        )
        real.get_order_book.return_value = expected

        gw = self._make_dryrun(real)
        result = gw.get_order_book("BTC/USDT", limit=5)

        real.get_order_book.assert_called_once_with("BTC/USDT", 5)
        assert result is expected

    def test_no_real_gateway_returns_none(self):
        gw = self._make_dryrun(real_gateway=None)
        assert gw.get_order_book("BTC/USDT") is None


# ---------------------------------------------------------------------------
# 6. DataProvider.orderbook()
# ---------------------------------------------------------------------------

class TestDataProviderOrderBook:
    """DataProvider.orderbook() with caching tests."""

    def _make_dp(self, gateway=None):
        from unittest.mock import MagicMock
        from bullseye.data.dataprovider import DataProvider

        config = MagicMock()
        config.dry_run = True

        gw = gateway or MagicMock()
        dp = DataProvider(config=config, gateway=gw, pairlist=["BTC/USDT"])
        return dp

    def test_returns_orderbook_from_gateway(self):
        from bullseye.trader.object.orderbook import OrderBookData

        expected = OrderBookData(
            symbol="BTC/USDT",
            bids=[[50000, 1]],
            asks=[[50001, 1]],
        )
        gw = MagicMock()
        gw.get_order_book.return_value = expected

        dp = self._make_dp(gw)
        result = dp.orderbook("BTC/USDT", limit=5)

        gw.get_order_book.assert_called_once_with("BTC/USDT", 5)
        assert result is expected

    def test_caches_result(self):
        from bullseye.trader.object.orderbook import OrderBookData

        expected = OrderBookData(symbol="BTC/USDT", bids=[[50000, 1]], asks=[[50001, 1]])
        gw = MagicMock()
        gw.get_order_book.return_value = expected

        dp = self._make_dp(gw)
        ob1 = dp.orderbook("BTC/USDT")
        ob2 = dp.orderbook("BTC/USDT")

        # Gateway called only once (second call uses cache)
        assert gw.get_order_book.call_count == 1
        assert ob1 is ob2

    def test_cache_timeout_forces_refresh(self):
        from bullseye.trader.object.orderbook import OrderBookData

        ob_first = OrderBookData(symbol="BTC/USDT", bids=[[50000, 1]], asks=[[50001, 1]])
        ob_second = OrderBookData(symbol="BTC/USDT", bids=[[49999, 2]], asks=[[50002, 2]])

        gw = MagicMock()
        gw.get_order_book.side_effect = [ob_first, ob_second]

        dp = self._make_dp(gw)
        ob1 = dp.orderbook("BTC/USDT", cache_timeout=0)
        ob2 = dp.orderbook("BTC/USDT", cache_timeout=0)

        assert gw.get_order_book.call_count == 2
        assert ob1 is ob_first
        assert ob2 is ob_second

    def test_gateway_returns_none(self):
        gw = MagicMock()
        gw.get_order_book.return_value = None

        dp = self._make_dp(gw)
        result = dp.orderbook("BTC/USDT")

        assert result is None

    def test_gateway_raises_exception(self):
        gw = MagicMock()
        gw.get_order_book.side_effect = RuntimeError("connection refused")

        dp = self._make_dp(gw)
        result = dp.orderbook("BTC/USDT")

        assert result is None

    def test_default_cache_timeout(self):
        """Default cache timeout is 5 seconds."""
        dp = self._make_dp()
        assert dp._orderbook_cache_timeout == 5

    def test_different_pairs_cached_separately(self):
        from bullseye.trader.object.orderbook import OrderBookData

        btc_ob = OrderBookData(symbol="BTC/USDT", bids=[[50000, 1]], asks=[[50001, 1]])
        eth_ob = OrderBookData(symbol="ETH/USDT", bids=[[3000, 1]], asks=[[3001, 1]])

        gw = MagicMock()
        gw.get_order_book.side_effect = [btc_ob, eth_ob]

        dp = self._make_dp(gw)
        r1 = dp.orderbook("BTC/USDT")
        r2 = dp.orderbook("ETH/USDT")

        assert gw.get_order_book.call_count == 2
        assert r1.symbol == "BTC/USDT"
        assert r2.symbol == "ETH/USDT"

    def test_clear_cache_all_clears_orderbook(self):
        from bullseye.trader.object.orderbook import OrderBookData

        ob = OrderBookData(symbol="BTC/USDT", bids=[[50000, 1]], asks=[[50001, 1]])
        gw = MagicMock()
        gw.get_order_book.return_value = ob

        dp = self._make_dp(gw)
        dp.orderbook("BTC/USDT")
        assert "BTC/USDT" in dp._orderbook_cache

        dp.clear_cache()
        assert len(dp._orderbook_cache) == 0

    def test_clear_cache_pair_clears_orderbook(self):
        from bullseye.trader.object.orderbook import OrderBookData

        btc_ob = OrderBookData(symbol="BTC/USDT", bids=[[50000, 1]], asks=[[50001, 1]])
        eth_ob = OrderBookData(symbol="ETH/USDT", bids=[[3000, 1]], asks=[[3001, 1]])
        gw = MagicMock()
        gw.get_order_book.side_effect = [btc_ob, eth_ob]

        dp = self._make_dp(gw)
        dp.orderbook("BTC/USDT")
        dp.orderbook("ETH/USDT")

        dp.clear_cache(pair="BTC/USDT")
        assert "BTC/USDT" not in dp._orderbook_cache
        assert "ETH/USDT" in dp._orderbook_cache

        # After clear, next call fetches from gateway again
        gw.get_order_book.side_effect = [OrderBookData(symbol="BTC/USDT", bids=[[50001, 1]], asks=[[50002, 1]])]
        dp.orderbook("BTC/USDT")
        assert gw.get_order_book.call_count == 3
