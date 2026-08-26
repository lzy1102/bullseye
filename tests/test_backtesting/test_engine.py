"""
Test backtesting engine
"""
import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bullseye.backtesting.engine import BacktestEngine, BacktestDataProvider
from bullseye.backtesting.result import BacktestResult, BacktestTrade, BacktestMetrics
from bullseye.configuration.config import Config
from bullseye.strategy.interface import IStrategy


class SimpleTestStrategy(IStrategy):
    """Simple strategy for testing - buys every candle."""

    timeframe = "1h"
    startup_candle_count = 10
    stoploss = -0.10
    minimal_roi = {"0": 0.10, "60": 0.05, "120": 0.02}

    def populate_indicators(self, dataframe, metadata):
        dataframe["sma"] = dataframe["close"].rolling(10).mean()
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe["enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = 0
        return dataframe


class NoEntryStrategy(IStrategy):
    """Strategy that never enters trades."""

    timeframe = "1h"
    startup_candle_count = 5

    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe["enter_long"] = 0
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = 0
        return dataframe


class FlatTestStrategy(IStrategy):
    """Always enters; no ROI/stoploss/trailing - trades only close via force_exit."""

    timeframe = "1h"
    startup_candle_count = 10
    minimal_roi = {}
    stoploss = -1.0
    trailing_stop = False

    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe["enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = 0
        return dataframe


class ImmediateExitStrategy(FlatTestStrategy):
    """Enters and exits on every candle - isolates settlement blocking behavior."""

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = 1
        return dataframe


class SingleTradeExitSignalStrategy(ImmediateExitStrategy):
    """Opens exactly ONE position; exit signal fires on every candle afterwards."""

    def __init__(self):
        self._entered = False

    def confirm_trade_entry(self, *args, **kwargs) -> bool:
        if self._entered:
            return False
        self._entered = True
        return True


def make_flat_data(pair_periods: Dict[str, int], start: str = "2024-01-01") -> Dict[str, pd.DataFrame]:
    """Create flat OHLCV data (all prices = 100) for each pair."""
    data = {}
    for pair, periods in pair_periods.items():
        dates = pd.date_range(start=start, periods=periods, freq="1h")
        data[pair] = pd.DataFrame({
            "date": dates,
            "open": [100.0] * periods,
            "high": [100.0] * periods,
            "low": [100.0] * periods,
            "close": [100.0] * periods,
            "volume": [1000.0] * periods,
        })
    return data


def run_flat_backtest(strategy_cls, data):
    """Run the backtest loop over flat in-memory data and return closed trades."""
    from bullseye.order.position_manager import PositionManager
    from bullseye.order.order_executor import OrderExecutor
    from bullseye.wallets.wallets import Wallets

    config = Config()
    config.set("dry_run_wallet", 1000)
    config.set("stake_amount", 100)
    config.set("max_open_trades", 1)

    strategy = strategy_cls()
    pairlist = list(data.keys())
    wallets = Wallets(config, initial_balance=1000)
    position_manager = PositionManager(config, wallets)
    position_manager.set_strategy(strategy)
    order_executor = OrderExecutor(config, position_manager, wallets)
    order_executor.set_strategy(strategy)
    bt_dp = BacktestDataProvider(data, pairlist)
    # Mirror what BacktestEngine.run() injects onto the strategy
    strategy.dp = bt_dp
    strategy.wallets = wallets
    strategy.config = config.to_dict()

    engine = BacktestEngine(config)
    engine._fee_rate = 0.001
    return engine._run_backtest_loop(
        strategy=strategy,
        data=data,
        pairlist=pairlist,
        timeframe="1h",
        wallets=wallets,
        position_manager=position_manager,
        order_executor=order_executor,
        bt_dp=bt_dp,
        max_open_trades=1,
        stake_amount=100,
        initial_balance=1000,
    )


def create_test_data(
    pair: str = "BTC/USDT",
    timeframe: str = "1h",
    periods: int = 200,
    start_price: float = 100.0,
    trend: str = "up",
) -> pd.DataFrame:
    """Create test OHLCV data."""
    dates = pd.date_range(
        start=datetime(2024, 1, 1),
        periods=periods,
        freq=timeframe,
    )

    if trend == "up":
        prices = [start_price + i * 0.5 for i in range(periods)]
    elif trend == "down":
        prices = [start_price - i * 0.3 for i in range(periods)]
    else:
        prices = [start_price + (i % 20 - 10) * 0.5 for i in range(periods)]

    return pd.DataFrame({
        "date": dates,
        "open": prices,
        "high": [p + 1.0 for p in prices],
        "low": [p - 0.5 for p in prices],
        "close": [p + 0.2 for p in prices],
        "volume": [1000.0] * periods,
    })


class TestBacktestResult:
    """Test BacktestResult class."""

    def test_empty_result(self):
        result = BacktestResult()
        assert result.strategy_name == ""
        assert len(result.trades) == 0

    def test_calculate_metrics_empty(self):
        result = BacktestResult()
        result.calculate_metrics(initial_balance=1000.0)
        assert result.metrics.total_trades == 0
        assert result.metrics.initial_balance == 1000.0

    def test_calculate_metrics_with_trades(self):
        trades = [
            BacktestTrade(
                pair="BTC/USDT",
                entry_date=datetime(2024, 1, 1),
                exit_date=datetime(2024, 1, 2),
                open_rate=100.0,
                close_rate=105.0,
                amount=1.0,
                stake_amount=100.0,
                profit_abs=5.0,
                profit_pct=5.0,
                exit_reason="roi",
                trade_duration=24.0,
            ),
            BacktestTrade(
                pair="ETH/USDT",
                entry_date=datetime(2024, 1, 3),
                exit_date=datetime(2024, 1, 4),
                open_rate=50.0,
                close_rate=48.0,
                amount=2.0,
                stake_amount=100.0,
                profit_abs=-2.0,
                profit_pct=-2.0,
                exit_reason="stoploss",
                trade_duration=24.0,
            ),
        ]
        result = BacktestResult(trades=trades)
        result.calculate_metrics(initial_balance=1000.0)

        assert result.metrics.total_trades == 2
        assert result.metrics.winning_trades == 1
        assert result.metrics.losing_trades == 1
        assert result.metrics.win_rate == 0.5
        assert result.metrics.total_profit == 3.0

    def test_to_dict(self):
        result = BacktestResult(strategy_name="TestStrategy")
        data = result.to_dict()
        assert data["strategy"] == "TestStrategy"

    def test_to_json(self):
        result = BacktestResult(strategy_name="TestStrategy")
        json_str = result.to_json()
        assert "TestStrategy" in json_str


class TestBacktestDataProvider:
    """Test BacktestDataProvider class."""

    def test_get_dataframe_up_to(self):
        data = {"BTC/USDT": create_test_data()}
        dp = BacktestDataProvider(data, ["BTC/USDT"])

        df = dp.get_dataframe_up_to("BTC/USDT", 50)
        assert len(df) == 50

    def test_get_dataframe_up_to_empty(self):
        dp = BacktestDataProvider({}, ["BTC/USDT"])
        df = dp.get_dataframe_up_to("BTC/USDT", 50)
        assert df.empty

    def test_current_whitelist(self):
        data = {"BTC/USDT": create_test_data()}
        dp = BacktestDataProvider(data, ["BTC/USDT"])
        assert dp.current_whitelist() == ["BTC/USDT"]

    def test_runmode(self):
        dp = BacktestDataProvider({}, [])
        assert dp.runmode() == "backtest"


class TestBacktestEngine:
    """Test BacktestEngine class."""

    def test_engine_creation(self):
        config = Config()
        engine = BacktestEngine(config)
        assert engine is not None

    def test_run_with_no_entry_strategy(self):
        config = Config()
        config.set("dry_run_wallet", 1000)
        config.set("stake_amount", 100)
        config.set("max_open_trades", 3)

        engine = BacktestEngine(config)

        data = {"BTC/USDT": create_test_data()}

        result = engine.run(
            strategy_class=NoEntryStrategy,
            pairlist=["BTC/USDT"],
            timeframe="1h",
            initial_balance=1000,
        )

        assert result is not None
        assert result.metrics.total_trades == 0

    def test_run_with_simple_strategy(self):
        config = Config()
        config.set("dry_run_wallet", 1000)
        config.set("stake_amount", 100)
        config.set("max_open_trades", 1)

        engine = BacktestEngine(config)

        result = engine.run(
            strategy_class=SimpleTestStrategy,
            pairlist=["BTC/USDT"],
            timeframe="1h",
            initial_balance=1000,
        )

        assert result is not None
        assert result.strategy_name == "SimpleTestStrategy"
        assert result.metrics.total_trades >= 0

    def test_timeframe_to_minutes(self):
        assert BacktestEngine._timeframe_to_minutes("1m") == 1
        assert BacktestEngine._timeframe_to_minutes("5m") == 5
        assert BacktestEngine._timeframe_to_minutes("1h") == 60
        assert BacktestEngine._timeframe_to_minutes("4h") == 240
        assert BacktestEngine._timeframe_to_minutes("1d") == 1440

    def test_fee_charged_exactly_once_per_side(self):
        """Regression: fee_open must not be double-charged.

        Flat prices -> zero gross profit. A single forced-exit trade should
        lose exactly fee_open + fee_close (= 2 * stake * fee_rate).
        """
        from bullseye.order.position_manager import PositionManager
        from bullseye.order.order_executor import OrderExecutor
        from bullseye.wallets.wallets import Wallets

        config = Config()
        config.set("dry_run_wallet", 1000)
        config.set("stake_amount", 100)
        config.set("max_open_trades", 1)

        periods = 50
        dates = pd.date_range(start=datetime(2024, 1, 1), periods=periods, freq="1h")
        flat = pd.DataFrame({
            "date": dates,
            "open": [100.0] * periods,
            "high": [100.0] * periods,
            "low": [100.0] * periods,
            "close": [100.0] * periods,
            "volume": [1000.0] * periods,
        })

        strategy = FlatTestStrategy()
        data = {"BTC/USDT": flat}
        pairlist = ["BTC/USDT"]
        wallets = Wallets(config, initial_balance=1000)
        position_manager = PositionManager(config, wallets)
        position_manager.set_strategy(strategy)
        order_executor = OrderExecutor(config, position_manager, wallets)
        order_executor.set_strategy(strategy)
        bt_dp = BacktestDataProvider(data, pairlist)

        engine = BacktestEngine(config)
        engine._fee_rate = 0.001

        trades = engine._run_backtest_loop(
            strategy=strategy,
            data=data,
            pairlist=pairlist,
            timeframe="1h",
            wallets=wallets,
            position_manager=position_manager,
            order_executor=order_executor,
            bt_dp=bt_dp,
            max_open_trades=1,
            stake_amount=100,
            initial_balance=1000,
        )

        assert len(trades) == 1
        expected_fees = 2 * 100 * 0.001
        assert trades[0].profit_abs == pytest.approx(-expected_fees)
        assert wallets.get_free("USDT") == pytest.approx(1000 - expected_fees)


class TestSettlementRestriction:
    """T+1 settlement must block same-day exits in backtesting."""

    def test_t1_stock_exit_blocked_until_settlement_date(self):
        """A-share pair: exit signals before the settlement date must be ignored."""
        data = make_flat_data({"000001.SZ": 80})
        trades = run_flat_backtest(SingleTradeExitSignalStrategy, data)

        assert len(trades) == 1
        trade = trades[0]
        from bullseye.order.settlement import get_settlement_date
        expected_settlement = get_settlement_date(trade.entry_date, "000001.SZ")

        # Exit signal fired on every candle yet exit only happened after T+1
        assert trade.exit_reason == "exit_signal"
        assert trade.exit_date >= expected_settlement
        # Entry at 2024-01-01 10:00 -> settlement 2024-01-02 09:30
        # -> first sellable hourly candle is 2024-01-02 10:00 (~24h hold)
        assert trade.trade_duration >= 23.0

    def test_t0_crypto_exits_immediately(self):
        """Crypto pair: no settlement restriction - round-trips every candle."""
        data = make_flat_data({"BTC/USDT": 30})
        trades = run_flat_backtest(ImmediateExitStrategy, data)

        assert len(trades) > 10
        for trade in trades:
            if trade.exit_reason == "force_exit":
                continue
            assert trade.trade_duration == pytest.approx(1.0)
            assert trade.exit_reason == "exit_signal"

    def test_precomputed_signals_golden_sequence(self):
        """Regression: signal precomputation must reproduce exact trade sequence.

        Golden baseline captured before the vectorized-signal refactor;
        guards against behavior drift when reading precomputed columns.
        """
        periods = 60
        dates = pd.date_range(start=datetime(2024, 1, 1), periods=periods, freq="1h")
        prices = []
        p = 100.0
        for i in range(periods):
            if i % 10 == 9:
                p -= 6.0
            else:
                p += 0.5
            prices.append(round(p, 2))
        data = {"BTC/USDT": pd.DataFrame({
            "date": dates, "open": prices,
            "high": [x + 0.3 for x in prices], "low": [x - 0.3 for x in prices],
            "close": prices, "volume": [1000.0] * periods,
        })}

        class MixedExitStrategy(IStrategy):
            timeframe = "1h"
            startup_candle_count = 5
            minimal_roi = {"0": 0.03}
            stoploss = -0.05

            def populate_indicators(self, dataframe, metadata):
                return dataframe

            def populate_entry_trend(self, dataframe, metadata):
                dataframe["enter_long"] = 1
                return dataframe

            def populate_exit_trend(self, dataframe, metadata):
                dataframe["exit_long"] = 0
                return dataframe

        trades = run_flat_backtest(MixedExitStrategy, data)

        golden = [
            ("2024-01-01 05:00:00", "2024-01-01 19:00:00", 103.0, 97.85, "stoploss", -5.195),
            ("2024-01-01 19:00:00", "2024-01-02 01:00:00", 97.0, 100.0, "roi_0m", 2.889691),
            ("2024-01-02 01:00:00", "2024-01-02 15:00:00", 100.0, 95.0, "stoploss", -5.195),
            ("2024-01-02 15:00:00", "2024-01-02 21:00:00", 94.0, 97.0, "roi_0m", 2.988298),
            ("2024-01-02 21:00:00", "2024-01-03 11:00:00", 97.0, 92.15, "stoploss", -5.195),
            ("2024-01-03 11:00:00", "2024-01-03 11:00:00", 91.0, 91.0, "force_exit", -0.2),
        ]
        assert len(trades) == len(golden)
        for trade, (entry, exit_, open_, close_, reason, profit) in zip(trades, golden):
            assert str(trade.entry_date) == entry
            assert str(trade.exit_date) == exit_
            assert trade.open_rate == pytest.approx(open_)
            assert trade.close_rate == pytest.approx(close_)
            assert trade.exit_reason == reason
            assert trade.profit_abs == pytest.approx(profit, abs=1e-6)


    def test_result_save_and_load(self, tmp_path):
        result = BacktestResult(
            strategy_name="TestStrategy",
            trades=[
                BacktestTrade(
                    pair="BTC/USDT",
                    entry_date=datetime(2024, 1, 1),
                    exit_date=datetime(2024, 1, 2),
                    open_rate=100.0,
                    close_rate=105.0,
                    amount=1.0,
                    stake_amount=100.0,
                    profit_abs=5.0,
                    profit_pct=5.0,
                    exit_reason="roi",
                    trade_duration=24.0,
                )
            ],
        )
        result.calculate_metrics(initial_balance=1000.0)

        filepath = str(tmp_path / "test_result.json")
        result.save(filepath)

        loaded = BacktestResult.load(filepath)
        assert loaded.strategy_name == "TestStrategy"
        assert len(loaded.trades) == 1
        assert loaded.trades[0].pair == "BTC/USDT"
