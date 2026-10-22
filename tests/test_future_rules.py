"""
Tests for Chinese-futures support in the backtest engine.

Covers the contract-spec math (multiplier / margin / per-lot fees / tick), the
Freqtrade-style sizing semantics (stake x leverage = notional, only the
exchange margin is locked) and an end-to-end futures backtest.
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

    def test_leverage_from_margin_is_broker_cap(self, contract):
        # 10% margin -> at most 10x notional
        assert contract.leverage_from_margin == pytest.approx(10.0)

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

    def test_real_contract_code_resolves_to_product_spec(self, tmp_path):
        path = tmp_path / "contracts.json"
        path.write_text(json.dumps({
            "contracts": {PAIR: {"multiplier": 10, "tick_size": 1,
                                 "margin_rate": 0.1, "product": "RB",
                                 "exchange": "SHFE", "symbol": "RB0"}}
        }), encoding="utf-8")
        registry = ContractRegistry.load(path)
        assert registry.get("rb2601").multiplier == 10.0
        assert registry.get("rb2601@SHFE").multiplier == 10.0
        assert registry.get("cu2601@SHFE") is None


class TestTradingModeConfig:
    def test_default_is_auto(self):
        config = Config()
        assert config.trading_mode == "auto"
        assert config.margin_mode == "isolated"
        assert config.allows_short is True

    def test_spot_forbids_shorts(self):
        config = Config()
        config.set("trading_mode", "spot")
        assert config.trading_mode == "spot"
        assert config.allows_short is False

    def test_invalid_mode_raises(self):
        from bullseye.exceptions import ConfigurationError
        config = Config()
        config.set("trading_mode", "banana")
        with pytest.raises(ConfigurationError):
            config.trading_mode


class TestFuturesBacktest:
    """End-to-end: stake x leverage = notional, only margin is locked."""

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

    def _contracts_file(self, tmp_path):
        path = tmp_path / "contracts.json"
        path.write_text(json.dumps({"contracts": {PAIR: {
            "multiplier": 10, "tick_size": 1, "margin_rate": 0.10,
            "open_fee_rate": 0.0001, "close_fee_rate": 0.0001,
            "close_today_fee_rate": 0.0003, "limit_ratio": 0.08,
            "product": "RB", "exchange": "SHFE", "symbol": "RB0",
        }}}), encoding="utf-8")
        return path

    def _config(self, tmp_path, stake=100000.0, trading_mode="auto"):
        path = self._contracts_file(tmp_path)
        config = Config()
        config.set("stake_currency", "CNY")
        config.set("stake_amount", stake)
        config.set("max_open_trades", 1)
        config.set("dry_run", True)
        config.set("dry_run_wallet", 100000.0)
        config.set("fee", 0.0)
        config.set("trading_mode", trading_mode)
        config.set("futures.contracts_file", str(path))
        return config

    def _strategy(self, leverage_cb=None):
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

        if leverage_cb is not None:
            def leverage(self, **kwargs):
                return leverage_cb(**kwargs)
            OneShotStrategy.leverage = leverage
        return OneShotStrategy

    def _run(self, tmp_path, closes, stake=100000.0, leverage_cb=None,
             trading_mode="auto", pair=PAIR):
        config = self._config(tmp_path, stake=stake, trading_mode=trading_mode)
        engine = BacktestEngine(config)
        data = {pair: self._frames(closes)}
        return engine.run(
            strategy_class=self._strategy(leverage_cb), pairlist=[pair],
            timeframe="1d", data=data,
        )

    def test_default_leverage_is_1x_notional(self, tmp_path):
        """Without a leverage() callback the stake buys 1x notional."""
        closes = [3000.0, 3000.0, 3060.0, 3060.0]
        result = self._run(tmp_path, closes, stake=100000.0)
        trade = result.trades[0]
        # 100000 notional / (3000 * 10) -> 3 lots
        assert trade.amount == 3
        assert trade.stake_amount == pytest.approx(90000.0)
        # only the exchange margin is locked: 90000 * 10% = 9000
        assert trade.fee_open == pytest.approx(9.0)
        assert trade.fee_close == pytest.approx(9.18)
        # pnl: 3 lots * 60 * 10 = 1800
        assert trade.profit_abs == pytest.approx(1800.0 - 9.0 - 9.18)
        # the margin comes back, the profit stays
        assert result.metrics.final_balance == pytest.approx(
            100000.0 + 1800.0 - 9.0 - 9.18
        )

    def test_strategy_can_ask_for_the_broker_cap(self, tmp_path):
        """leverage() returning max_leverage uses the full broker margin."""
        closes = [3000.0, 3000.0, 3060.0, 3060.0]
        result = self._run(
            tmp_path, closes, stake=10000.0,
            leverage_cb=lambda **kw: kw["max_leverage"],
        )
        trade = result.trades[0]
        # 10000 * 10 (1 / 10% margin) = 100000 notional -> 3 lots
        assert trade.amount == 3
        assert trade.stake_amount == pytest.approx(90000.0)

    def test_leverage_is_clamped_to_the_broker_cap(self, tmp_path):
        closes = [3000.0, 3000.0, 3060.0, 3060.0]
        result = self._run(
            tmp_path, closes, stake=100000.0,
            leverage_cb=lambda **kw: 100.0,
        )
        # 100000 * 10 (clamped from 100) -> 1000000 notional -> 33 lots
        assert result.trades[0].amount == 33

    def test_trading_mode_futures_forces_the_futures_path(self, tmp_path):
        """A contract code without @EXCHANGE still gets futures accounting."""
        closes = [3000.0, 3000.0, 3060.0, 3060.0]
        result = self._run(tmp_path, closes, stake=100000.0,
                           trading_mode="futures", pair="RB2601")
        assert result.trades[0].amount == 3

    def test_daily_bars_never_pay_close_today_fee(self, tmp_path):
        """The engine exits before it enters within a bar, so a daily-bar
        position is always closed on a later trading day. Close-today (平今)
        only becomes reachable on intraday timeframes."""
        closes = [3000.0, 3000.0, 3060.0]
        result = self._run(tmp_path, closes, stake=100000.0)
        # plain close fee: 3 * 0.0001 * 30600 = 9.18 (not the 0.0003 rate)
        assert result.trades[0].fee_close == pytest.approx(9.18)
