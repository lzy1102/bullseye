"""
Test the structured fee model (A-share commission min / stamp duty / transfer)
and its integration into backtesting.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from bullseye.backtesting.engine import BacktestEngine
from bullseye.configuration.config import Config
from bullseye.order.fees import FeeModel
from bullseye.strategy.interface import IStrategy


ASHARE_FEES = {
    "commission_rate": 0.00025,   # 万2.5
    "commission_min": 5.0,        # 不足5元按5元
    "stamp_duty_rate": 0.0005,    # 印花税 卖出单边
    "transfer_fee_rate": 0.00001, # 过户费 双边
}


class TestFeeModelMath:
    def test_ashare_small_buy_min_commission(self):
        model = FeeModel(**ASHARE_FEES)
        # 10000 * 0.00025 = 2.5 -> lifted to 5; transfer = 0.1
        assert model.fee(10000.0, is_sell=False) == pytest.approx(5.1)

    def test_ashare_small_sell_includes_stamp_duty(self):
        model = FeeModel(**ASHARE_FEES)
        # commission 5 (min) + stamp 11000*0.0005=5.5 + transfer 0.11
        assert model.fee(11000.0, is_sell=True) == pytest.approx(10.61)

    def test_ashare_large_trade_no_min(self):
        model = FeeModel(**ASHARE_FEES)
        # commission 250 + transfer 10 (buy) / + stamp 500 (sell)
        assert model.fee(1_000_000.0, is_sell=False) == pytest.approx(260.0)
        assert model.fee(1_000_000.0, is_sell=True) == pytest.approx(760.0)

    def test_flat_model_unchanged(self):
        model = FeeModel(commission_rate=0.001)
        assert model.fee(1000.0, is_sell=False) == pytest.approx(1.0)
        assert model.fee(1000.0, is_sell=True) == pytest.approx(1.0)

    def test_non_positive_value(self):
        model = FeeModel(**ASHARE_FEES)
        assert model.fee(0.0, is_sell=True) == 0.0
        assert model.fee(-100.0, is_sell=False) == 0.0


class TestFeeModelFromConfig:
    def test_missing_config_returns_none(self):
        assert FeeModel.from_config(Config()) is None

    def test_backtest_section_takes_priority(self):
        config = Config()
        config.set("backtest.fees", ASHARE_FEES)
        config.set("fees", {"commission_rate": 0.5})  # ignored
        model = FeeModel.from_config(config)
        assert model is not None
        assert model.commission_rate == pytest.approx(0.00025)

    def test_top_level_fallback(self):
        config = Config()
        config.set("fees", {"commission_rate": 0.0003, "commission_min": 1.0})
        model = FeeModel.from_config(config)
        assert model is not None
        assert model.commission_rate == pytest.approx(0.0003)
        assert model.commission_min == pytest.approx(1.0)


class AlwaysEnterStrategy(IStrategy):
    timeframe = "1h"
    startup_candle_count = 10
    minimal_roi = {}
    stoploss = 0
    trailing_stop = False

    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe["enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = 0
        return dataframe


def flat_data(periods=30, price=100.0):
    return {"000001.SZ": pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=periods, freq="1h"),
        "open": [price] * periods,
        "high": [price] * periods,
        "low": [price] * periods,
        "close": [price] * periods,
        "volume": [1000.0] * periods,
    })}


class TestBacktestFeeIntegration:
    def run(self, config, **kwargs):
        engine = BacktestEngine(config)
        return engine.run(
            strategy_class=AlwaysEnterStrategy,
            pairlist=["000001.SZ"],
            timeframe="1h",
            initial_balance=1000,
            data=flat_data(),
            **kwargs,
        )

    def test_structured_fees_applied_to_trade(self):
        config = Config()
        config.set("dry_run_wallet", 1000)
        config.set("stake_amount", 100)
        config.set("max_open_trades", 1)
        config.set("backtest.fees", ASHARE_FEES)

        result = self.run(config)

        assert len(result.trades) == 1
        trade = result.trades[0]
        # Buy 100: commission min 5 + transfer 0.001 = 5.001
        assert trade.fee_open == pytest.approx(5.001)
        # Sell 100: commission 5 + stamp 0.05 + transfer 0.001 = 5.051
        assert trade.fee_close == pytest.approx(5.051)
        # Flat price -> PnL is exactly the round-trip fees
        assert trade.profit_abs == pytest.approx(-(5.001 + 5.051))

    def test_explicit_fee_overrides_structured_config(self):
        config = Config()
        config.set("dry_run_wallet", 1000)
        config.set("stake_amount", 100)
        config.set("max_open_trades", 1)
        config.set("backtest.fees", ASHARE_FEES)

        result = self.run(config, fee=0.001)

        trade = result.trades[0]
        assert trade.fee_open == pytest.approx(0.1)   # flat 0.1% of 100
        assert trade.fee_close == pytest.approx(0.1)
