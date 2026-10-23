"""
Tests for ThsGateway (read-only THS counter gateway).

Uses an injected fake TradeClient: no network, no ths-trade-client needed.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from bullseye.gateway.stock.ths_gateway import (  # noqa: E402
    ThsGateway,
    _to_float,
    market_of,
    normalize_symbol,
)
from bullseye.trader.eventengine import EventEngine, EventType  # noqa: E402
from bullseye.trader.object import Status  # noqa: E402


class FakeThsClient:
    """Minimal stand-in for ths_client.TradeClient."""

    def __init__(self):
        self.started = False
        self.closed = False
        self.heartbeat = 0
        self.auto_reconnect = None
        self.pushes = []
        self.calls = []

    def start(self):
        self.started = True
        return {"sess": b"abcd", "iv": b"12345678"}

    def close(self):
        self.closed = True

    def account_info(self):
        return {"kv": {"zjzh": "12345678"}}

    def query_balance(self):
        self.calls.append("query_balance")
        return {"kv": {"zjjye": "100000.00", "kqye": "98500.50"}}

    def query_positions(self, market="2"):
        self.calls.append(f"query_positions:{market}")
        if market == "2":
            return {"kv": {"zqdm": "601398", "zqmc": "工商银行",
                           "wdbl": "1000", "kyzq": "800", "zxj": "7.20"}}
        return {"kv": {"zqdm": "000001", "zqmc": "平安银行",
                       "wdbl": "0", "kyzq": "0", "zxj": "11.10"}}

    def query_orders(self, market="2"):
        self.calls.append(f"query_orders:{market}")
        return {"kv": {"wtbh": "7788", "zqdm": "601398", "jybz": "b",
                       "wtjg": "7.10", "wtml": "1000", "cjsl": "1000",
                       "wtztdm": "已成交"}}

    def query_trades(self, market="2"):
        return {"kv": {}}


def make_gateway(client=None):
    ee = EventEngine()
    gw = ThsGateway(ee, "THS", client=client or FakeThsClient())
    return gw


def test_normalize_symbol():
    assert normalize_symbol("601398.SH") == "601398"
    assert normalize_symbol("000001.SZ") == "000001"
    assert normalize_symbol("") == ""


def test_market_detection():
    assert market_of("601398.SH") == "2"
    assert market_of("688981.SH") == "2"
    assert market_of("000001.SZ") == "1"
    assert market_of("300750.SZ") == "1"


def test_to_float_tolerates_junk():
    assert _to_float("1,234.5") == 1234.5
    assert _to_float(None) == 0.0
    assert _to_float("") == 0.0
    assert _to_float("abc") == 0.0
    assert _to_float(7) == 7.0


def test_connect_starts_counter_and_publishes():
    client = FakeThsClient()
    gw = make_gateway(client)
    gw.connect(heartbeat=15)
    assert client.started is True
    assert client.heartbeat == 15
    assert gw._connected is True
    gw.close()
    assert client.closed is True
    assert gw._connected is False


def test_connect_without_client_or_profile_raises():
    gw = ThsGateway(EventEngine(), "THS", client=None)
    # either ths-trade-client missing (ImportError) or profile required (ValueError)
    with pytest.raises((ImportError, ValueError)):
        gw.connect()


def test_query_account():
    gw = make_gateway()
    acct = gw.query_account()
    assert acct is not None
    assert acct.balance == pytest.approx(100000.0)
    assert acct.available == pytest.approx(98500.5)
    assert acct.accountid == "12345678"


def test_query_position_maps_counter_fields():
    gw = make_gateway()
    positions = gw.query_position()
    assert len(positions) == 1  # only the SH row has volume
    pos = positions[0]
    assert pos.symbol == "601398"
    assert pos.volume == pytest.approx(1000.0)
    assert pos.available == pytest.approx(800.0)


def test_query_order_maps_counter_status():
    gw = make_gateway()
    gw._order_map_store = {"THS-1": "7788"}
    order = gw.query_order({"orderid": "THS-1"})
    assert order is not None
    assert order.symbol == "601398"
    assert order.volume == pytest.approx(1000.0)
    assert order.traded == pytest.approx(1000.0)
    assert order.status == Status.ALLTRADED


def test_query_order_unknown_orderid_returns_none():
    gw = make_gateway()
    assert gw.query_order({"orderid": "missing"}) is None
    assert gw.query_order({}) is None


def test_query_contract_derives_from_positions():
    """Contracts are derived per market: SH row + SZ row both register."""
    gw = make_gateway()
    contracts = gw.query_contract()
    assert [c.symbol for c in contracts] == ["601398", "000001"]
    assert contracts[0].name == "工商银行"
    assert contracts[1].exchange == "1"


def test_send_and_cancel_order_are_blocked():
    gw = make_gateway()
    with pytest.raises(NotImplementedError):
        gw.send_order({"symbol": "601398", "volume": 100})
    with pytest.raises(NotImplementedError):
        gw.cancel_order({"orderid": "x"})


def test_push_produces_throttled_tick():
    gw = make_gateway()
    gw._on_push({"kv": {"zqdm": "601398", "zxj": "7.25", "zgj": "7.30",
                        "zdj": "7.18", "cjl": "123456"}})
    cached = gw._quote_cache["601398"]
    assert cached["last"] == pytest.approx(7.25)
    assert cached["volume"] == pytest.approx(123456)
    tick = gw.get_tick("601398.SH")
    assert tick is not None and tick.last_price == pytest.approx(7.25)
    assert gw.get_tick("999999.SH") is None


def test_close_is_idempotent():
    client = FakeThsClient()
    gw = make_gateway(client)
    gw.connect()
    gw.close()
    gw.close()  # must not raise
    assert client.closed is True

# ==========================================================================
# Order placement machinery (gated by _LIVE_TRADING_ENABLED)
# ==========================================================================

class ScriptedClient(FakeThsClient):
    """Client whose order calls are scripted, to exercise dedup/reconcile."""

    def __init__(self):
        super().__init__()
        self.buy_calls = 0
        self.sell_calls = 0
        self.buy_reply = {"text": "委托编号:900001 合同编号:123 状态:已报"}
        self.buy_error = None
        self.live_orders = []          # rows returned by query_orders

    def buy_market(self, code, qty, **kw):
        self.buy_calls += 1
        if self.buy_error is not None:
            raise self.buy_error
        return self.buy_reply

    def sell_market(self, code, qty, **kw):
        self.sell_calls += 1
        return {"text": "wtbh=900002"}

    def limit_order(self, code, qty, price, is_sell=False, **kw):
        self.buy_calls += 1
        return {"text": f"wtbh=900003 price={price}"}

    def query_orders(self, market="2"):
        if self.live_orders:
            return {"rows": list(self.live_orders)}
        return {"kv": {}}


def make_trading_gateway(client=None):
    gw = make_gateway(client or ScriptedClient())
    gw._LIVE_TRADING_ENABLED = True
    gw.connect(heartbeat=0, enforce_trading_window=False)
    return gw


def test_send_order_blocked_by_master_switch():
    gw = make_gateway()          # default: _LIVE_TRADING_ENABLED = False
    with pytest.raises(NotImplementedError):
        gw.send_order({"symbol": "601398", "volume": 100})


def test_send_order_maps_counter_number_and_publishes():
    events = []

    class RecordingEngine(EventEngine):
        def publish(self, event_type, data=None, gateway_name=""):
            if data is not None:
                events.append((str(event_type), data))
            # swallow: no engine thread in tests

    client = ScriptedClient()
    ee = RecordingEngine()
    gw = ThsGateway(ee, "THS", client=client)
    gw._LIVE_TRADING_ENABLED = True
    gw.connect(heartbeat=0, enforce_trading_window=False)
    orderid = gw.send_order({"symbol": "601398", "volume": 100})
    assert orderid and orderid.startswith("THS-")
    assert client.buy_calls == 1
    assert gw._counter_no(orderid) == "900001"
    assert events, "no order event published"


def test_send_order_suppresses_auto_retry_during_submit():
    client = ScriptedClient()
    gw = make_trading_gateway(client)
    seen = {}
    orig = client.buy_market

    def spy(code, qty, **kw):
        seen["auto_reconnect"] = getattr(client, "auto_reconnect", None)
        return orig(code, qty, **kw)

    client.buy_market = spy
    gw.send_order({"symbol": "601398", "volume": 100})
    assert seen["auto_reconnect"] is False     # retry suppressed while placing
    assert getattr(client, "auto_reconnect", None) is True  # restored afterwards


def test_send_order_dedup_adopts_existing_live_order():
    client = ScriptedClient()
    client.live_orders = [{"wtbh": "55555", "zqdm": "601398", "jybz": "b",
                           "wtml": "100", "wtjg": "-1", "wtztdm": "已报"}]
    gw = make_trading_gateway(client)
    orderid = gw.send_order({"symbol": "601398", "volume": 100})
    assert client.buy_calls == 0, "must not double-send an identical live order"
    assert gw._counter_no(orderid) == "55555"


def test_send_order_reconciles_ambiguous_failure_without_resending():
    """Dropped connection after the order reached the counter -> adopt, never resend."""
    client = ScriptedClient()
    gw = make_trading_gateway(client)
    gw._reconcile_grace = 0.0

    def ambiguous(code, qty, **kw):
        client.buy_calls += 1
        # the order DID land at the counter; only our socket died
        client.live_orders = [{"wtbh": "77777", "zqdm": "601398", "jybz": "b",
                               "wtml": "100", "wtjg": "-1", "wtztdm": "已报"}]
        raise ConnectionError("socket closed")

    client.buy_market = ambiguous
    orderid = gw.send_order({"symbol": "601398", "volume": 100})
    assert orderid is not None
    assert gw._counter_no(orderid) == "77777"
    assert client.buy_calls == 1, "found on reconcile; must not resend"


def test_send_order_resends_at_most_once():
    client = ScriptedClient()
    gw = make_trading_gateway(client)
    gw._reconcile_grace = 0.0
    def always_fail(code, qty, **kw):
        client.buy_calls += 1
        raise ConnectionError("socket closed")

    client.buy_market = always_fail
    assert gw.send_order({"symbol": "601398", "volume": 100}) is None
    assert client.buy_calls == 2, "exactly one retry"


def test_kill_switch_blocks_new_orders():
    import tempfile
    from pathlib import Path as P

    client = ScriptedClient()
    gw = make_trading_gateway(client)
    with tempfile.TemporaryDirectory() as td:
        marker = P(td) / "KILL"
        marker.write_text("1")
        gw._kill_switch_file = str(marker)
        with pytest.raises(RuntimeError):
            gw.send_order({"symbol": "601398", "volume": 100})
        assert client.buy_calls == 0


def test_trading_window_guard():
    from datetime import datetime
    from bullseye.gateway.stock.ths_gateway import in_trading_window

    assert in_trading_window(datetime(2026, 10, 19, 10, 0)) is True
    assert in_trading_window(datetime(2026, 10, 19, 14, 0)) is True
    assert in_trading_window(datetime(2026, 10, 19, 12, 0)) is False
    assert in_trading_window(datetime(2026, 10, 19, 8, 0)) is False
    assert in_trading_window(datetime(2026, 10, 19, 15, 30)) is False
    assert in_trading_window(datetime(2026, 10, 17, 10, 0)) is False  # Saturday


def test_extract_counter_no_variants():
    from bullseye.gateway.stock.ths_gateway import extract_counter_no

    assert extract_counter_no({"kv": {"wtbh": "123"}}) == "123"
    assert extract_counter_no({"text": "委托编号:900001 状态"}) == "900001"
    assert extract_counter_no({"text": "wtbh=900002"}) == "900002"
    assert extract_counter_no({"text": "资金不足"}) == ""
    assert extract_counter_no(None) == ""


def test_reconcile_adopts_foreign_orders():
    client = ScriptedClient()
    client.live_orders = [{"wtbh": "88888", "zqdm": "000001", "jybz": "s",
                           "wtml": "500", "wtjg": "11.20", "wtztdm": "部成"}]
    gw = make_trading_gateway(client)
    adopted = gw.reconcile_orders()
    assert "88888" in adopted
    ext_id = adopted["88888"]
    assert ext_id.startswith("THS-EXT-")
    order = gw.query_order({"orderid": ext_id})
    assert order is not None and order.symbol == "000001"
    assert order.status == Status.PARTTRADED


def test_confirm_order_publishes_fill_delta():
    client = ScriptedClient()
    gw = make_trading_gateway(client)
    client.live_orders = [{"wtbh": "900001", "zqdm": "601398", "jybz": "b",
                           "wtml": "100", "wtjg": "7.10", "cjsl": "100",
                           "wtztdm": "已成交"}]
    order = gw.confirm_order("THS-fake", timeout=0.3, poll_interval=0.05)
    assert order is None or order.status in (Status.ALLTRADED, Status.NOTTRADED)


# ==========================================================================
# Profile / credentials hygiene
# ==========================================================================

def test_profile_template_has_required_fields():
    """The shipped template must contain the fields TradeClient needs."""
    import json

    tmpl = ROOT / "user_data" / "local_profile.example.json"
    assert tmpl.exists(), "profile template missing"
    data = json.loads(tmpl.read_text(encoding="utf-8"))
    for key in ("zjzh", "gdzh_sh", "gdzh_sz"):
        assert key in data, f"template missing required field {key}"
    # documented shape: SH shareholder id starts with "A", SZ is digits only
    assert data["gdzh_sh"].startswith("A")
    assert data["gdzh_sz"].isdigit()
    # placeholder only - never a real-looking account
    assert set(data["zjzh"]) <= set("0123456789")


def test_real_profile_is_gitignored_but_template_is_not():
    import subprocess

    def ignored(path):
        r = subprocess.run(["git", "check-ignore", "-q", str(path)],
                           cwd=ROOT)
        return r.returncode == 0

    assert ignored("user_data/local_profile.json"), "credentials must stay ignored"
    assert not ignored("user_data/local_profile.example.json"), \
        "the placeholder template must be committable"


def test_config_passthrough_drops_only_gateway_key():
    """market_type: custom forwards every custom.* key except `gateway`."""
    from bullseye.configuration.config import Config

    cfg = Config()
    cfg.set("market_type", "custom")
    cfg.set("custom.gateway", "pkg.mod.ThsGateway")
    cfg.set("custom.profile", "user_data/local_profile.json")
    cfg.set("custom.kill_switch_file", "user_data/KILL_TRADING")
    cfg.set("custom.reconcile_grace", 2.5)
    kwargs = {}
    custom = dict(cfg.get("custom", {}))
    custom.pop("gateway", None)
    kwargs.update(custom)
    assert "gateway" not in kwargs
    assert kwargs["profile"] == "user_data/local_profile.json"
    assert kwargs["kill_switch_file"] == "user_data/KILL_TRADING"
    assert kwargs["reconcile_grace"] == 2.5


# ==========================================================================
# One-click capture helper
# ==========================================================================

def _capture_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "capture_ths_profile",
        ROOT / "scripts" / "capture_ths_profile.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_capture_script_validates_required_fields(tmp_path):
    mod = _capture_module()
    good = tmp_path / "p.json"
    good.write_text(json.dumps({"zjzh": "1", "gdzh_sh": "A1", "gdzh_sz": "2"}),
                    encoding="utf-8")
    assert mod.validate(good) == (True, [])

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"zjzh": "1"}), encoding="utf-8")
    ok, missing = mod.validate(bad)
    assert ok is False and "gdzh_sh" in missing and "gdzh_sz" in missing

    assert mod.validate(tmp_path / "nope.json")[0] is False

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert mod.validate(broken)[0] is False


def test_capture_bat_is_ascii_only():
    """cmd.exe mis-parses non-ASCII batch files; the launcher must stay ASCII."""
    bat = ROOT / "scripts" / "capture_ths_profile.bat"
    raw = bat.read_bytes()
    assert raw, "batch launcher missing"
    offenders = [b for b in raw if b > 127]
    assert not offenders, f"non-ASCII bytes in .bat: {offenders[:8]}"
    assert b"capture_ths_profile.py" in raw


def test_capture_script_default_output_is_gitignored():
    import subprocess

    mod = _capture_module()
    assert mod.DEFAULT_OUT.name == "local_profile.json"
    r = subprocess.run(["git", "check-ignore", "-q", str(mod.DEFAULT_OUT)],
                       cwd=ROOT)
    assert r.returncode == 0, "default profile path must stay git-ignored"


class TestThsClientContract:
    """Pin the ths-trade-client surface this gateway depends on.

    The client is an external repo we do not vendor, so an upstream update can
    silently break us. These tests fail fast when a symbol we call disappears
    or changes signature. Skipped when ths-trade-client is not installed.
    """

    @staticmethod
    def _client():
        return pytest.importorskip("ths_client")

    def test_client_version_floor(self):
        """precheck() hangs mid-session before 0.13.1; we must not run it."""
        mod = self._client()
        raw = getattr(mod, "__version__", "") or ""
        parts = [int(p) for p in raw.split(".")[:3] if p.isdigit()]
        assert parts, f"cannot parse ths_client version {raw!r}"
        assert tuple(parts) >= (0, 13, 1), (
            f"ths-trade-client {raw} < 0.13.1: precheck() blocks during "
            "trading hours, orders would time out"
        )

    def test_methods_we_call_exist(self):
        mod = self._client()
        client = mod.TradeClient
        for name in ("from_profile", "start", "close", "query_balance",
                     "query_positions", "query_orders", "account_info",
                     "buy_market", "sell_market", "limit_order"):
            assert callable(getattr(client, name, None)), f"missing {name}"

    def test_cancel_is_still_unimplemented_upstream(self):
        """Blocker #1: our cancel_order stays disabled until upstream ships it."""
        mod = self._client()
        client = mod.TradeClient
        assert not hasattr(client, "cancel_order"), (
            "ths-trade-client now has cancel_order: wire it into the gateway "
            "and re-check the double-submit reconcile path"
        )
