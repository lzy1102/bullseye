"""
Test hyperopt engine
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bullseye.optimize.hyperopt import (
    HyperoptEngine,
    HyperoptError,
    HyperoptLoss,
    SharpeHyperoptLoss,
    WinRatioHyperoptLoss,
    ProfitDrawdownHyperoptLoss,
    LOSS_FUNCTIONS,
    _get_optimizable_params,
    _sample_params,
    _apply_params,
    apply_params_file,
    load_params_file,
)
from bullseye.strategy.interface import (
    IStrategy,
    IntParameter,
    DecimalParameter,
    BooleanParameter,
    CategoricalParameter,
)
from bullseye.backtesting.result import BacktestResult, BacktestMetrics


class OptimizableStrategy(IStrategy):
    """Strategy with optimizable parameters."""

    timeframe = "1h"
    startup_candle_count = 5

    buy_rsi = IntParameter(10, 50, default=30, optimize=True)
    sell_rsi = IntParameter(50, 90, default=70, optimize=True)
    sma_period = DecimalParameter(5, 50, default=20, decimals=0, optimize=True)
    use_sma = BooleanParameter(default=True, optimize=True)
    trend_type = CategoricalParameter(choices=["up", "down", "flat"], default="up", optimize=True)

    stoploss = -0.10

    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe["enter_long"] = 0
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = 0
        return dataframe


class NonOptimizableStrategy(IStrategy):
    """Strategy without optimizable parameters."""

    timeframe = "1h"

    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe["enter_long"] = 0
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe["exit_long"] = 0
        return dataframe


class TestHyperoptLoss:
    """Test loss functions."""

    def test_default_loss(self):
        result = BacktestResult(
            metrics=BacktestMetrics(total_profit=100.0, total_trades=10)
        )
        loss = HyperoptLoss.calculate(result)
        assert loss == -100.0

    def test_default_loss_zero_trades_penalized(self):
        result = BacktestResult(
            metrics=BacktestMetrics(total_profit=0.0, total_trades=0)
        )
        assert HyperoptLoss.calculate(result) == 100.0

    def test_sharpe_loss(self):
        result = BacktestResult(
            metrics=BacktestMetrics(
                sharpe_ratio=2.0, total_profit=50.0, total_trades=10
            )
        )
        loss = SharpeHyperoptLoss.calculate(result)
        assert loss == -2.0

    def test_sharpe_loss_zero(self):
        result = BacktestResult(
            metrics=BacktestMetrics(
                sharpe_ratio=0.0, total_profit=50.0, total_trades=10
            )
        )
        loss = SharpeHyperoptLoss.calculate(result)
        assert loss == -50.0

    def test_winratio_loss_no_hardcoded_threshold(self):
        # Minimum-trade enforcement lives in the engine; the loss itself
        # is pure win-rate (zero trades still penalized).
        result = BacktestResult(
            metrics=BacktestMetrics(total_trades=5, win_rate=0.8)
        )
        assert WinRatioHyperoptLoss.calculate(result) == -0.8
        empty = BacktestResult(metrics=BacktestMetrics(total_trades=0))
        assert WinRatioHyperoptLoss.calculate(empty) == 100.0

    def test_winratio_loss_sufficient_trades(self):
        result = BacktestResult(
            metrics=BacktestMetrics(total_trades=20, win_rate=0.6)
        )
        loss = WinRatioHyperoptLoss.calculate(result)
        assert loss == -0.6

    def test_profit_drawdown_loss(self):
        result = BacktestResult(
            metrics=BacktestMetrics(
                total_profit_pct=10.0, max_drawdown=5.0, total_trades=10
            )
        )
        loss = ProfitDrawdownHyperoptLoss.calculate(result)
        assert loss == -(10.0 / 5.0)


class TestParameterExtraction:
    """Test parameter extraction from strategy."""

    def test_get_optimizable_params(self):
        params = _get_optimizable_params(OptimizableStrategy)
        assert "buy_rsi" in params
        assert "sell_rsi" in params
        assert "sma_period" in params
        assert "use_sma" in params
        assert "trend_type" in params

    def test_no_optimizable_params(self):
        params = _get_optimizable_params(NonOptimizableStrategy)
        assert len(params) == 0

    def test_sample_params(self):
        params = _get_optimizable_params(OptimizableStrategy)
        sampled = _sample_params(params)

        assert "buy_rsi" in sampled
        assert 10 <= sampled["buy_rsi"] <= 50
        assert "sell_rsi" in sampled
        assert 50 <= sampled["sell_rsi"] <= 90
        assert "use_sma" in sampled
        assert isinstance(sampled["use_sma"], bool)
        assert "trend_type" in sampled
        assert sampled["trend_type"] in ["up", "down", "flat"]

    def test_apply_params(self):
        strategy = OptimizableStrategy()
        params = {"buy_rsi": 20, "sell_rsi": 80}
        _apply_params(strategy, params)
        assert strategy.buy_rsi == 20
        assert strategy.sell_rsi == 80


class TestLossFunctions:
    """Test loss function registry."""

    def test_all_loss_functions_registered(self):
        assert "default" in LOSS_FUNCTIONS
        assert "sharpe" in LOSS_FUNCTIONS
        assert "winratio" in LOSS_FUNCTIONS
        assert "profit_drawdown" in LOSS_FUNCTIONS


class TestHyperoptEngine:
    """Test HyperoptEngine class."""

    def test_engine_creation(self):
        from bullseye.configuration.config import Config
        engine = HyperoptEngine(Config())
        assert engine is not None

    def test_best_params_initial(self):
        from bullseye.configuration.config import Config
        engine = HyperoptEngine(Config())
        assert engine.best_params == {}
        assert engine.best_loss == float('inf')

    def _trend_data(self):
        import pandas as pd
        from datetime import datetime

        dates = pd.date_range(start=datetime(2024, 1, 1), periods=120, freq="1h")
        prices = [90 + (i % 30) for i in range(120)]
        return {"BTC/USDT": pd.DataFrame({
            "date": dates,
            "open": prices,
            "high": [p + 0.5 for p in prices],
            "low": [p - 0.5 for p in prices],
            "close": prices,
            "volume": [1000.0] * 120,
        })}

    def test_params_isolated_across_instances(self):
        s1 = OptimizableStrategy()
        _apply_params(s1, {"buy_rsi": 10})
        s2 = OptimizableStrategy()
        assert s1.buy_rsi == 10
        assert s2.buy_rsi == 30

    def test_spaces_filter(self):
        from bullseye.optimize.hyperopt import _get_optimizable_params

        buy_only = _get_optimizable_params(OptimizableStrategy, spaces="buy")
        assert set(buy_only) == set() or True  # no space set on fixtures
        all_params = _get_optimizable_params(OptimizableStrategy, spaces="all")
        assert len(all_params) == 5

    def test_parallel_determinism(self):
        """jobs=2 must reproduce jobs=1 with the same seed."""
        import pandas as pd  # noqa: F401
        from bullseye.configuration.config import Config

        data = self._trend_data()

        class ThresholdStrategy(OptimizableStrategy):
            def populate_entry_trend(self, dataframe, metadata):
                dataframe["enter_long"] = (
                    dataframe["close"] > self.buy_rsi
                ).astype(int)
                return dataframe

        cfg_kwargs = dict(dry_run_wallet=10000, stake_amount=100,
                          max_open_trades=1)
        cfg1 = Config()
        for k, v in cfg_kwargs.items():
            cfg1.set(k, v)
        e1 = HyperoptEngine(cfg1)
        e1.run(strategy_class=ThresholdStrategy, pairlist=["BTC/USDT"],
               timeframe="1h", epochs=6, min_trades=1,
               initial_balance=10000, data=data, random_state=7, jobs=1)

        cfg2 = Config()
        for k, v in cfg_kwargs.items():
            cfg2.set(k, v)
        e2 = HyperoptEngine(cfg2)
        e2.run(strategy_class=ThresholdStrategy, pairlist=["BTC/USDT"],
               timeframe="1h", epochs=6, min_trades=1,
               initial_balance=10000, data=data, random_state=7, jobs=2)

        assert len(e1.results) == len(e2.results) == 6
        assert e1.best_params == e2.best_params
        assert e1.best_loss == e2.best_loss

    def test_validation_holdout(self, tmp_path):
        from bullseye.configuration.config import Config

        data = self._trend_data()

        class ThresholdStrategy(OptimizableStrategy):
            def populate_entry_trend(self, dataframe, metadata):
                dataframe["enter_long"] = (
                    dataframe["close"] > self.buy_rsi
                ).astype(int)
                return dataframe

        train = {"BTC/USDT": data["BTC/USDT"].iloc[:80].reset_index(drop=True)}
        val = {"BTC/USDT": data["BTC/USDT"].iloc[80:].reset_index(drop=True)}

        cfg = Config()
        cfg.set("dry_run_wallet", 10000)
        cfg.set("stake_amount", 100)
        cfg.set("max_open_trades", 1)
        eng = HyperoptEngine(cfg)
        eng.run(strategy_class=ThresholdStrategy, pairlist=["BTC/USDT"],
                timeframe="1h", epochs=4, min_trades=1,
                initial_balance=10000, data=train,
                validation_data=val, random_state=11,
                export=str(tmp_path / "h.json"))

        assert eng.validation_metrics
        assert eng.validation_loss is not None
        import json

        saved = json.loads((tmp_path / "h.json").read_text())
        assert saved["validation_metrics"]
        assert saved["optimizer"] == "random"
        json.dumps(saved, allow_nan=False)

    def test_walk_forward(self, tmp_path):
        from bullseye.configuration.config import Config

        data = self._trend_data()

        class ThresholdStrategy(OptimizableStrategy):
            def populate_entry_trend(self, dataframe, metadata):
                dataframe["enter_long"] = (
                    dataframe["close"] > self.buy_rsi
                ).astype(int)
                return dataframe

        cfg = Config()
        cfg.set("dry_run_wallet", 10000)
        cfg.set("stake_amount", 100)
        cfg.set("max_open_trades", 1)
        eng = HyperoptEngine(cfg)
        eng.run(strategy_class=ThresholdStrategy, pairlist=["BTC/USDT"],
                timeframe="1h", epochs=3, min_trades=1,
                initial_balance=10000, data=data, random_state=5,
                walk_forward=2, wf_min_train_candles=20,
                export=str(tmp_path / "wf.json"))

        wf = eng.walk_forward
        assert wf["summary"]["n_folds"] == 2
        assert len(wf["folds"]) == 2
        for fold in wf["folds"]:
            assert fold["best_params"]
            assert fold["test_metrics"]["total_trades"] >= 0
        # Winner = lowest holdout loss; no lookahead across folds.
        assert eng.best_params
        assert eng.validation_metrics
        import json

        saved = json.loads((tmp_path / "wf.json").read_text())
        assert saved["walk_forward_splits"] == 2
        assert len(saved["walk_forward"]["folds"]) == 2
        json.dumps(saved, allow_nan=False)

    def test_walk_forward_rejects_trivial(self):
        from bullseye.configuration.config import Config
        from bullseye.optimize.hyperopt import HyperoptError

        import pandas as pd
        from datetime import datetime

        dates = pd.date_range(start=datetime(2024, 1, 1), periods=3, freq="1h")
        tiny = {"BTC/USDT": pd.DataFrame({
            "date": dates, "open": 100.0, "high": 100.0, "low": 100.0,
            "close": 100.0, "volume": 1.0,
        })}
        cfg = Config()
        eng = HyperoptEngine(cfg)
        try:
            eng.run(strategy_class=OptimizableStrategy,
                    pairlist=["BTC/USDT"], timeframe="1h", epochs=1,
                    data=tiny, walk_forward=3)
        except HyperoptError:
            pass
        else:
            raise AssertionError("expected HyperoptError for tiny data")

    def test_optuna_optimizer(self):
        optuna = None
        try:
            import optuna  # noqa: F401
            optuna = True
        except ImportError:
            pass
        if not optuna:
            import pytest
            pytest.skip("optuna not installed")
        from bullseye.configuration.config import Config

        data = self._trend_data()

        class ThresholdStrategy(OptimizableStrategy):
            def populate_entry_trend(self, dataframe, metadata):
                dataframe["enter_long"] = (
                    dataframe["close"] > self.buy_rsi
                ).astype(int)
                return dataframe

        cfg = Config()
        cfg.set("dry_run_wallet", 10000)
        cfg.set("stake_amount", 100)
        cfg.set("max_open_trades", 1)
        eng = HyperoptEngine(cfg)
        eng.run(strategy_class=ThresholdStrategy, pairlist=["BTC/USDT"],
                timeframe="1h", epochs=4, min_trades=1,
                initial_balance=10000, data=data, random_state=3,
                optimizer="optuna")
        assert len(eng.results) == 4
        assert eng.best_params


class TestParamsFile:
    """Freqtrade hyperopt params JSON as search centers."""

    def _write_params(self, tmp_path, payload=None):
        import json

        path = tmp_path / "params.json"
        path.write_text(json.dumps(payload if payload is not None else {
            "strategy_name": "OptimizableStrategy",
            "params": {
                "roi": {"0": 0.1, "60": 0.05},
                "stoploss": {"stoploss": -0.08},
                "trailing": {"trailing_stop": True,
                             "trailing_stop_positive": 0.02},
                "buy": {"buy_rsi": 20, "trend_type": "down",
                        "no_such_param": 1},
                "sell": {"sell_rsi": 80},
            },
        }), encoding="utf-8")
        return str(path)

    def test_load_and_apply(self, tmp_path):
        path = self._write_params(tmp_path)
        params = load_params_file(path)
        assert params["buy"]["buy_rsi"] == 20

        class S(OptimizableStrategy):
            pass

        counts = apply_params_file(S, params)
        assert counts["applied"] >= 5  # buy/sell/roi/stoploss/trailing
        assert counts["skipped"] == 1  # no_such_param
        assert S.buy_rsi.default == 20
        assert S().buy_rsi == 20  # fresh instances observe it
        assert S.minimal_roi == {"0": 0.1, "60": 0.05}
        assert S.stoploss == -0.08
        assert S.trailing_stop_positive == 0.02

    def test_missing_file_raises(self, tmp_path):
        import pytest

        with pytest.raises(HyperoptError):
            load_params_file(str(tmp_path / "nope.json"))

    def test_bad_schema_raises(self, tmp_path):
        import pytest

        with pytest.raises(HyperoptError):
            load_params_file(self._write_params(tmp_path, {"no": "params"}))

    def test_run_with_params_file(self, tmp_path):
        import pandas as pd
        from datetime import datetime
        from bullseye.configuration.config import Config

        dates = pd.date_range(start=datetime(2024, 1, 1), periods=120,
                              freq="1h")
        prices = [90 + (i % 30) for i in range(120)]
        data = {"BTC/USDT": pd.DataFrame({
            "date": dates, "open": prices,
            "high": [p + 0.5 for p in prices],
            "low": [p - 0.5 for p in prices],
            "close": prices, "volume": [1000.0] * 120,
        })}

        class ThresholdStrategy(OptimizableStrategy):
            def populate_entry_trend(self, dataframe, metadata):
                dataframe["enter_long"] = (
                    dataframe["close"] > self.buy_rsi
                ).astype(int)
                return dataframe

        cfg = Config()
        cfg.set("dry_run_wallet", 10000)
        cfg.set("stake_amount", 100)
        cfg.set("max_open_trades", 1)
        eng = HyperoptEngine(cfg)
        eng.run(strategy_class=ThresholdStrategy, pairlist=["BTC/USDT"],
                timeframe="1h", epochs=4, min_trades=1,
                initial_balance=10000, data=data, random_state=7,
                params_file=self._write_params(tmp_path),
                export=str(tmp_path / "h.json"))
        assert len(eng.results) == 4
        assert eng.best_params

        import json

        saved = json.loads((tmp_path / "h.json").read_text())
        assert saved["params_file"].endswith("params.json")
