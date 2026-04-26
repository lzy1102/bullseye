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
