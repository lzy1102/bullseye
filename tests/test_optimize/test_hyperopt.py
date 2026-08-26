"""
Test hyperopt engine
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bullseye.optimize.hyperopt import (
    HyperoptEngine,
    HyperoptLoss,
    SharpeHyperoptLoss,
    WinRatioHyperoptLoss,
    ProfitDrawdownHyperoptLoss,
    LOSS_FUNCTIONS,
    _get_optimizable_params,
    _sample_params,
    _apply_params,
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
            metrics=BacktestMetrics(total_profit=100.0)
        )
        loss = HyperoptLoss.calculate(result)
        assert loss == -100.0

    def test_sharpe_loss(self):
        result = BacktestResult(
            metrics=BacktestMetrics(sharpe_ratio=2.0, total_profit=50.0)
        )
        loss = SharpeHyperoptLoss.calculate(result)
        assert loss == -2.0

    def test_sharpe_loss_zero(self):
        result = BacktestResult(
            metrics=BacktestMetrics(sharpe_ratio=0.0, total_profit=50.0)
        )
        loss = SharpeHyperoptLoss.calculate(result)
        assert loss == -50.0

    def test_winratio_loss_insufficient_trades(self):
        result = BacktestResult(
            metrics=BacktestMetrics(total_trades=5, win_rate=0.8)
        )
        loss = WinRatioHyperoptLoss.calculate(result)
        assert loss == 100.0

    def test_winratio_loss_sufficient_trades(self):
        result = BacktestResult(
            metrics=BacktestMetrics(total_trades=20, win_rate=0.6)
        )
        loss = WinRatioHyperoptLoss.calculate(result)
        assert loss == -0.6

    def test_profit_drawdown_loss(self):
        result = BacktestResult(
            metrics=BacktestMetrics(total_profit_pct=10.0, max_drawdown=5.0)
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
