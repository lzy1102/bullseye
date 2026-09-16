"""
Test OrderExecutor live (gateway-routed) execution and simulated mode.
"""
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from bullseye.configuration.config import Config
from bullseye.order.order_executor import OrderExecutor
from bullseye.order.position_manager import PositionManager
from bullseye.trader.object import OrderData, Status
from bullseye.wallets.wallets import Wallets


def make_order(status: Status, traded: float = 0.0, price: float = 0.0) -> OrderData:
    return OrderData(
        orderid="ORD1",
        symbol="BTC/USDT",
        price=price,
        volume=1.0,
        traded=traded,
        status=status,
    )


class ScriptedGateway:
    """Gateway returning a scripted sequence of order states per poll."""

    def __init__(self, script, accept=True):
        self.script = script
        self.accept = accept
        self.sent = []
        self.cancelled = []
        self.poll_idx = 0

    def send_order(self, req):
        self.sent.append(req)
        return "ORD1" if self.accept else None

    def query_order(self, req):
        idx = min(self.poll_idx, len(self.script) - 1)
        self.poll_idx += 1
        return self.script[idx]

    def cancel_order(self, req):
        self.cancelled.append(req["orderid"])
        return True


def make_executor(dry_run: bool = False, gateway=None):
    config = Config()
    config.set("dry_run", dry_run)
    config.set("stake_amount", 100)
    config.set("max_open_trades", 3)
    config.set("tradable_balance_ratio", 1.0)
    config.set("execution.order_timeout", 0.05)
    config.set("execution.order_poll_interval", 0.005)

    wallets = Wallets(config)
    wallets.add_amount("USDT", 1000)
    pm = PositionManager(config, wallets)
    executor = OrderExecutor(config=config, position_manager=pm, wallets=wallets)
    if gateway is not None:
        executor.set_gateway(gateway)
    return executor, pm, wallets


class TestLiveEntry:
    def test_full_fill_books_actual_values(self):
        gw = ScriptedGateway([make_order(Status.ALLTRADED, traded=1.0, price=101.0)])
        executor, pm, wallets = make_executor(gateway=gw)

        trade = executor.execute_entry("BTC/USDT", rate=100.0, enter_tag="t1")

        assert trade is not None
        assert trade.open_rate == pytest.approx(101.0)  # actual fill price
        assert trade.amount == pytest.approx(1.0)
        assert trade.stake_amount == pytest.approx(101.0)
        assert pm.has_open_trade("BTC/USDT")
        assert wallets.get_free("USDT") == pytest.approx(899.0)
        assert gw.sent[0]["direction"].value == "long"

    def test_rejected_order_returns_none(self):
        gw = ScriptedGateway([make_order(Status.REJECTED, traded=0.0)])
        executor, pm, wallets = make_executor(gateway=gw)

        assert executor.execute_entry("BTC/USDT", rate=100.0) is None
        assert not pm.has_open_trade("BTC/USDT")
        assert wallets.get_free("USDT") == pytest.approx(1000)
        assert gw.cancelled == []  # rejected is terminal - no cancel needed

    def test_timeout_cancels_and_returns_none(self):
        gw = ScriptedGateway([make_order(Status.NOTTRADED, traded=0.0)])
        executor, pm, _ = make_executor(gateway=gw)

        assert executor.execute_entry("BTC/USDT", rate=100.0) is None
        assert not pm.has_open_trade("BTC/USDT")
        assert gw.cancelled == ["ORD1"]

    def test_partial_fill_books_filled_portion(self):
        gw = ScriptedGateway([make_order(Status.PARTTRADED, traded=0.4, price=100.0)])
        executor, pm, _ = make_executor(gateway=gw)

        trade = executor.execute_entry("BTC/USDT", rate=100.0)

        assert trade is not None
        assert trade.amount == pytest.approx(0.4)
        assert trade.stake_amount == pytest.approx(40.0)
        assert gw.cancelled == ["ORD1"]  # remainder cancelled

    def test_send_order_none_returns_none(self):
        gw = ScriptedGateway([make_order(Status.ALLTRADED, traded=1.0)], accept=False)
        executor, pm, _ = make_executor(gateway=gw)

        assert executor.execute_entry("BTC/USDT", rate=100.0) is None
        assert not pm.has_open_trade("BTC/USDT")


class TestLiveExit:
    def _open_trade(self, executor, pm):
        gw = ScriptedGateway([make_order(Status.ALLTRADED, traded=1.0, price=100.0)])
        executor.set_gateway(gw)
        trade = executor.execute_entry("BTC/USDT", rate=100.0)
        assert trade is not None
        return trade, gw

    def test_full_exit_closes_trade(self):
        executor, pm, wallets = make_executor()
        trade, entry_gw = self._open_trade(executor, pm)

        exit_gw = ScriptedGateway([make_order(Status.ALLTRADED, traded=1.0, price=105.0)])
        executor.set_gateway(exit_gw)

        closed = executor.execute_exit(trade, rate=105.0, exit_reason="roi")

        assert closed is not None
        assert closed.close_rate == pytest.approx(105.0)
        assert closed.exit_reason == "roi"
        assert not pm.has_open_trade("BTC/USDT")
        assert exit_gw.sent[0]["direction"].value == "short"
        assert exit_gw.sent[0]["offset"].value == "close"

    def test_partial_exit_keeps_trade_open(self):
        executor, pm, _ = make_executor()
        trade, _ = self._open_trade(executor, pm)

        exit_gw = ScriptedGateway([make_order(Status.PARTTRADED, traded=0.3, price=105.0)])
        executor.set_gateway(exit_gw)

        result = executor.execute_exit(trade, rate=105.0, exit_reason="roi")

        assert result is None
        assert pm.has_open_trade("BTC/USDT")  # conservative: stays open
        assert exit_gw.cancelled == ["ORD1"]

    def test_t1_stock_blocked_before_gateway_call(self):
        """T+1 gate must reject the exit before any order reaches the gateway."""
        executor, pm, _ = make_executor()

        entry_gw = ScriptedGateway([make_order(Status.ALLTRADED, traded=1.0, price=10.0)])
        executor.set_gateway(entry_gw)
        trade = executor.execute_entry("600000.SH", rate=10.0)
        assert trade is not None  # stock pair auto-detects T+1 restriction

        exit_gw = ScriptedGateway([make_order(Status.ALLTRADED, traded=1.0, price=10.5)])
        executor.set_gateway(exit_gw)

        assert executor.execute_exit(trade, rate=10.5, exit_reason="roi") is None
        assert exit_gw.sent == []  # nothing was sent


class TestSimulatedMode:
    def test_dry_run_never_calls_gateway(self):
        gw = ScriptedGateway([make_order(Status.ALLTRADED, traded=1.0)])
        executor, pm, _ = make_executor(dry_run=True, gateway=gw)

        trade = executor.execute_entry("BTC/USDT", rate=100.0)

        assert trade is not None
        assert trade.open_rate == pytest.approx(100.0)  # booked at signal rate
        assert gw.sent == []  # simulator never touched the gateway

    def test_no_gateway_is_simulated(self):
        executor, pm, _ = make_executor(dry_run=False, gateway=None)
        assert executor.is_live is False
        trade = executor.execute_entry("BTC/USDT", rate=100.0)
        assert trade is not None
        assert trade.open_rate == pytest.approx(100.0)
