"""
Live/backtest parity: strategy callbacks honored on the live path.

Mirrors the backtest-side guarantees (custom stake/leverage/prices,
adjust/DCA, custom stoploss/ROI, exit-signal gates, stock rules,
order fills, order timeouts) through PositionManager, OrderExecutor
and StrategyRunner without any gateway.
"""
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from bullseye.bot.strategy_runner import StrategyRunner
from bullseye.configuration.config import Config
from bullseye.order.order_executor import OrderExecutor
from bullseye.order.position_manager import MarketType, PositionManager
from bullseye.strategy.interface import IStrategy
from bullseye.trader.object import Status
from bullseye.wallets.wallets import Wallets


def make_stack(strategy=None, **cfg_entries):
    config = Config()
    config.set("dry_run", True)
    config.set("dry_run_wallet", 100000)
    config.set("stake_amount", 20000)
    config.set("max_open_trades", 3)
    for k, v in cfg_entries.items():
        config.set(k, v)
    wallets = Wallets(config, initial_balance=100000)
    pm = PositionManager(config, wallets)
    ex = OrderExecutor(config, pm, wallets)
    if strategy is None:
        strategy = IStrategy()
    pm.set_strategy(strategy)
    ex.set_strategy(strategy)
    return config, wallets, pm, ex, strategy


def open_long(pm, pair="BTC/USDT", rate=100.0, stake=20000.0):
    amount = stake / rate
    return pm.open_trade(
        pair=pair, rate=rate, amount=amount, stake_amount=stake,
        market_type=MarketType.CRYPTO,
    )


class TestLiveStoplossRoi:
    def test_custom_stoploss_tightens(self):
        config, wallets, pm, ex, _ = make_stack()

        class Tight(IStrategy):
            stoploss = -0.50
            use_custom_stoploss = True

            def custom_stoploss(self, pair, trade, current_time,
                                current_rate, current_profit, **k):
                return -0.01

        pm.set_strategy(Tight())
        trade = open_long(pm)
        assert pm.check_stoploss(trade, 98.5) is True  # below 99
        assert trade.stop_loss == pytest.approx(99.0)

    def test_custom_roi_overrides_table(self):
        config, wallets, pm, ex, _ = make_stack()

        class DynRoi(IStrategy):
            minimal_roi = {"0": 1.0}  # unreachable statically

            def custom_roi(self, pair, current_time, current_rate,
                           current_profit, **k):
                return 0.01

        trade = open_long(pm)
        pm.set_strategy(DynRoi())
        # trade just opened: duration ~0 >= 0, profit 2% >= 1%
        assert pm.check_roi(trade, 102.0) == "roi_0m"

    def test_ignore_roi_on_entry_signal(self):
        config, wallets, pm, ex, _ = make_stack()

        class IgnoreRoi(IStrategy):
            minimal_roi = {"0": 0.01}
            ignore_roi_if_entry_signal = True

        trade = open_long(pm)
        pm.set_strategy(IgnoreRoi())
        assert pm.check_roi(trade, 105.0, has_entry_signal=True) is None
        assert pm.check_roi(trade, 105.0, has_entry_signal=False) == "roi_0m"


class TestLiveAdjust:
    def test_adjust_averages_cost(self):
        config, wallets, pm, ex, _ = make_stack()
        trade = open_long(pm, rate=100.0, stake=20000.0)
        assert pm.adjust_position(trade, 20000.0, 80.0) is True
        assert trade.amount == pytest.approx(200 + 250)
        assert trade.open_rate == pytest.approx(
            (100 * 200 + 80 * 250) / 450
        )
        assert trade.nr_of_successful_entries == 2

    def test_adjust_stock_lot_floor(self):
        config, wallets, pm, ex, _ = make_stack()
        trade = pm.open_trade(
            pair="600036.SH", rate=40.0, amount=300.0, stake_amount=12000.0,
            market_type=MarketType.STOCK,
        )
        # 1000/40 = 25 shares -> below 1 lot -> rejected
        assert pm.adjust_position(trade, 1000.0, 40.0) is False
        assert trade.amount == pytest.approx(300.0)
        # 12000/40 = 300 shares -> 3 lots booked
        assert pm.adjust_position(trade, 12000.0, 40.0) is True
        assert trade.amount == pytest.approx(600.0)


class TestLiveEntryContext:
    def test_stake_sees_side_and_leverage(self):
        config, wallets, pm, ex, _ = make_stack()
        seen = {}

        class Rec(IStrategy):
            def custom_stake_amount(self, pair, current_time, current_rate,
                                    proposed_stake, min_stake, max_stake,
                                    leverage, entry_tag, side, **k):
                seen.update(side=side, leverage=leverage, tag=entry_tag)
                return 5000.0

            def leverage(self, pair, current_time, current_rate,
                         proposed_leverage, max_leverage, entry_tag,
                         side, **k):
                return 3.0

        ex.set_strategy(Rec())
        stake = ex.calculate_stake_amount(
            "BTC/USDT", side="short", entry_tag="t",
            current_rate=100.0, current_time=datetime.now(),
        )
        assert stake == 5000.0
        assert seen == {"side": "short", "leverage": 3.0, "tag": "t"}

    def test_custom_entry_price_and_lot_reject(self):
        config, wallets, pm, ex, _ = make_stack()

        class Mk(IStrategy):
            def custom_entry_price(self, pair, current_time, proposed_rate,
                                   entry_tag, side, **k):
                return proposed_rate * 0.99

        ex.set_strategy(Mk())
        trade = ex.execute_entry(pair="BTC/USDT", rate=100.0)
        assert trade is not None
        assert trade.open_rate == pytest.approx(99.0)
        # Stock dust rejected: 100 USDT @ 100 CNY = 1 share < 1 lot
        dust = ex.execute_entry(pair="000001.SZ", rate=100.0,
                                stake_amount=100.0)
        assert dust is None

    def test_order_filled_on_entry_and_exit(self):
        config, wallets, pm, ex, _ = make_stack()
        seen = []

        class Rec(IStrategy):
            def order_filled(self, pair, trade, order, current_time, **k):
                seen.append((order.ft_order_side, order.price))

        ex.set_strategy(Rec())
        trade = ex.execute_entry(pair="BTC/USDT", rate=100.0,
                                 stake_amount=10000.0)
        assert trade is not None
        closed = ex.execute_exit(trade=trade, rate=110.0,
                                 exit_reason="test")
        assert closed is not None
        assert [s for s, _ in seen] == ["buy", "sell"]
        assert seen[0][1] == pytest.approx(100.0)
        assert seen[1][1] == pytest.approx(110.0)


class TestLiveTimeouts:
    def _live_executor(self, strategy):
        config = Config()
        config.set("dry_run", False)
        config.set("dry_run_wallet", 100000)
        config.set("stake_amount", 20000)
        config.set("max_open_trades", 3)
        config.set("execution.order_timeout", 0.05)
        config.set("execution.order_poll_interval", 0.01)
        wallets = Wallets(config, initial_balance=100000)
        # dry_run=False skips wallet init: fund explicitly for live tests.
        wallets.update_balance(config.stake_currency, total=100000.0,
                               free=100000.0, used=0.0)
        pm = PositionManager(config, wallets)
        ex = OrderExecutor(config, pm, wallets)
        ex.set_strategy(strategy)

        gateway = MagicMock()
        gateway.send_order.return_value = "OID1"
        gateway.query_order.return_value = SimpleNamespace(
            status=Status.NOTTRADED, traded=0, price=0.0
        )
        ex.set_gateway(gateway)
        assert ex.is_live is True
        return config, wallets, pm, ex, gateway

    def test_buy_timeout_cancel_by_default(self):
        _, _, _, ex, gateway = self._live_executor(IStrategy())
        trade = ex.execute_entry(pair="BTC/USDT", rate=100.0,
                                 stake_amount=10000.0)
        assert trade is None  # never filled -> cancelled, nothing booked
        gateway.cancel_order.assert_called()

    def test_sell_timeout_strategy_can_extend_once(self):
        # Entry timeouts have no trade object yet: always cancel (safe).
        # Exit timeouts consult check_sell_timeout (False extends once).
        calls = {"n": 0, "polls": 0}

        class Patient(IStrategy):
            def check_sell_timeout(self, pair, trade, order,
                                   current_time, **k):
                calls["n"] += 1
                return False  # extend; the fill below ends the wait

        config, wallets, pm, ex, gateway = self._live_executor(Patient())
        trade = pm.open_trade(
            pair="BTC/USDT", rate=100.0, amount=100.0, stake_amount=10000.0,
            market_type=MarketType.CRYPTO,
        )

        def _poll(_req):
            calls["polls"] += 1
            if calls["polls"] < 8:  # starve past the first 0.05s deadline
                return SimpleNamespace(status=Status.NOTTRADED, traded=0,
                                       price=0.0)
            return SimpleNamespace(status=Status.ALLTRADED, traded=100.0,
                                   price=100.0)

        gateway.query_order.side_effect = _poll
        closed = ex.execute_exit(trade=trade, rate=100.0,
                                 exit_reason="test")
        assert closed is not None
        assert calls["n"] == 1


def make_runner(strategy, pair="BTC/USDT", closes=None):
    config = Config()
    config.set("dry_run", True)
    config.set("dry_run_wallet", 100000)
    config.set("stake_amount", 20000)
    config.set("max_open_trades", 3)
    wallets = Wallets(config, initial_balance=100000)
    pm = PositionManager(config, wallets)
    ex = OrderExecutor(config, pm, wallets)
    pm.set_strategy(strategy)
    ex.set_strategy(strategy)
    dp = MagicMock()
    runner = StrategyRunner(config, strategy, dp, ex, pm, wallets)
    runner._running = True
    n = len(closes or [100.0] * 10)
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="1h"),
        "open": closes or [100.0] * n,
        "high": closes or [100.0] * n,
        "low": closes or [100.0] * n,
        "close": closes or [100.0] * n,
        "volume": [1000.0] * n,
        "enter_long": [0] * n,
        "exit_long": [0] * n,
    })
    return runner, pm, ex, df


class TestRunnerGates:
    def test_use_exit_signal_false_blocks(self):
        class Quiet(IStrategy):
            use_exit_signal = False

        runner, pm, _, df = make_runner(Quiet())
        trade = open_long(pm)
        df.loc[df.index[-1], "exit_long"] = 1
        runner._check_exit_signals("BTC/USDT", df, 100.0, datetime.now())
        assert pm.get_trade_for_pair("BTC/USDT") is not None

    def test_exit_profit_only_blocks_loser(self):
        class Greedy(IStrategy):
            exit_profit_only = True
            stoploss = 0
            minimal_roi = {}

        runner, pm, _, df = make_runner(Greedy())
        trade = open_long(pm, rate=100.0)
        df.loc[df.index[-1], "exit_long"] = 1
        runner._check_exit_signals("BTC/USDT", df, 90.0, datetime.now())
        assert pm.get_trade_for_pair("BTC/USDT") is not None

    def test_short_exit_signal_works(self):
        class Shorty(IStrategy):
            can_short = True

        runner, pm, _, df = make_runner(Shorty())
        trade = pm.open_trade(
            pair="BTC/USDT", rate=100.0, amount=200.0, stake_amount=20000.0,
            market_type=MarketType.CRYPTO, is_short=True,
        )
        df.loc[df.index[-1], "exit_short"] = 1
        runner._check_exit_signals("BTC/USDT", df, 90.0, datetime.now())
        assert pm.get_trade_for_pair("BTC/USDT") is None

    def test_limit_up_entry_skipped(self):
        runner, pm, ex, df = make_runner(IStrategy(), pair="600036.SH")
        closes = [40.0] * 9 + [44.0]
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=10, freq="1h"),
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": [1000.0] * 10, "enter_long": [0] * 9 + [1],
            "exit_long": [0] * 10,
        })
        runner._check_entry_signals("600036.SH", df, 44.0, datetime.now())
        assert pm.get_trade_for_pair("600036.SH") is None

    def test_limit_down_exit_blocked(self):
        runner, pm, _, df = make_runner(IStrategy(), pair="600036.SH")
        trade = pm.open_trade(
            pair="600036.SH", rate=40.0, amount=500.0, stake_amount=20000.0,
            market_type=MarketType.STOCK,
        )
        closes = [40.0] * 9 + [36.0]
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=10, freq="1h"),
            "open": closes, "high": closes, "low": closes, "close": closes,
            "volume": [1000.0] * 10, "enter_long": [0] * 10,
            "exit_long": [0] * 9 + [1],
        })
        runner._check_exit_signals("600036.SH", df, 36.0, datetime.now())
        assert pm.get_trade_for_pair("600036.SH") is not None

    def test_custom_exit_price_applied(self):
        class Discounter(IStrategy):
            def custom_exit_price(self, pair, trade, current_time,
                                  proposed_rate, current_profit,
                                  exit_tag, **k):
                return proposed_rate * 0.99

        runner, pm, _, df = make_runner(Discounter())
        trade = open_long(pm, rate=100.0)
        df.loc[df.index[-1], "exit_long"] = 1
        runner._check_exit_signals("BTC/USDT", df, 110.0, datetime.now())
        assert pm.get_trade_for_pair("BTC/USDT") is None
        closed = pm.get_closed_trades()[-1]
        assert closed.close_rate == pytest.approx(108.9)

    def test_runner_dca_adjust(self):
        class Grid(IStrategy):
            position_adjustment_enable = True
            stoploss = 0
            minimal_roi = {}

            def adjust_trade_position(self, trade, current_time,
                                      current_rate, current_profit,
                                      min_stake, max_stake,
                                      current_entry_rate, current_exit_rate,
                                      current_entry_profit,
                                      current_exit_profit, **k):
                return 10000.0

        runner, pm, _, df = make_runner(Grid())
        trade = open_long(pm, rate=100.0, stake=20000.0)
        runner._check_exit_signals("BTC/USDT", df, 90.0, datetime.now())
        assert pm.get_trade_for_pair("BTC/USDT") is not None
        assert trade.nr_of_successful_entries == 2
        assert trade.amount == pytest.approx(200 + 10000.0 / 90.0)
