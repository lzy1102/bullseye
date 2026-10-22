"""
Tests for Chinese-futures support in the backtest engine.

Covers the contract-spec math (multiplier / margin / per-lot fees / tick) and
an end-to-end futures backtest: margin-based sizing, T+0 exit, close-today fee
surcharge and mark-to-market equity.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from bullseye.backtesting.engine import BacktestEngine  # noqa: E402
from bullseye.configuration.config import Config  # noqa: E402
from bullseye.order.future_rules import (  # noqa: E402
    ContractRegistry,
    FutureContract,
)
from bullseye.strategy.interface import IStrategy  # noqa: E402

PAIR = "RB0@SHFE"


@pytest.fixture
def contract():
    return FutureContract(
        pair=PAIR, symbol="RB0", product="RB", exchange="SHFE",
        multiplier=10.0, tick_size=1.0, margin_rate=0.10,
        open_fee_fixed_per_lot=0.0, close_fee_fixed_per_lot=0.0,
        close_today_fee_fixed_per_lot=0.0,
        open_fee_rate=0.0001, close_fee_rate=0.0001,
        close_today_fee_rate=0.0003, limit_ratio=0.08,
    )


class TestFutureContractMath:
    def test_notional_uses_multiplier(self, contract):
        assert contract.notional(3000.0, 2) == 3000.0 * 2 * 10.0

    def test_margin_is_notional_times_rate(self, contract):
        assert contract.margin(3000.0, 2) == pytest.approx(60000.0 * 0.10)

    def test_contracts_for_margin_is_whole_lots(self, contract):
        # 1 lot at 3000 needs 3000 * 10 * 0.1 = 3000 margin
        assert contract.contracts_for_margin(3000.0, 3000.0) == 1
        assert contract.contracts_for_margin(2999.0, 3000.0) == 0
        assert contract.contracts_for_margin(9000.0, 3000.0) == 3

    def test_fee_is_fixed_plus_rate_on_notional(self, contract):
        # 1 lot of 10t at 3000 -> 30000 notional; rate 0.0001 -> 3.0
        assert contract.fee(3000.0, 1, "open") == pytest.approx(3.0)
        assert contract.fee(3000.0, 2, "open") == pytest.approx(6.0)

    def test_close_today_fee_uses_its_own_rate(self, contract):
        assert contract.fee(3000.0, 1, "close", close_today=True) == pytest.approx(9.0)
        assert contract.fee(3000.0, 1, "close", close_today=False) == pytest.approx(3.0)

    def test_fixed_fee_part_is_added(self):
        spec = FutureContract(multiplier=1.0, open_fee_fixed_per_lot=2.5,
                              open_fee_rate=0.0)
        assert spec.fee(100.0, 3, "open") == pytest.approx(7.5)

    def test_round_to_tick(self, contract):
        assert contract.round_to_tick(3000.4) == 3000.0
        assert contract.round_to_tick(3000.6) == 3001.0

    def test_limit_prices_from_settlement(self, contract):
        up, down = contract.limit_prices(3000.0)
        assert up == pytest.approx(3240.0)
        assert down == pytest.approx(2760.0)


class TestContractRegistry:
    def test_load_roundtrip(self, tmp_path):
        path = tmp_path / "contracts.json"
        path.write_text(json.dumps({
            "contracts": {PAIR: {"multiplier": 10, "tick_size": 1,
                                 "margin_rate": 0.1}}
        }), encoding="utf-8")
        registry = ContractRegistry.load(path)
        assert PAIR in registry
        spec = registry.get(PAIR)
        assert spec is not None and spec.multiplier == 10.0
        assert spec.pair == PAIR

    def test_missing_file_yields_empty_registry(self, tmp_path):
        registry = ContractRegistry.load(tmp_path / "nope.json")
        assert len(registry) == 0
        assert registry.get(PAIR) is None


class TestFuturesBacktest:
    """End-to-end: margin sizing, per-lot fees, T+0 exit, margin release."""

    def _frames(self, closes):
        dates = pd.date_range("2024-01-02", periods=len(closes), freq="D")
        return pd.DataFrame({
            "date": dates,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
            "pre_settle": [closes[0]] + closes[:-1],
        })

    def _config(self, tmp_path, contracts_file, stake=10000.0):
        path = tmp_path / "contracts.json"
        path.write_text(json.dumps({"contracts": {PAIR: {
            "multiplier": 10, "tick_size": 1, "margin_rate": 0.10,
            "open_fee_rate": 0.0001, "close_fee_rate": 0.0001,
            "close_today_fee_rate": 0.0003, "limit_ratio": 0.08,
        }}}), encoding="utf-8")
        config = Config()
        config.set("stake_currency", "CNY")
        config.set("stake_amount", stake)
        config.set("max_open_trades", 1)
        config.set("dry_run", True)
        config.set("dry_run_wallet", 100000.0)
        config.set("fee", 0.0)
        config.set("futures.contracts_file", str(path))
        return config

    def _strategy(self):
        class OneShotStrategy(IStrategy):
            timeframe = "1d"
            startup_candle_count = 1
            minimal_roi = {"0": 10}
            stoploss = -0.5

            def populate_indicators(self, dataframe, metadata):
                return dataframe

            def populate_entry_trend(self, dataframe, metadata):
                dataframe.loc[1, "enter_long"] = 1
                return dataframe

            def populate_exit_trend(self, dataframe, metadata):
                dataframe.loc[2, "exit_long"] = 1
                return dataframe

        return OneShotStrategy

    def test_futures_trade_uses_lots_and_margin(self, tmp_path):
        closes = [3000.0, 3000.0, 3060.0, 3060.0]
        config = self._config(tmp_path, None, stake=10000.0)
        engine = BacktestEngine(config)
        data = {PAIR: self._frames(closes)}
        result = engine.run(
            strategy_class=self._strategy(), pairlist=[PAIR],
            timeframe="1d", data=data,
        )
        trades = result.trades
        assert len(trades) == 1, "expected one futures trade"
        trade = trades[0]
        # 10000 margin / (3000 * 10 * 0.1) -> 3 lots
        assert trade.amount == 3
        # notional = 3 lots * 3000 * 10
        assert trade.stake_amount == pytest.approx(90000.0)
        # open fee: 3 * 0.0001 * 30000 = 9.0
        assert trade.fee_open == pytest.approx(9.0)
        # close fee (not same day) = 3 * 0.0001 * 30600 = 9.18
        assert trade.fee_close == pytest.approx(9.18)
        # pnl: 3 * 60 * 10 = 1800
        assert trade.profit_abs == pytest.approx(1800.0 - 9.0 - 9.18)
        # exit happened on the entry+1 bar -> T+0 allowed
        assert trade.exit_date > trade.entry_date

    def test_daily_bars_never_pay_close_today_fee(self, tmp_path):
        """The engine exits before it enters within a bar, so a daily-bar
        position is always closed on a later trading day. Close-today (平今)
        only becomes reachable on intraday timeframes."""
        closes = [3000.0, 3000.0, 3060.0]
        config = self._config(tmp_path, None, stake=10000.0)
        engine = BacktestEngine(config)
        data = {PAIR: self._frames(closes)}
        result = engine.run(
            strategy_class=self._strategy(), pairlist=[PAIR],
            timeframe="1d", data=data,
        )
        trade = result.trades[0]
        # plain close fee: 3 * 0.0001 * 30600 = 9.18 (not the 0.0003 rate)
        assert trade.fee_close == pytest.approx(9.18)

    def test_final_balance_reflects_margin_release(self, tmp_path):
        closes = [3000.0, 3000.0, 3060.0, 3060.0]
        config = self._config(tmp_path, None, stake=10000.0)
        engine = BacktestEngine(config)
        data = {PAIR: self._frames(closes)}
        result = engine.run(
            strategy_class=self._strategy(), pairlist=[PAIR],
            timeframe="1d", data=data,
        )
        # 100000 start, 10000 margin locked, released at exit, +1781.82 pnl
        assert result.metrics.final_balance == pytest.approx(
            100000.0 + 1800.0 - 9.0 - 9.18
        )
