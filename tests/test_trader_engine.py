"""
Unit tests for the MainEngine (trader engine) gateway management and event caching.
"""
import time

import pytest

from bullseye.trader.engine import MainEngine
from bullseye.trader.eventengine import EventEngine, Event, EventType
from bullseye.trader.object import AccountData, TickData


class FakeGateway:
    """Minimal in-memory gateway for exercising MainEngine flows."""

    def __init__(self, event_engine: EventEngine):
        self.event_engine = event_engine
        self.connected = False
        self.closed = False
        self.sent_orders = []
        self.cancelled_orders = []
        self.fail_send = False

    def connect(self, **setting):
        self.connected = True
        self.setting = setting

    def close(self):
        self.closed = True

    def send_order(self, req):
        if self.fail_send:
            raise RuntimeError("send failed")
        self.sent_orders.append(req)
        return f"ORDER_{len(self.sent_orders)}"

    def cancel_order(self, req):
        self.cancelled_orders.append(req)
        return True


@pytest.fixture
def engine():
    eng = MainEngine()
    yield eng
    eng.stop()


@pytest.fixture
def connected_engine(engine):
    engine.add_gateway_class(FakeGateway, "fake")
    engine.connect("fake", {"account": "test"})
    return engine


def wait_until(predicate, timeout=2.0, interval=0.01) -> bool:
    """Poll until predicate is true (event engine is asynchronous)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class TestGatewayRegistry:
    def test_add_gateway_class(self, engine):
        engine.add_gateway_class(FakeGateway, "fake")
        assert "fake" not in engine.gateways  # registered, not yet connected

    def test_connect_unknown_gateway_fails(self, engine):
        assert engine.connect("nope", {}) is False

    def test_connect_and_gateway_listed(self, connected_engine):
        assert connected_engine.gateways == ["fake"]

    def test_connect_passes_setting_to_gateway(self, connected_engine):
        gw = list(connected_engine._gateways.values())[0]
        assert gw.connected is True
        assert gw.setting == {"account": "test"}

    def test_connect_is_idempotent(self, connected_engine):
        assert connected_engine.connect("fake", {}) is True
        assert len(connected_engine.gateways) == 1

    def test_close_removes_gateway(self, connected_engine):
        gw = list(connected_engine._gateways.values())[0]
        connected_engine.close("fake")
        assert gw.closed is True
        assert connected_engine.gateways == []

    def test_close_unknown_gateway_is_noop(self, engine):
        engine.close("nope")  # should not raise


class TestOrderRouting:
    def test_send_order_via_connected_gateway(self, connected_engine):
        orderid = connected_engine.send_order({"symbol": "BTC/USDT"}, "fake")
        assert orderid == "ORDER_1"
        gw = list(connected_engine._gateways.values())[0]
        assert gw.sent_orders == [{"symbol": "BTC/USDT"}]

    def test_send_order_unknown_gateway_returns_none(self, engine):
        assert engine.send_order({"symbol": "BTC/USDT"}, "nope") is None

    def test_send_order_gateway_error_returns_none(self, connected_engine):
        gw = list(connected_engine._gateways.values())[0]
        gw.fail_send = True
        assert connected_engine.send_order({"symbol": "BTC/USDT"}, "fake") is None

    def test_cancel_order_via_connected_gateway(self, connected_engine):
        assert connected_engine.cancel_order({"orderid": "O1"}, "fake") is True

    def test_cancel_order_unknown_gateway_returns_false(self, engine):
        assert engine.cancel_order({"orderid": "O1"}, "nope") is False


class TestEventCaches:
    def test_tick_event_updates_cache(self, engine):
        tick = TickData(gateway_name="fake", symbol="BTC/USDT", last_price=100.0)
        engine._on_tick(Event(EventType.EVENT_TICK, tick))
        ticks = engine.get_ticks()
        assert ticks["BTC/USDT"].last_price == 100.0

    def test_get_ticks_symbol_filter(self, engine):
        engine._on_tick(Event(EventType.EVENT_TICK, TickData(symbol="BTC/USDT")))
        engine._on_tick(Event(EventType.EVENT_TICK, TickData(symbol="ETH/USDT")))
        assert set(engine.get_ticks("BTC")) == {"BTC/USDT"}

    def test_account_event_updates_cache(self, engine):
        account = AccountData(gateway_name="fake", accountid="ACC1", balance=500.0)
        engine._on_account(Event(EventType.EVENT_ACCOUNT, account))
        assert engine.get_accounts()["ACC1"].balance == pytest.approx(500)

    def test_async_publish_reaches_cache(self, connected_engine):
        tick = TickData(gateway_name="fake", symbol="ETH/USDT", last_price=42.0)
        connected_engine.event_engine.publish(EventType.EVENT_TICK, tick, "fake")
        found = wait_until(lambda: "ETH/USDT" in connected_engine.get_ticks())
        assert found, "tick event was not processed by the engine"

    def test_none_data_events_ignored(self, engine):
        engine._on_tick(Event(EventType.EVENT_TICK, None))
        engine._on_account(Event(EventType.EVENT_ACCOUNT, None))
        assert engine.get_ticks() == {}
        assert engine.get_accounts() == {}

    def test_stop_shuts_down_cleanly(self):
        eng = MainEngine()
        eng.add_gateway_class(FakeGateway, "fake")
        eng.connect("fake", {})
        eng.stop()
        assert eng.is_active is False
