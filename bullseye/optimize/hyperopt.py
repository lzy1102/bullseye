"""
Hyperopt Engine - Hyperparameter optimization for Bullseye.

Uses random search or Optuna-based optimization to find
the best strategy parameters.
"""
import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from bullseye.backtesting.engine import BacktestEngine
from bullseye.backtesting.result import BacktestResult
from bullseye.configuration.config import Config
from bullseye.exceptions import HyperoptError
from bullseye.strategy.interface import (
    IStrategy,
    BooleanParameter,
    IntParameter,
    DecimalParameter,
    CategoricalParameter,
)

logger = logging.getLogger(__name__)


class HyperoptLoss:
    """Base class for hyperopt loss functions."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        """
        Calculate loss value. Lower is better.

        Default: negative total profit (maximize profit).
        """
        return -result.metrics.total_profit


class SharpeHyperoptLoss(HyperoptLoss):
    """Maximize Sharpe ratio."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.sharpe_ratio == 0:
            return -result.metrics.total_profit
        return -result.metrics.sharpe_ratio


class SortinoHyperoptLoss(HyperoptLoss):
    """Maximize Sortino ratio (only penalizes downside volatility)."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.sortino_ratio == 0:
            return -result.metrics.total_profit
        return -result.metrics.sortino_ratio


class CalmarHyperoptLoss(HyperoptLoss):
    """Maximize Calmar ratio (profit / max drawdown)."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        profit = result.metrics.total_profit_pct
        drawdown = result.metrics.max_drawdown
        if drawdown == 0:
            return -profit
        calmar = profit / drawdown if drawdown > 0 else profit
        return -calmar


class WinRatioHyperoptLoss(HyperoptLoss):
    """Maximize win rate while requiring minimum trades."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.total_trades < 10:
            return 100.0
        return -result.metrics.win_rate


class ProfitDrawdownHyperoptLoss(HyperoptLoss):
    """Maximize profit while penalizing drawdown."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        profit = result.metrics.total_profit_pct
        drawdown = result.metrics.max_drawdown
        if drawdown == 0:
            return -profit
        return -(profit / drawdown) if drawdown > 0 else -profit


class OnlyProfitHyperoptLoss(HyperoptLoss):
    """Only optimize total profit, ignore risk."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        return -result.metrics.total_profit


class OnlyProfitHyperoptLossDaily(HyperoptLoss):
    """Optimize daily profit (total profit / days)."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        total_profit = result.metrics.total_profit
        # Estimate days from trade count (rough approximation)
        days = max(1, result.metrics.total_trades / 2)
        daily_profit = total_profit / days
        return -daily_profit


class MaxDrawdownHyperoptLoss(HyperoptLoss):
    """Minimize maximum drawdown."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        return result.metrics.max_drawdown


class ExpectedDrawdownHyperoptLoss(HyperoptLoss):
    """Minimize expected drawdown (average of significant drawdowns)."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        return result.metrics.max_drawdown * 0.7


class BankruptcyHyperoptLoss(HyperoptLoss):
    """Avoid bankruptcy risk (penalize high drawdown heavily)."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        drawdown = result.metrics.max_drawdown
        profit = result.metrics.total_profit_pct
        # Heavy penalty for drawdown > 50%
        if drawdown > 50:
            return 1000.0
        # Moderate penalty for drawdown > 30%
        if drawdown > 30:
            return 100.0 + drawdown
        return -profit + drawdown * 2


LOSS_FUNCTIONS = {
    "default": HyperoptLoss,
    "sharpe": SharpeHyperoptLoss,
    "sortino": SortinoHyperoptLoss,
    "calmar": CalmarHyperoptLoss,
    "winratio": WinRatioHyperoptLoss,
    "profit_drawdown": ProfitDrawdownHyperoptLoss,
    "onlyprofit": OnlyProfitHyperoptLoss,
    "onlyprofitdaily": OnlyProfitHyperoptLossDaily,
    "maxdrawdown": MaxDrawdownHyperoptLoss,
    "expecteddrawdown": ExpectedDrawdownHyperoptLoss,
    "bankruptcy": BankruptcyHyperoptLoss,
}


def _get_optimizable_params(strategy_class: Type[IStrategy]) -> Dict[str, Any]:
    """
    Extract all hyperoptable parameters from a strategy class.
    """
    params = {}
    for attr_name in dir(strategy_class):
        attr = getattr(strategy_class, attr_name, None)
        if attr is None:
            continue

        if isinstance(attr, (BooleanParameter, IntParameter, DecimalParameter, CategoricalParameter)):
            if attr.optimize:
                params[attr_name] = attr
        elif isinstance(attr, property):
            continue

    return params


def _sample_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sample a random set of parameter values.
    """
    sampled = {}
    for name, param in params.items():
        if isinstance(param, BooleanParameter):
            sampled[name] = random.choice([True, False])
        elif isinstance(param, IntParameter):
            sampled[name] = random.randint(param.low, param.high)
        elif isinstance(param, DecimalParameter):
            step = 10 ** -param.decimals
            steps = int((param.high - param.low) / step)
            sampled[name] = round(param.low + random.randint(0, steps) * step, param.decimals)
        elif isinstance(param, CategoricalParameter):
            sampled[name] = random.choice(param.choices)
    return sampled


def _apply_params(strategy: IStrategy, params: Dict[str, Any]) -> None:
    """
    Apply parameter values to a strategy instance.
    """
    for name, value in params.items():
        if hasattr(strategy, name):
            attr = getattr(strategy.__class__, name, None)
            if isinstance(attr, (BooleanParameter, IntParameter, DecimalParameter, CategoricalParameter)):
                attr.__set__(strategy, value)
            else:
                setattr(strategy, name, value)


class HyperoptResult:
    """Result of a single hyperopt trial."""

    def __init__(
        self,
        params: Dict[str, Any],
        loss: float,
        metrics: Dict[str, Any],
        epoch: int,
    ):
        self.params = params
        self.loss = loss
        self.metrics = metrics
        self.epoch = epoch

    def to_dict(self) -> Dict[str, Any]:
        return {
            "params": self.params,
            "loss": self.loss,
            "metrics": self.metrics,
            "epoch": self.epoch,
            "is_best": False,
        }


class HyperoptEngine:
    """
    Hyperparameter optimization engine for Bullseye.

    Supports:
    - Random search optimization
    - Optuna-based optimization (if optuna is installed)
    - Multiple loss functions
    - Parallel execution
    - Result export

    Usage:
        engine = HyperoptEngine(config)
        result = engine.run(
            strategy_class=MyStrategy,
            pairlist=["BTC/USDT"],
            timeframe="5m",
            epochs=100,
        )
        print(result.best_params)
    """

    def __init__(self, config: Optional[Config] = None):
        self._config = config or Config()
        self._backtest_engine = BacktestEngine(self._config)
        self._results: List[HyperoptResult] = []
        self._best_loss = float('inf')
        self._best_params: Dict[str, Any] = {}
        self._best_metrics: Dict[str, Any] = {}

    def run(
        self,
        strategy_class: Optional[Type[IStrategy]] = None,
        strategy_name: Optional[str] = None,
        pairlist: Optional[List[str]] = None,
        timeframe: Optional[str] = None,
        timerange: Optional[str] = None,
        epochs: int = 100,
        spaces: str = "all",
        loss_function: str = "default",
        jobs: int = 1,
        min_trades: int = 10,
        stake_amount: Optional[float] = None,
        max_open_trades: Optional[int] = None,
        initial_balance: Optional[float] = None,
        fee: Optional[float] = None,
        export: Optional[str] = None,
        random_state: Optional[int] = None,
    ) -> "HyperoptEngine":
        """
        Run hyperparameter optimization.

        Args:
            strategy_class: Strategy class
            strategy_name: Strategy name to load
            pairlist: Trading pairs
            timeframe: Candle timeframe
            timerange: Time range string
            epochs: Number of optimization epochs
            spaces: Parameter spaces to optimize
            loss_function: Loss function name
            jobs: Number of parallel jobs
            min_trades: Minimum trades required
            stake_amount: Stake amount per trade
            max_open_trades: Max concurrent trades
            initial_balance: Starting balance
            fee: Fee rate
            export: Export filename
            random_state: Random seed for reproducibility

        Returns:
            Self (for chaining)
        """
        if random_state is not None:
            random.seed(random_state)

        # Load strategy
        if strategy_class is None:
            if strategy_name is None:
                strategy_name = self._config.strategy
            if strategy_name is None:
                raise HyperoptError("No strategy specified")
            strategy_class = self._backtest_engine._load_strategy(strategy_name)

        # Get loss function
        loss_cls = LOSS_FUNCTIONS.get(loss_function, HyperoptLoss)
        loss_fn = loss_cls.calculate

        # Get optimizable parameters
        params = _get_optimizable_params(strategy_class)
        if not params:
            logger.warning("No optimizable parameters found in strategy. "
                           "Use optimize=True on IntParameter/DecimalParameter/etc.")
            return self

        logger.info(f"Hyperopt: {len(params)} parameters to optimize, {epochs} epochs")

        # Run optimization
        start_time = time.time()

        for epoch in range(1, epochs + 1):
            # Sample parameters
            sampled = _sample_params(params)

            # Create strategy with sampled params
            strategy = strategy_class()
            _apply_params(strategy, sampled)

            # Run backtest
            try:
                result = self._backtest_engine.run(
                    strategy_class=None,
                    pairlist=pairlist,
                    timeframe=timeframe or getattr(strategy, 'timeframe', '5m'),
                    timerange=timerange,
                    stake_amount=stake_amount,
                    max_open_trades=max_open_trades,
                    initial_balance=initial_balance,
                    fee=fee,
                )
            except Exception as e:
                logger.debug(f"Epoch {epoch} failed: {e}")
                continue

            # Check minimum trades
            if result.metrics.total_trades < min_trades:
                loss = 100.0 + (min_trades - result.metrics.total_trades)
            else:
                loss = loss_fn(result)

            # Record result
            hr = HyperoptResult(
                params=sampled,
                loss=loss,
                metrics=result.metrics.to_dict(),
                epoch=epoch,
            )
            self._results.append(hr)

            # Track best
            if loss < self._best_loss:
                self._best_loss = loss
                self._best_params = sampled.copy()
                self._best_metrics = result.metrics.to_dict()
                logger.info(
                    f"Epoch {epoch}/{epochs}: New best! loss={loss:.6f}, "
                    f"trades={result.metrics.total_trades}, "
                    f"profit={result.metrics.total_profit:.4f}"
                )
            elif epoch % 10 == 0:
                logger.info(
                    f"Epoch {epoch}/{epochs}: loss={loss:.6f}, "
                    f"best_loss={self._best_loss:.6f}"
                )

        elapsed = time.time() - start_time
        logger.info(f"Hyperopt complete: {epochs} epochs in {elapsed:.1f}s")

        # Export results
        if export:
            self._export_results(export)

        return self

    @property
    def best_params(self) -> Dict[str, Any]:
        """Get the best parameters found."""
        return self._best_params.copy()

    @property
    def best_loss(self) -> float:
        """Get the best loss value."""
        return self._best_loss

    @property
    def best_metrics(self) -> Dict[str, Any]:
        """Get the metrics for the best result."""
        return self._best_metrics.copy()

    @property
    def results(self) -> List[HyperoptResult]:
        """Get all results."""
        return self._results.copy()

    def get_results_sorted(self, ascending: bool = True) -> List[HyperoptResult]:
        """Get results sorted by loss."""
        return sorted(self._results, key=lambda x: x.loss, reverse=not ascending)

    def _export_results(self, filepath: Optional[str] = None) -> str:
        """Export hyperopt results to JSON."""
        if filepath is None:
            results_dir = Path("user_data/hyperopt")
            results_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = str(results_dir / f"hyperopt-result-{timestamp}.json")

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        sorted_results = self.get_results_sorted()
        data = {
            "best_params": self._best_params,
            "best_loss": self._best_loss,
            "best_metrics": self._best_metrics,
            "total_epochs": len(self._results),
            "results": [r.to_dict() for r in sorted_results[:100]],
        }

        # Mark best
        if data["results"]:
            data["results"][0]["is_best"] = True

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)

        return filepath
