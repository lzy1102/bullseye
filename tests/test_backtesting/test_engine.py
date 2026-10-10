"""
Test backtesting engine
"""
import pytest
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bullseye.backtesting.engine import BacktestEngine, BacktestDataProvider
from bullseye.backtesting.result import BacktestResult, BacktestTrade
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


def run_flat_backtest(strategy_cls, data, slippage: float = 0.0,
                      stake_amount: float = 100, initial_balance: float = 1000):
    """Run the backtest loop over flat in-memory data and return closed trades."""
    from bullseye.order.position_manager import PositionManager
    from bullseye.order.order_executor import OrderExecutor
    from bullseye.wallets.wallets import Wallets

    config = Config()
    config.set("dry_run_wallet", initial_balance)
    config.set("stake_amount", stake_amount)
    config.set("max_open_trades", 1)

    strategy = strategy_cls()
    pairlist = list(data.keys())
    wallets = Wallets(config, initial_balance=initial_balance)
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
    engine._slippage_rate = slippage
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
        stake_amount=stake_amount,
        initial_balance=initial_balance,
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
        # Stake 20000 @ flat 100 = 200 shares = 2 lots (A-share rule;
        # note tradable_balance_ratio 0.99 shaves available, so headroom
        # above exactly 1 lot is required).
        data = make_flat_data({"000001.SZ": 80})
        trades = run_flat_backtest(
            SingleTradeExitSignalStrategy, data,
            stake_amount=20000, initial_balance=100000,
        )

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

        # Fee-aware ROI: exits require NET >= 3% (gross minus both-side
        # fees), so ROI fills occur ~1 candle later than the old
        # gross-triggered baseline (which exited with net 2.89% < 3%).
        golden = [
            ("2024-01-01 05:00:00", "2024-01-01 19:00:00", 103.0, 97.85, "stoploss", -5.195),
            ("2024-01-01 19:00:00", "2024-01-02 02:00:00", 97.0, 100.5, "roi_0m", 3.404639),
            ("2024-01-02 02:00:00", "2024-01-02 05:00:00", 100.5, 95.475, "stoploss", -5.195),
            ("2024-01-02 05:00:00", "2024-01-02 12:00:00", 95.5, 99.0, "roi_0m", 3.461257),
            ("2024-01-02 12:00:00", "2024-01-02 15:00:00", 99.0, 94.05, "stoploss", -5.195),
            ("2024-01-02 15:00:00", "2024-01-02 22:00:00", 94.0, 97.5, "roi_0m", 3.519681),
            ("2024-01-02 22:00:00", "2024-01-03 01:00:00", 97.5, 92.625, "stoploss", -5.195),
            ("2024-01-03 01:00:00", "2024-01-03 07:00:00", 92.5, 95.5, "roi_0m", 3.04),
            ("2024-01-03 07:00:00", "2024-01-03 11:00:00", 95.5, 90.725, "stoploss", -5.195),
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


class TestEquityCurve:
    """Mark-to-market equity curve sampling and curve-based drawdown."""

    def test_equity_curve_via_run(self):
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

        config = Config()
        config.set("dry_run_wallet", 10000)
        config.set("stake_amount", 100)
        config.set("max_open_trades", 1)

        engine = BacktestEngine(config)
        result = engine.run(
            strategy_class=MixedExitStrategy,
            pairlist=["BTC/USDT"],
            timeframe="1h",
            initial_balance=10000,
            fee=0.001,
            data=data,
        )

        curve = result.equity_curve
        assert len(curve) > 40
        # Curve starts at initial balance and ends at final balance
        assert curve[0][1] == pytest.approx(10000)
        assert curve[-1][1] == pytest.approx(result.metrics.final_balance, abs=0.5)

    def test_max_drawdown_uses_mark_to_market_curve(self):
        """Intra-trade dip must show up in max_drawdown even though the
        trade later closes flat."""
        periods = 30
        dates = pd.date_range(start=datetime(2024, 1, 1), periods=periods, freq="1h")
        # Price: 100 -> spikes down to 80 mid-data -> back to 100 (trade closes flat)
        prices = [100.0] * periods
        for i in range(10, 20):
            prices[i] = 80.0
        data = {"BTC/USDT": pd.DataFrame({
            "date": dates, "open": prices, "high": prices,
            "low": prices, "close": prices, "volume": [1000.0] * periods,
        })}

        class HoldFlatStrategy(IStrategy):
            timeframe = "1h"
            startup_candle_count = 2
            minimal_roi = {}
            stoploss = 0  # disabled - hold through the dip

            def populate_indicators(self, dataframe, metadata):
                return dataframe

            def populate_entry_trend(self, dataframe, metadata):
                dataframe["enter_long"] = 1
                return dataframe

            def populate_exit_trend(self, dataframe, metadata):
                dataframe["exit_long"] = 0
                return dataframe

        config = Config()
        config.set("dry_run_wallet", 10000)
        config.set("stake_amount", 5000)
        config.set("max_open_trades", 1)

        engine = BacktestEngine(config)
        result = engine.run(
            strategy_class=HoldFlatStrategy,
            pairlist=["BTC/USDT"],
            timeframe="1h",
            initial_balance=10000,
            fee=0.001,
            data=data,
        )

        # The single trade closes flat, so closed-trade-based accounting
        # would report ~0% drawdown... but half the account rides through
        # the 20% spike-down: equity dips 10000 -> 9000 => 10% drawdown.
        assert len(result.trades) >= 1
        assert result.metrics.max_drawdown == pytest.approx(10.0, rel=0.02)
        assert result.metrics.max_drawdown_abs == pytest.approx(1000.0, rel=0.05)
        equity_df = result.get_equity_dataframe()
        assert list(equity_df.columns) == ["date", "equity"]

    def test_result_save_load_roundtrips_equity_curve(self, tmp_path):
        result = BacktestResult(
            strategy_name="Test",
            equity_curve=[
                (datetime(2024, 1, 1), 1000.0),
                (datetime(2024, 1, 2), 1100.0),
                (datetime(2024, 1, 3), 990.0),
            ],
        )
        filepath = str(tmp_path / "curve.json")
        result.save(filepath)
        loaded = BacktestResult.load(filepath)

        assert len(loaded.equity_curve) == 3
        assert loaded.equity_curve[0][0] == datetime(2024, 1, 1)
        assert loaded.equity_curve[2][1] == pytest.approx(990.0)


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

    def test_signal_misalignment_raises(self):
        """A strategy that drops rows in populate_* must fail loudly instead
        of silently trading on misaligned signals."""
        from bullseye.exceptions import BacktestError

        class RowDroppingStrategy(FlatTestStrategy):
            def populate_indicators(self, dataframe, metadata):
                # Simulates a strategy dropping warm-up rows
                return dataframe.iloc[:-5]

        data = make_flat_data({"BTC/USDT": 30})
        with pytest.raises(BacktestError, match="Signal misalignment"):
            run_flat_backtest(RowDroppingStrategy, data)


class TestSlippage:
    """Adverse fill pricing: buys higher, sells lower, stoploss worse."""

    def test_zero_slippage_preserves_prices(self):
        data = make_flat_data({"BTC/USDT": 30})
        trades = run_flat_backtest(ImmediateExitStrategy, data, slippage=0.0)
        assert trades[0].open_rate == pytest.approx(100.0)
        assert trades[0].close_rate == pytest.approx(100.0)

    def test_entry_and_exit_are_slipped(self):
        data = make_flat_data({"BTC/USDT": 30})
        trades = run_flat_backtest(ImmediateExitStrategy, data, slippage=0.001)

        trade = trades[0]
        assert trade.open_rate == pytest.approx(100.0 * 1.001)   # buys higher
        assert trade.close_rate == pytest.approx(100.0 * 0.999)  # sells lower
        # Round trip loses roughly 2 * stake * slippage plus fees
        assert trade.profit_abs < 0

    def test_stoploss_fills_worse_than_stop_price(self):
        # Price crashes through the stop level
        data = {"BTC/USDT": pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=40, freq="1h"),
            "open": [100.0] * 12 + [85.0] * 28,
            "high": [100.0] * 12 + [85.0] * 28,
            "low": [100.0] * 12 + [85.0] * 28,
            "close": [100.0] * 12 + [85.0] * 28,
            "volume": [1000.0] * 40,
        })}

        class StopStrategy(FlatTestStrategy):
            startup_candle_count = 5
            stoploss = -0.05

        trades = run_flat_backtest(StopStrategy, data, slippage=0.001)

        stops = [t for t in trades if t.exit_reason == "stoploss"]
        assert len(stops) == 1
        trade = stops[0]
        # Stop level derives from the slipped entry (-5% for long)
        expected_stop = trade.open_rate * (1 - 0.05)
        # Fill is worse than the stop level (long exits sell lower)
        assert trade.close_rate < expected_stop
        assert trade.close_rate == pytest.approx(expected_stop * 0.999)

    def test_config_fallback_applies(self):
        """backtest.slippage config is honored when no explicit value given."""
        from bullseye.backtesting.engine import BacktestEngine

        config = Config()
        config.set("backtest.slippage", 0.002)
        engine = BacktestEngine(config)

        data = make_flat_data({"BTC/USDT": 20})
        result = engine.run(
            strategy_class=FlatTestStrategy,
            pairlist=["BTC/USDT"],
            timeframe="1h",
            data=data,
            initial_balance=1000,
        )
        assert engine._slippage_rate == pytest.approx(0.002)
        assert len(result.trades) == 1
        assert result.trades[0].open_rate == pytest.approx(100.0 * 1.002)


class TestAshareTradingRules:
    """A-share lot-size (100 shares) and limit-up/down fill rules."""

    def test_below_one_lot_rejected(self):
        # Stake 100 @ 100 = 1 share < 1 lot -> no trade for stocks...
        data = make_flat_data({"000001.SZ": 30})
        trades = run_flat_backtest(FlatTestStrategy, data,
                                   stake_amount=100, initial_balance=1000)
        assert len(trades) == 0
        # ...while the same stake still trades crypto.
        data = make_flat_data({"BTC/USDT": 30})
        trades = run_flat_backtest(FlatTestStrategy, data,
                                   stake_amount=100, initial_balance=1000)
        assert len(trades) == 1

    def test_lot_rounding_down(self):
        # Stake 25000 @ 100 = 250 shares -> 200 (2 lots), stake 20000.
        data = make_flat_data({"000001.SZ": 30})
        trades = run_flat_backtest(FlatTestStrategy, data,
                                   stake_amount=25000,
                                   initial_balance=100000)
        assert len(trades) == 1
        assert trades[0].amount == pytest.approx(200.0)
        assert trades[0].stake_amount == pytest.approx(20000.0)

    def test_limit_up_entry_skipped(self):
        # Day opens flat then gaps to limit-up (100 -> 110): buys rejected.
        dates = pd.date_range("2024-01-01", periods=30, freq="1h")
        closes = [100.0] * 12 + [110.0] * 18
        data = {"000001.SZ": pd.DataFrame({
            "date": dates, "open": closes,
            "high": closes, "low": closes, "close": closes,
            "volume": [1000.0] * 30,
        })}
        trades = run_flat_backtest(FlatTestStrategy, data,
                                   stake_amount=20000,
                                   initial_balance=100000)
        # Entries only before the limit-up lock; nothing opens at 110.
        assert all(t.open_rate < 110.0 for t in trades)

    def test_limit_down_exit_blocked(self):
        # Open flat, then lock at limit-down (100 -> 90) with exit
        # signals firing: the position cannot be sold into the lock.
        dates = pd.date_range("2024-01-01", periods=40, freq="1h")
        closes = [100.0] * 12 + [90.0] * 28
        data = {"000001.SZ": pd.DataFrame({
            "date": dates, "open": closes,
            "high": closes, "low": closes, "close": closes,
            "volume": [1000.0] * 40,
        })}
        trades = run_flat_backtest(ImmediateExitStrategy, data,
                                   stake_amount=20000,
                                   initial_balance=100000)
        assert trades
        locked_date = dates[12]  # first 90 candle: 10% gap from prev 100
        # No signal-driven fill may happen on the locked candle itself.
        assert all(
            not (t.exit_date == locked_date and t.exit_reason == "exit_signal")
            for t in trades
        )
        # The position open at 100 is carried through the lock into 90.
        assert any(
            t.open_rate == pytest.approx(100.0)
            and t.close_rate == pytest.approx(90.0)
            for t in trades
        )

    def test_price_limit_ratio(self):
        from bullseye.backtesting.engine import BacktestEngine

        assert BacktestEngine._price_limit_ratio("000001.SZ") == pytest.approx(0.10)
        assert BacktestEngine._price_limit_ratio("300001.SZ") == pytest.approx(0.20)
        assert BacktestEngine._price_limit_ratio("688001.SH") == pytest.approx(0.20)
        assert BacktestEngine._price_limit_ratio("BTC/USDT") == pytest.approx(0.10)

    def test_rules_opt_out(self):
        from bullseye.backtesting.engine import BacktestEngine
        from bullseye.order.position_manager import PositionManager
        from bullseye.order.order_executor import OrderExecutor
        from bullseye.wallets.wallets import Wallets
        from bullseye.backtesting.engine import BacktestDataProvider

        config = Config()
        config.set("dry_run_wallet", 1000)
        config.set("stake_amount", 100)
        config.set("max_open_trades", 1)
        config.set("backtest.enforce_lot_size", False)
        data = make_flat_data({"000001.SZ": 30})
        strategy = FlatTestStrategy()
        wallets = Wallets(config, initial_balance=1000)
        pm = PositionManager(config, wallets)
        pm.set_strategy(strategy)
        oe = OrderExecutor(config, pm, wallets)
        oe.set_strategy(strategy)
        bt_dp = BacktestDataProvider(data, ["000001.SZ"])
        strategy.dp = bt_dp
        strategy.wallets = wallets
        strategy.config = config.to_dict()
        engine = BacktestEngine(config)
        engine._fee_rate = 0.001
        trades = engine._run_backtest_loop(
            strategy=strategy, data=data, pairlist=["000001.SZ"],
            timeframe="1h", wallets=wallets, position_manager=pm,
            order_executor=oe, bt_dp=bt_dp, max_open_trades=1,
            stake_amount=100, initial_balance=1000,
        )
        assert len(trades) == 1


class TestRiskMetrics:
    """Ulcer/VaR/CVaR/SQN/Kelly/exposure math."""

    def _result(self):
        dates = pd.date_range("2024-01-01", periods=6, freq="1d")
        # Equity: 100 -> 90 (-10% dip) -> 100 -> 110 -> 105 -> 115
        equity = [100.0, 90.0, 100.0, 110.0, 105.0, 115.0]
        trades = [
            BacktestTrade(
                pair="BTC/USDT", entry_date=dates[0], exit_date=dates[2],
                open_rate=100.0, close_rate=100.0, amount=1.0,
                stake_amount=100.0, profit_abs=10.0, profit_pct=10.0,
                exit_reason="roi", trade_duration=48.0,
            ),
            BacktestTrade(
                pair="BTC/USDT", entry_date=dates[2], exit_date=dates[4],
                open_rate=100.0, close_rate=95.0, amount=1.0,
                stake_amount=100.0, profit_abs=-5.0, profit_pct=-5.0,
                exit_reason="stoploss", trade_duration=48.0,
            ),
        ]
        result = BacktestResult(
            strategy_name="T",
            trades=trades,
            equity_curve=list(zip(dates, equity)),
        )
        result.calculate_metrics(initial_balance=100.0)
        return result

    def test_ulcer_positive_on_dip(self):
        m = self._result().metrics
        assert m.ulcer_index > 0
        # Flat curve has zero ulcer.
        dates = pd.date_range("2024-01-01", periods=5, freq="1d")
        flat = BacktestResult(
            strategy_name="F",
            equity_curve=[(d, 100.0) for d in dates],
        )
        flat.calculate_metrics(initial_balance=100.0)
        assert flat.metrics.ulcer_index == pytest.approx(0.0)

    def test_var_cvar_ordering(self):
        m = self._result().metrics
        assert m.var_99 <= m.var_95
        assert m.cvar_95 <= m.var_95 + 1e-9
        assert m.cvar_99 <= m.var_99 + 1e-9

    def test_sqn_kelly(self):
        m = self._result().metrics
        # 1 win (+10), 1 loss (-5): positive expectancy, partial Kelly.
        assert m.sqn > 0
        assert 0 < m.kelly < 1

    def test_exposure(self):
        m = self._result().metrics
        # In market 4 of 4 days span -> 100%.
        assert m.exposure_pct == pytest.approx(100.0)
        empty = BacktestResult(strategy_name="E")
        empty.calculate_metrics(initial_balance=100.0)
        assert empty.metrics.exposure_pct == pytest.approx(0.0)

    def test_roundtrip(self, tmp_path):
        result = self._result()
        path = str(tmp_path / "risk.json")
        result.save(path)
        loaded = BacktestResult.load(path)
        # to_dict rounds for JSON; roundtrip keeps display precision.
        assert loaded.metrics.ulcer_index == pytest.approx(
            result.metrics.ulcer_index, abs=0.01
        )
        assert loaded.metrics.beta == pytest.approx(
            result.metrics.beta, abs=0.01
        )
        assert loaded.metrics.sqn == pytest.approx(
            result.metrics.sqn, abs=0.01
        )


class TestBenchmark:
    """Benchmark-relative metrics (excess/TE/IR/beta/alpha)."""

    def _result(self, bench_closes):
        dates = pd.date_range("2024-01-01", periods=5, freq="1d")
        equity = [100.0, 110.0, 121.0, 133.1, 146.41]  # +10%/day
        trades = [BacktestTrade(
            pair="BTC/USDT", entry_date=dates[0], exit_date=dates[-1],
            open_rate=100.0, close_rate=146.41, amount=1.0,
            stake_amount=100.0, profit_abs=46.41, profit_pct=46.41,
            exit_reason="force_exit", trade_duration=96.0,
        )]
        result = BacktestResult(
            strategy_name="T", trades=trades,
            equity_curve=list(zip(dates, equity)),
        )
        bench = pd.DataFrame({"date": dates, "close": bench_closes})
        result.calculate_metrics(initial_balance=100.0, benchmark=bench)
        return result

    def test_identical_benchmark(self):
        m = self._result([100.0, 110.0, 121.0, 133.1, 146.41]).metrics
        assert m.beta == pytest.approx(1.0)
        assert m.alpha == pytest.approx(0.0, abs=1e-6)
        assert m.excess_return_pct == pytest.approx(0.0)
        assert m.information_ratio == pytest.approx(0.0)

    def test_flat_benchmark(self):
        m = self._result([1000.0] * 5).metrics
        assert m.benchmark_return_pct == pytest.approx(0.0)
        assert m.excess_return_pct == pytest.approx(46.41)
        assert m.beta == pytest.approx(0.0)
        assert m.tracking_error > 0

    def test_engine_run_with_benchmark_df(self):
        data = make_flat_data({"BTC/USDT": 30})
        dates = pd.date_range("2024-01-01", periods=30, freq="1h")
        bench = pd.DataFrame({
            "date": dates, "close": [100.0 + i * 0.1 for i in range(30)],
        })
        config = Config()
        config.set("dry_run_wallet", 1000)
        config.set("stake_amount", 100)
        config.set("max_open_trades", 1)
        engine = BacktestEngine(config)
        result = engine.run(
            strategy_class=FlatTestStrategy, pairlist=["BTC/USDT"],
            timeframe="1h", data=data, initial_balance=1000,
            benchmark=bench,
        )
        assert result.metrics.benchmark_return_pct != 0
        assert result.config.get("benchmark") is None

    def test_missing_benchmark_pair_warns(self, tmp_path):
        config = Config()
        config.set("datadir", str(tmp_path / "nodata"))
        engine = BacktestEngine(config)
        data = make_flat_data({"BTC/USDT": 30})
        result = engine.run(
            strategy_class=FlatTestStrategy, pairlist=["BTC/USDT"],
            timeframe="1h", data=data, initial_balance=1000,
            benchmark="000300.SH",
        )
        assert result.metrics.beta == pytest.approx(0.0)
        assert result.metrics.benchmark_return_pct == pytest.approx(0.0)


class TestGridAdjust:
    """adjust_trade_position averaging-down and never-sell-red exits."""

    def _dip_data(self):
        import numpy as np

        n = 120
        px = np.concatenate([np.linspace(40, 28, 60), np.linspace(28, 42, 60)])
        dates = pd.date_range("2024-01-01", periods=n, freq="1h")
        return {"600036.SH": pd.DataFrame({
            "date": dates, "open": px, "high": px * 1.005,
            "low": px * 0.995, "close": px, "volume": [10000.0] * n,
        })}

    def test_grid_adds_and_exits_profitable(self):
        sys.path.insert(0, str(Path(__file__).parent.parent.parent
                               / "user_data" / "strategies"))
        from GridBank10 import GridBank10

        config = Config()
        config.set("dry_run_wallet", 200000)
        config.set("stake_amount", 12000)
        config.set("max_open_trades", 1)
        engine = BacktestEngine(config)
        result = engine.run(
            strategy_class=GridBank10, pairlist=["600036.SH"],
            timeframe="1h", data=self._dip_data(),
            initial_balance=200000, fee=0.001,
        )
        assert result.metrics.total_trades >= 1
        first = result.trades[0]
        # Averaged down across several tranches (more than one lot).
        assert first.amount > 300
        assert first.stake_amount > 12000
        # Entry count recorded (1 initial + DCA adds).
        assert first.entries > 1
        assert all(t.entries >= 1 for t in result.trades)
        # Average cost below the initial ~40 fill.
        assert first.open_rate < 40.0
        # No losing signal exits (force_exit at data end excepted).
        for t in result.trades:
            if t.exit_reason != "force_exit":
                assert t.profit_abs > 0, t

    def test_adjust_disabled_by_default(self):
        # FlatTestStrategy has no position_adjustment_enable: single lot.
        data = make_flat_data({"600036.SH": 30})
        trades = run_flat_backtest(FlatTestStrategy, data,
                                   stake_amount=20000,
                                   initial_balance=100000)
        assert len(trades) == 1
        assert trades[0].amount == pytest.approx(200.0)


class TestCustomStoploss:
    """use_custom_stoploss reprices the stop level every candle."""

    def test_custom_stop_triggers(self):
        # Drift down 0.2%/candle: static -50% never hits, custom -0.5%
        # trails the (falling) entry... use fixed custom level instead.
        dates = pd.date_range("2024-01-01", periods=40, freq="1h")
        prices = [100.0 - i * 0.2 for i in range(40)]
        data = {"BTC/USDT": pd.DataFrame({
            "date": dates, "open": prices, "high": prices,
            "low": prices, "close": prices, "volume": [1000.0] * 40,
        })}

        class FixedCustom(FlatTestStrategy):
            stoploss = -0.50
            use_custom_stoploss = True

            def custom_stoploss(self, pair, trade, current_time,
                                current_rate, current_profit, **kwargs):
                return -0.01  # 1% below average entry, always

        trades = run_flat_backtest(FixedCustom, data)
        assert len(trades) >= 1
        assert trades[0].exit_reason == "stoploss"
        # Static -50% on the same slope never triggers before force_exit.
        class StaticWide(FlatTestStrategy):
            stoploss = -0.50

        wide = run_flat_backtest(StaticWide, data)
        assert wide[0].exit_reason == "force_exit"

    def test_invalid_return_ignored(self):
        data = make_flat_data({"BTC/USDT": 30})

        class BadReturn(FlatTestStrategy):
            stoploss = -1.0
            minimal_roi = {}
            use_custom_stoploss = True

            def custom_stoploss(self, pair, trade, current_time,
                                current_rate, current_profit, **kwargs):
                return "nonsense"

        trades = run_flat_backtest(BadReturn, data)
        assert len(trades) == 1  # no crash, normal close


class TestOrderFilled:
    """order_filled fires on entry and exit fills with fill details."""

    def test_entry_and_exit_fills(self):
        data = make_flat_data({"BTC/USDT": 30})
        seen = []

        class Recording(ImmediateExitStrategy):
            def order_filled(self, pair, trade, order, current_time,
                             **kwargs):
                seen.append((pair, order.ft_order_side, order.price,
                             order.amount))

        run_flat_backtest(Recording, data)
        sides = [s for _, s, _, _ in seen]
        assert "buy" in sides and "sell" in sides
        # Every entry fill is followed by an exit fill.
        assert len(seen) % 2 == 0
        for _, _, price, amount in seen:
            assert price > 0 and amount > 0

    def test_crashing_callback_does_not_break_run(self):
        data = make_flat_data({"BTC/USDT": 30})

        class Boom(FlatTestStrategy):
            def order_filled(self, pair, trade, order, current_time,
                             **kwargs):
                raise RuntimeError("boom")

        trades = run_flat_backtest(Boom, data)
        assert len(trades) == 1


class TestStockDownloadHelpers:
    """KlineData -> OHLCV conversion and stock download wiring."""

    def test_klines_to_ohlcv_df(self):
        from datetime import datetime as _dt
        from bullseye.commands.data_commands import _klines_to_ohlcv_df
        from bullseye.trader.object.kline import KlineData

        klines = [
            KlineData(symbol="000001.SZ", interval="5m",
                      datetime=_dt(2024, 1, 2, 10, 0),
                      open_price=10.0, high_price=10.5,
                      low_price=9.9, close_price=10.2, volume=1000.0),
            KlineData(symbol="000001.SZ", interval="5m",
                      datetime=_dt(2024, 1, 2, 10, 5),
                      open_price=10.2, high_price=10.3,
                      low_price=10.0, close_price=10.1, volume=800.0),
        ]
        df = _klines_to_ohlcv_df(klines)
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
        assert len(df) == 2
        assert df.iloc[0]["close"] == pytest.approx(10.2)

    def test_download_stock_dry_run(self, tmp_path, monkeypatch):
        from bullseye.commands.data_commands import _download_data_impl
        from bullseye.configuration.config import Config

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "datadir: user_data/data\nstock:\n  datafeed: akshare\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        # Dry run must not touch the network.
        _download_data_impl(
            exchange=None, pairs="000001.SZ", timeframes="5m", days=5,
            timerange=None, data_format="parquet", prepend=False, erase=False,
            config=str(cfg_path), dry_run=True, market="stock",
            datafeed="akshare", adjust="qfq",
        )

    def test_download_defaults_to_qfq(self, tmp_path, monkeypatch):
        from datetime import datetime as _dt
        from bullseye.commands import data_commands as dc
        from bullseye.trader.object.kline import KlineData

        seen = {}

        class RecordingFeed:
            def init(self):
                pass

            def get_supported_intervals(self):
                return ["5m"]

            def query_history(self, symbol, interval, start=None, end=None,
                              limit=None, adjust=None):
                seen["adjust"] = adjust
                return [KlineData(
                    symbol=symbol, interval=interval,
                    datetime=_dt(2024, 1, 2, 10, 0),
                    open_price=10.0, high_price=10.5, low_price=9.9,
                    close_price=10.2, volume=1000.0)]

            def get_dividends(self, symbol, start=None, end=None):
                return []

            def close(self):
                pass

        monkeypatch.setattr(
            "bullseye.data.datafeed.akshare_datafeed.AKShareDatafeed",
            RecordingFeed,
        )
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("datadir: user_data/data\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        dc._download_data_impl(
            exchange=None, pairs="000001.SZ", timeframes="5m", days=5,
            timerange=None, data_format="json",
            prepend=False, erase=False, config=str(cfg_path), dry_run=False,
            market="stock", datafeed="akshare", adjust=None,
        )
        assert seen.get("adjust") == "qfq"
        import json as _json

        meta = _json.loads(
            (tmp_path / "user_data" / "data" / "000001.SZ-5m.meta.json")
            .read_text(encoding="utf-8")
        )
        assert meta["adjust"] == "qfq"
        divs = _json.loads(
            (tmp_path / "user_data" / "data" / "000001.SZ.dividends.json")
            .read_text(encoding="utf-8")
        )
        assert divs["symbol"] == "000001.SZ"

    def test_download_stock_with_stub_feed(self, tmp_path, monkeypatch):
        import pandas as pd  # noqa: F401
        from datetime import datetime as _dt
        from bullseye.commands import data_commands as dc
        from bullseye.trader.object.kline import KlineData

        class StubFeed:
            def init(self):
                pass

            def get_supported_intervals(self):
                return ["5m", "1d"]

            def query_history(self, symbol, interval, start=None, end=None,
                              limit=None, adjust=None):
                assert symbol == "000001.SZ"
                return [KlineData(
                    symbol=symbol, interval=interval,
                    datetime=_dt(2024, 1, 2, 10, 0),
                    open_price=10.0, high_price=10.5, low_price=9.9,
                    close_price=10.2, volume=1000.0)]

            def close(self):
                pass

        monkeypatch.setattr(
            "bullseye.data.datafeed.akshare_datafeed.AKShareDatafeed",
            StubFeed,
        )

        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("datadir: user_data/data\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        dc._download_data_impl(
            exchange=None, pairs="000001.SZ", timeframes="5m", days=5,
            timerange="20240101-20240105", data_format="parquet",
            prepend=False, erase=False, config=str(cfg_path), dry_run=False,
            market="stock", datafeed="akshare", adjust=None,
        )
        saved = tmp_path / "user_data" / "data" / "000001.SZ-5m.parquet"
        assert saved.exists()
        df = pd.read_parquet(saved)
        assert len(df) == 1
        assert df.iloc[0]["close"] == pytest.approx(10.2)


class TestAdjustValidation:
    """Stock file adjustment口径 must match the declared stock.adjust."""

    def _write_stock_file(self, tmp_path, pair="000001.SZ", timeframe="1d",
                          adjust="qfq", price=10.0):
        import json as _json
        from bullseye.commands.data_commands import _save_ohlcv_df

        dates = pd.date_range("2024-01-01", periods=30, freq="1h")
        df = pd.DataFrame({
            "date": dates, "open": price, "high": price, "low": price,
            "close": price, "volume": [1000.0] * 30,
        })
        datadir = tmp_path / "user_data" / "data"
        meta = None if adjust == "legacy" else {"adjust": adjust,
                                                "datafeed": "test"}
        _save_ohlcv_df(df, str(datadir), pair, timeframe, "json",
                       prepend=False, erase=True, meta=meta)
        return datadir

    def _engine(self, tmp_path, declared):
        config = Config()
        config.set("datadir", str(tmp_path / "user_data" / "data"))
        config.set("stock.adjust", declared)
        config.set("dry_run_wallet", 100000)
        config.set("stake_amount", 20000)
        config.set("max_open_trades", 1)
        return BacktestEngine(config)

    def test_matching_adjust_passes(self, tmp_path):
        self._write_stock_file(tmp_path, adjust="qfq")
        engine = self._engine(tmp_path, "qfq")
        result = engine.run(
            strategy_class=FlatTestStrategy, pairlist=["000001.SZ"],
            timeframe="1d", initial_balance=100000,
        )
        assert result.metrics.total_trades == 1

    def test_mismatch_raises(self, tmp_path):
        from bullseye.exceptions import BacktestError

        self._write_stock_file(tmp_path, adjust=None)
        engine = self._engine(tmp_path, "qfq")
        with pytest.raises(BacktestError, match="Adjustment mismatch"):
            engine.run(
                strategy_class=FlatTestStrategy, pairlist=["000001.SZ"],
                timeframe="1d", initial_balance=100000,
            )

    def test_legacy_file_warns_only(self, tmp_path, caplog):
        import logging as _logging

        self._write_stock_file(tmp_path, adjust="legacy")
        engine = self._engine(tmp_path, "qfq")
        with caplog.at_level(_logging.WARNING):
            result = engine.run(
                strategy_class=FlatTestStrategy, pairlist=["000001.SZ"],
                timeframe="1d", initial_balance=100000,
            )
        assert result.metrics.total_trades == 1
        assert any("no .meta.json sidecar" in r.message for r in caplog.records)

    def test_crypto_untouched(self, tmp_path):
        self._write_stock_file(tmp_path, pair="BTC/USDT", timeframe="1h",
                               adjust=None)
        config = Config()
        config.set("datadir", str(tmp_path / "user_data" / "data"))
        engine = BacktestEngine(config)
        result = engine.run(
            strategy_class=FlatTestStrategy, pairlist=["BTC/USDT"],
            timeframe="1h", initial_balance=1000,
        )
        assert result.metrics.total_trades == 1


class TestDividends:
    """Ex-date cash dividends are credited to holders of record."""

    def test_dividend_cash_credited(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="1h")
        data = {"000001.SZ": pd.DataFrame({
            "date": dates, "open": [10.0] * 30, "high": [10.0] * 30,
            "low": [10.0] * 30, "close": [10.0] * 30,
            "volume": [1000.0] * 30,
        })}
        ex_date = dates[15].date().isoformat()
        config = Config()
        config.set("dry_run_wallet", 100000)
        config.set("stake_amount", 20000)
        config.set("max_open_trades", 1)
        engine = BacktestEngine(config)
        result = engine.run(
            strategy_class=FlatTestStrategy, pairlist=["000001.SZ"],
            timeframe="1h", data=data, initial_balance=100000,
            dividends={"000001.SZ": [{"ex_date": ex_date, "cash_div": 0.5}]},
        )
        # 2000 shares (20000/10) x 0.5 x (1 - 0.1 tax) = 900.
        assert result.config["dividends_paid"] == pytest.approx(900.0)
        assert result.metrics.total_profit == pytest.approx(
            result.trades[0].profit_abs + 900.0
        )

    def test_dividend_entries_parsed(self):
        from bullseye.backtesting.engine import BacktestEngine as _E

        entries = _E._parse_dividend_entries([
            {"ex_date": "2024-06-15", "cash_div": 0.5},
            {"ex_date": None, "cash_div": 1.0},
            {"ex_date": "bad-date", "cash_div": 1.0},
            {"ex_date": "2024-06-16", "cash_div": 0},
        ])
        assert len(entries) == 1
        assert entries[0][1] == pytest.approx(0.5)


class TestTuShareDividends:
    """TuShare dividend calendar parsing (stubbed pro API, no network)."""

    def test_get_dividends(self):
        from bullseye.data.datafeed.tushare_datafeed import TuShareDatafeed

        feed = TuShareDatafeed.__new__(TuShareDatafeed)

        class FakePro:
            def dividend(self, **kwargs):
                assert kwargs["ts_code"] == "000001.SZ"
                return pd.DataFrame([
                    {"ts_code": "000001.SZ", "div_proc": "实施",
                     "ex_date": "20240615", "cash_div": 0.5},
                    {"ts_code": "000001.SZ", "div_proc": "预案",
                     "ex_date": None, "cash_div": 0.3},
                    {"ts_code": "000001.SZ", "div_proc": "实施",
                     "ex_date": "20230615", "cash_div": 0.0},
                ])

        feed._ts_pro = FakePro()
        feed._ts = None
        divs = TuShareDatafeed.get_dividends(feed, "000001.SZ")
        assert len(divs) == 1
        assert divs[0]["cash_div"] == pytest.approx(0.5)

    def test_base_returns_empty(self):
        from bullseye.data.datafeed.base import BaseDatafeed

        assert BaseDatafeed.get_dividends(object(), "000001.SZ") == []


class TestBacktestParamsAutoDiscovery:
    """Backtests auto-apply a sibling {Strategy}.json unless disabled."""

    def _write_strategy(self, tmp_path, dirname="bt_strats"):
        import textwrap

        strat_dir = tmp_path / dirname
        strat_dir.mkdir(exist_ok=True)
        (strat_dir / "JsonStrat.py").write_text(textwrap.dedent("""\
            from bullseye.strategy.interface import IStrategy

            class JsonStrat(IStrategy):
                timeframe = "1h"
                startup_candle_count = 2
                minimal_roi = {"0": 100.0}

                def populate_indicators(self, dataframe, metadata):
                    return dataframe

                def populate_entry_trend(self, dataframe, metadata):
                    dataframe["enter_long"] = 1
                    return dataframe

                def populate_exit_trend(self, dataframe, metadata):
                    dataframe["exit_long"] = 0
                    return dataframe
            """), encoding="utf-8")
        return strat_dir

    def _run(self, tmp_path, dirname="bt_strats", **kwargs):
        import json as _json

        strat_dir = self._write_strategy(tmp_path, dirname)
        (strat_dir / "JsonStrat.json").write_text(_json.dumps({
            "params": {"roi": {"0": 0.0}},
        }), encoding="utf-8")
        config = Config()
        config.set("strategy_path", str(strat_dir))
        config.set("dry_run_wallet", 10000)
        config.set("stake_amount", 100)
        config.set("max_open_trades", 1)
        engine = BacktestEngine(config)
        # Rising prices: net profit stays positive so roi 0.0 exits
        # every candle (fee-aware ROI would never fire on flat data).
        prices = [100.0 + i for i in range(30)]
        data = {"BTC/USDT": pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30, freq="1h"),
            "open": prices, "high": [p + 0.5 for p in prices],
            "low": [p - 0.5 for p in prices], "close": prices,
            "volume": [1000.0] * 30,
        })}
        return engine.run(
            strategy_name="JsonStrat", pairlist=["BTC/USDT"],
            timeframe="1h", data=data, initial_balance=10000, **kwargs,
        )

    def test_sibling_json_applied(self, tmp_path):
        result = self._run(tmp_path)
        # json roi 0.0 exits on the first candle: many quick round-trips.
        assert result.metrics.total_trades > 1

    def test_empty_string_disables(self, tmp_path):
        result = self._run(tmp_path, dirname="bt_strats_b", params_file="")
        # class default roi 100.0 never reached: single forced exit.
        assert result.metrics.total_trades == 1
        assert result.trades[0].exit_reason == "force_exit"


class TestResultNaming:
    """{strategy}-{pairs}-{timeframe} file convention + organizer."""

    def test_save_uses_convention(self, tmp_path, monkeypatch):
        import json as _json

        monkeypatch.chdir(tmp_path)
        result = BacktestResult(
            strategy_name="BankMACross",
            trades=[BacktestTrade(
                pair="600036.SH",
                entry_date=datetime(2024, 1, 1),
                exit_date=datetime(2024, 1, 2),
                open_rate=30.0, close_rate=31.0, amount=600.0,
                stake_amount=18000.0, profit_abs=600.0, profit_pct=3.0,
                exit_reason="roi", trade_duration=24.0,
            )],
            config={"timeframe": "1d", "pairlist": ["600036.SH"]},
        )
        saved = result.save()
        name = saved.split("/")[-1].split("\\")[-1]
        assert name.startswith("BankMACross-600036.SH-1d-")
        assert name.endswith(".json")

    def test_organize_renames_legacy(self, tmp_path, monkeypatch):
        import json as _json
        from bullseye.commands.backtest_commands import (
            backtest_target_name,
        )
        from click.testing import CliRunner
        from bullseye.commands.backtest_commands import organize_results

        monkeypatch.chdir(tmp_path)
        legacy = (tmp_path / "user_data" / "backtest_results"
                  / "backtest-result-20240101_120000.json")
        legacy.parent.mkdir(parents=True)
        legacy.write_text(_json.dumps({
            "strategy": "GridBank10",
            "created_at": "2024-01-01T12:00:00",
            "config": {"timeframe": "5m", "pairlist": ["BTC/USDT"]},
            "metrics": {}, "trades": [],
        }), encoding="utf-8")

        assert backtest_target_name(
            {"strategy": "GridBank10",
             "created_at": "2024-01-01T12:00:00",
             "config": {"timeframe": "5m", "pairlist": ["BTC/USDT"]},
             "trades": []}
        ) == "GridBank10-BTCUSDT-5m-20240101120000.json"

        runner = CliRunner()
        cli_result = runner.invoke(organize_results, [])
        assert cli_result.exit_code == 0
        names = [p.name for p in legacy.parent.glob("*.json")]
        assert names == ["GridBank10-BTCUSDT-5m-20240101120000.json"]
