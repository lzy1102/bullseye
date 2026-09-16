"""
Test TemplateGateway (HTTP order bridge reference implementation).
"""
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from bullseye.gateway.template.gateway_template import TemplateGateway
from bullseye.trader.eventengine import EventEngine, EventType
from bullseye.trader.object import Status


class FakeTransport:
    """Scriptable transport: routes map (method, path-prefix) -> handler."""

    def __init__(self):
        self.responses = {}
        self.calls = []

    def set(self, method, path, response):
        self.responses[(method, path)] = response

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        # Exact match first, then prefix match (for /order/{id})
        if (method, path) in self.responses:
            return self.responses[(method, path)]
        for (m, p), resp in self.responses.items():
            if m == method and path.startswith(p):
                return resp(path, body) if callable(resp) else resp
        raise ConnectionError(f"No scripted response for {method} {path}")


def make_gateway(transport=None):
    engine = EventEngine()
    engine.start()
    gw = TemplateGateway(event_engine=engine, transport=transport or FakeTransport())
    return gw, engine


def collect_events(engine, event_type):
    events = []
    engine.subscribe(event_type, events.append)
    return events


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestConnectAndKillSwitch:
    def test_connect_health_ok(self):
        transport = FakeTransport()
        transport.set("GET", "/health", {"status": "ok"})
        gw, engine = make_gateway(transport)
        try:
            gw.connect(base_url="http://localhost:9999")
            assert gw.connected is True
        finally:
            gw.close()
            engine.stop()

    def test_connect_unhealthy_raises(self):
        transport = FakeTransport()
        transport.set("GET", "/health", {"status": "down"})
        gw, engine = make_gateway(transport)
        try:
            with pytest.raises(ConnectionError):
                gw.connect(base_url="http://localhost:9999")
        finally:
            engine.stop()

    def test_close_idempotent(self):
        gw, engine = make_gateway()
        gw.close()
        gw.close()
        engine.stop()

    def test_kill_switch_blocks_orders(self, tmp_path):
        marker = tmp_path / "DISABLE"
        marker.write_text("stop")
        gw, engine = make_gateway()
        try:
            gw._kill_switch_file = str(marker)
            orderid = gw.send_order({"symbol": "600000.SH", "volume": 100, "price": 10})
            assert orderid is None
        finally:
            engine.stop()

    def test_kill_switch_removed_allows_orders(self, tmp_path):
        marker = tmp_path / "DISABLE"
        transport = FakeTransport()
        transport.set("POST", "/order", {"order_id": "B1"})
        gw, engine = make_gateway(transport)
        try:
            gw._kill_switch_file = str(marker)
            orderid = gw.send_order({"symbol": "600000.SH", "volume": 100, "price": 10})
            assert orderid is not None
        finally:
            engine.stop()


class TestOrderLifecycle:
    def test_send_order_publishes_and_returns_id(self):
        transport = FakeTransport()
        transport.set("POST", "/order", {"order_id": "B1"})
        gw, engine = make_gateway(transport)
        orders = collect_events(engine, EventType.EVENT_ORDER)
        try:
            orderid = gw.send_order({"symbol": "600000.SH", "volume": 100, "price": 10.5})
            assert orderid and orderid.startswith("Template-")
            assert wait_until(lambda: len(orders) == 1)
            assert orders[0].data.status == Status.NOTTRADED
            assert orders[0].data.symbol == "600000.SH"
            # client_order_id is echoed to the bridge
            _, _, body = transport.calls[-1]
            assert body["client_order_id"] == orderid
        finally:
            engine.stop()

    def test_confirm_order_publishes_transitions_and_fills(self):
        transport = FakeTransport()
        transport.set("POST", "/order", {"order_id": "B1"})
        states = iter([
            {"status": "pending", "filled": 0.0},
            {"status": "partial", "filled": 0.5, "avg_price": 10.0, "symbol": "600000.SH"},
            {"status": "filled", "filled": 1.0, "avg_price": 10.1, "symbol": "600000.SH"},
        ])

        def order_handler(path, body):
            return next(states)

        transport.set("GET", "/order/", order_handler)
        gw, engine = make_gateway(transport)
        orders = collect_events(engine, EventType.EVENT_ORDER)
        trades = collect_events(engine, EventType.EVENT_TRADE)
        try:
            orderid = gw.send_order({"symbol": "600000.SH", "volume": 100, "price": 10.5})
            wait_until(lambda: len(orders) == 1)  # initial NOTTRADED

            final = gw.confirm_order(orderid, timeout=2.0, poll_interval=0.01)

            assert final.status == Status.ALLTRADED
            assert final.traded == pytest.approx(1.0)
            assert wait_until(lambda: len(orders) == 3)
            statuses = [e.data.status for e in orders]
            assert statuses == [Status.NOTTRADED, Status.PARTTRADED, Status.ALLTRADED]
            # Two fill deltas: 0.5 and 0.5
            assert wait_until(lambda: len(trades) == 2)
            assert [t.data.volume for t in trades] == pytest.approx([0.5, 0.5])
        finally:
            engine.stop()

    def test_cancel_order(self):
        transport = FakeTransport()
        transport.set("POST", "/order/", {"ok": True})
        gw, engine = make_gateway(transport)
        try:
            assert gw.cancel_order({"orderid": "Template-1-1"}) is True
        finally:
            engine.stop()

    def test_reconcile_publishes_open_orders(self):
        transport = FakeTransport()
        transport.set("GET", "/orders?status=open", [
            {"client_order_id": "X1", "status": "partial", "filled": 0.5, "symbol": "600000.SH"},
            {"client_order_id": "X2", "status": "pending", "filled": 0.0, "symbol": "000001.SZ"},
        ])
        gw, engine = make_gateway(transport)
        orders = collect_events(engine, EventType.EVENT_ORDER)
        try:
            count = gw.reconcile_open_orders()
            assert count == 2
            assert wait_until(lambda: len(orders) == 2)
        finally:
            engine.stop()


class TestQueries:
    def test_query_account(self):
        transport = FakeTransport()
        transport.set("GET", "/account", {
            "account_id": "A1", "balance": 5000, "available": 4200, "frozen": 800,
        })
        gw, engine = make_gateway(transport)
        try:
            account = gw.query_account()
            assert account.accountid == "A1"
            assert account.balance == pytest.approx(5000)
            assert account.available == pytest.approx(4200)
        finally:
            engine.stop()

    def test_query_position(self):
        transport = FakeTransport()
        transport.set("GET", "/positions", [
            {"symbol": "600000.SH", "direction": "long", "volume": 100, "avg_price": 10.5},
        ])
        gw, engine = make_gateway(transport)
        try:
            positions = gw.query_position()
            assert len(positions) == 1
            assert positions[0].symbol == "600000.SH"
            assert positions[0].volume == pytest.approx(100)
            assert positions[0].price == pytest.approx(10.5)
        finally:
            engine.stop()

    def test_query_order_maps_status(self):
        transport = FakeTransport()
        transport.set("GET", "/order/", {"status": "filled", "filled": 1.0, "avg_price": 10.0})
        gw, engine = make_gateway(transport)
        try:
            order = gw.query_order({"orderid": "X1"})
            assert order.status == Status.ALLTRADED
        finally:
            engine.stop()

    def test_query_contracts_empty_ok(self):
        transport = FakeTransport()
        transport.set("GET", "/contracts", [])
        gw, engine = make_gateway(transport)
        try:
            assert gw.query_contract() == []
        finally:
            engine.stop()


class TestBarsFallback:
    def test_get_bars_from_bridge(self):
        transport = FakeTransport()
        transport.set("GET", "/bars", [
            {"datetime": "2024-01-01T00:00:00", "open": 10, "high": 11,
             "low": 9, "close": 10.5, "volume": 100},
            {"datetime": "2024-01-02T00:00:00", "open": 10.5, "high": 11.5,
             "low": 9.5, "close": 11, "volume": 120},
        ])
        gw, engine = make_gateway(transport)
        try:
            bars = gw.get_bars("600000.SH", "1d", limit=50)
            assert len(bars) == 2
            assert bars[0].close_price == pytest.approx(10.5)
            assert bars[0].datetime == datetime(2024, 1, 1)
        finally:
            engine.stop()

    def test_get_bars_absent_endpoint_returns_empty(self):
        transport = FakeTransport()  # no /bars scripted -> ConnectionError inside
        gw, engine = make_gateway(transport)
        try:
            assert gw.get_bars("600000.SH", "1d") == []
        finally:
            engine.stop()
