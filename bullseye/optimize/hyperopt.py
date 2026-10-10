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


def _finite(value: float, fallback: float = 0.0) -> float:
    """Coerce inf/NaN/None to a finite fallback for loss math + JSON."""
    try:
        import math

        if value is None:
            return fallback
        f = float(value)
        if math.isinf(f) or math.isnan(f):
            return fallback
        return f
    except (TypeError, ValueError):
        return fallback


class HyperoptLoss:
    """Base class for hyperopt loss functions."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        """
        Calculate loss value. Lower is better.

        Default: negative total profit (maximize profit).
        Zero-trade results are heavily penalized so an empty backtest can
        never win as "risk-free".
        """
        if result.metrics.total_trades == 0:
            return 100.0
        return -_finite(result.metrics.total_profit, 0.0)


class SharpeHyperoptLoss(HyperoptLoss):
    """Maximize Sharpe ratio."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.total_trades == 0:
            return 100.0
        sharpe = _finite(result.metrics.sharpe_ratio, 0.0)
        if sharpe == 0:
            return -_finite(result.metrics.total_profit, 0.0)
        return -sharpe


class SortinoHyperoptLoss(HyperoptLoss):
    """Maximize Sortino ratio (only penalizes downside volatility)."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.total_trades == 0:
            return 100.0
        sortino = _finite(result.metrics.sortino_ratio, 0.0)
        if sortino == 0:
            return -_finite(result.metrics.total_profit, 0.0)
        return -sortino


class CalmarHyperoptLoss(HyperoptLoss):
    """Maximize Calmar ratio (profit / max drawdown)."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.total_trades == 0:
            return 100.0
        profit = _finite(result.metrics.total_profit_pct, 0.0)
        drawdown = _finite(result.metrics.max_drawdown, 0.0)
        if drawdown <= 0:
            return -profit
        return -(profit / drawdown)


class WinRatioHyperoptLoss(HyperoptLoss):
    """Maximize win rate.

    Minimum-trade enforcement lives in the engine (`min_trades` penalty),
    so no hardcoded threshold here (previously a fixed 10 that fought the
    engine setting).
    """

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.total_trades == 0:
            return 100.0
        return -_finite(result.metrics.win_rate, 0.0)


class ProfitDrawdownHyperoptLoss(HyperoptLoss):
    """Maximize profit while penalizing drawdown."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.total_trades == 0:
            return 100.0
        profit = _finite(result.metrics.total_profit_pct, 0.0)
        drawdown = _finite(result.metrics.max_drawdown, 0.0)
        if drawdown <= 0:
            return -profit
        return -(profit / drawdown)


class OnlyProfitHyperoptLoss(HyperoptLoss):
    """Only optimize total profit, ignore risk."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.total_trades == 0:
            return 100.0
        return -_finite(result.metrics.total_profit, 0.0)


class OnlyProfitHyperoptLossDaily(HyperoptLoss):
    """Optimize daily profit (total profit / backtest days)."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.total_trades == 0:
            return 100.0
        total_profit = _finite(result.metrics.total_profit, 0.0)
        days = result.metrics.backtest_days or 0
        if days <= 0:
            # Fall back to equity-curve span via trade count only when the
            # engine could not determine calendar days (never trades/2 as a
            # day estimate — that systematically favored high-frequency
            # noise).
            days = 1
        return -(total_profit / days)


class MaxDrawdownHyperoptLoss(HyperoptLoss):
    """Minimize maximum drawdown."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.total_trades == 0:
            return 100.0
        return _finite(result.metrics.max_drawdown, 0.0)


class ExpectedDrawdownHyperoptLoss(HyperoptLoss):
    """Minimize expected drawdown (average of significant drawdowns)."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.total_trades == 0:
            return 100.0
        return _finite(result.metrics.max_drawdown, 0.0) * 0.7


class BankruptcyHyperoptLoss(HyperoptLoss):
    """Avoid bankruptcy risk (penalize high drawdown heavily)."""

    @staticmethod
    def calculate(result: BacktestResult) -> float:
        if result.metrics.total_trades == 0:
            return 100.0
        drawdown = _finite(result.metrics.max_drawdown, 0.0)
        profit = _finite(result.metrics.total_profit_pct, 0.0)
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


def _resolve_strategy_class(
    strategy_class: Optional[Type[IStrategy]],
    loaded: Any,
) -> Type[IStrategy]:
    """Normalize class-or-instance (from `_load_strategy`) to a class.

    `BacktestEngine._load_strategy` returns a strategy *instance*; param
    descriptors only resolve on the class, so sampling from an instance
    previously yielded an empty set and hyperopt silently no-opped.
    """
    if strategy_class is not None:
        return strategy_class
    if isinstance(loaded, type):
        return loaded
    return type(loaded)


def _get_optimizable_params(
    strategy_class: Type[IStrategy], spaces: str = "all"
) -> Dict[str, Any]:
    """
    Extract all hyperoptable parameters from a strategy class.

    Args:
        strategy_class: Strategy class (or instance — normalized to class).
        spaces: Space filter (`all`, or comma/space-separated list like
            `"buy sell roi stoploss trailing"` matching each parameter's
            `.space` attribute; params with `space=None` are included only
            under `all`).
    """
    if not isinstance(strategy_class, type):
        strategy_class = type(strategy_class)
    wanted: Optional[set] = None
    if spaces and spaces.strip().lower() != "all":
        wanted = {
            s.strip().lower()
            for s in spaces.replace(",", " ").split()
            if s.strip()
        }
    params = {}
    for attr_name in dir(strategy_class):
        attr = getattr(strategy_class, attr_name, None)
        if attr is None:
            continue

        if isinstance(attr, (BooleanParameter, IntParameter, DecimalParameter, CategoricalParameter)):
            if not attr.optimize:
                continue
            if wanted is not None:
                param_space = (getattr(attr, "space", None) or "").lower()
                if param_space not in wanted:
                    continue
            params[attr_name] = attr
        elif isinstance(attr, property):
            continue

    return params


def find_default_params_file(
    strategy_class: Any = None,
    strategy_name: Optional[str] = None,
    strategy_path: Optional[str] = None,
) -> Optional[str]:
    """Locate the conventional sibling params file, if any.

    Convention: `{strategy_path}/{StrategyName}.json` next to the strategy
    source (or next to the class's source file). Returns the path when the
    file exists, else None. Never raises.
    """
    import inspect
    from pathlib import Path as _Path

    candidates = []
    if strategy_class is not None:
        cls = strategy_class if isinstance(strategy_class, type) else type(strategy_class)
        try:
            src = inspect.getsourcefile(cls)
            if src:
                p = _Path(src)
                candidates.append(p.with_name(p.stem + ".json"))
        except (TypeError, OSError):
            pass
    if strategy_name and strategy_path:
        candidates.append(_Path(strategy_path) / f"{strategy_name}.json")
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def load_params_file(path: str) -> Dict[str, Any]:
    """Load a Freqtrade hyperopt params file (ft_stratparam_v).

    Returns the `params` mapping (roi/stoploss/trailing/buy/sell/
    protection). Raises HyperoptError on missing file or bad schema.
    """
    import json as _json
    from pathlib import Path as _Path

    filepath = _Path(path)
    if not filepath.exists():
        raise HyperoptError(f"Params file not found: {path}")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            payload = _json.load(f)
    except Exception as e:
        raise HyperoptError(f"Cannot parse params file {path}: {e}")
    params = (payload or {}).get("params")
    if not isinstance(params, dict):
        raise HyperoptError(
            f"Params file {path} has no 'params' mapping "
            "(expected Freqtrade ft_stratparam format)"
        )
    return params


def apply_params_file(
    strategy_class: Type[IStrategy], params_data: Dict[str, Any]
) -> Dict[str, int]:
    """Apply a params-file mapping onto strategy defaults.

    buy/sell entries override matching hyperoptable Parameter defaults
    (type-coerced, unknown names warn and skip); roi/stoploss/trailing
    sections override the plain strategy attributes. Returns counts of
    {applied, skipped} per section. Fresh strategy instances observe the
    new defaults, so call this before sampling.
    """
    counts = {"applied": 0, "skipped": 0}

    def _coerce(descriptor: Any, value: Any) -> Any:
        if isinstance(descriptor, BooleanParameter):
            return bool(value)
        if isinstance(descriptor, IntParameter):
            return max(int(descriptor.low), min(int(descriptor.high),
                                                int(float(value))))
        if isinstance(descriptor, DecimalParameter):
            decimals = max(0, int(getattr(descriptor, "decimals", 3)))
            return round(float(value), decimals)
        if isinstance(descriptor, CategoricalParameter):
            choices = list(getattr(descriptor, "choices", []) or [])
            if value in choices:
                return value
            logger.warning(
                f"Ignoring params-file value {value!r}: not in {choices}"
            )
            return None
        return value

    for space in ("buy", "sell"):
        for name, value in (params_data.get(space, {}) or {}).items():
            descriptor = getattr(strategy_class, name, None)
            if not isinstance(descriptor, (BooleanParameter, IntParameter,
                                           DecimalParameter,
                                           CategoricalParameter)):
                logger.warning(
                    f"Ignoring params-file entry '{space}.{name}': "
                    "no such hyperoptable parameter"
                )
                counts["skipped"] += 1
                continue
            try:
                coerced = _coerce(descriptor, value)
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"Ignoring params-file entry '{space}.{name}={value}': {e}"
                )
                counts["skipped"] += 1
                continue
            if coerced is None:
                counts["skipped"] += 1
                continue
            descriptor.default = coerced
            counts["applied"] += 1

    roi = params_data.get("roi")
    if isinstance(roi, dict) and roi:
        try:
            strategy_class.minimal_roi = {str(k): float(v) for k, v in roi.items()}
            counts["applied"] += 1
        except (TypeError, ValueError) as e:
            logger.warning(f"Ignoring params-file roi section: {e}")
            counts["skipped"] += 1

    stoploss = (params_data.get("stoploss", {}) or {}).get("stoploss")
    if stoploss is not None:
        try:
            strategy_class.stoploss = float(stoploss)
            counts["applied"] += 1
        except (TypeError, ValueError):
            counts["skipped"] += 1

    trailing = params_data.get("trailing", {}) or {}
    for attr in ("trailing_stop", "trailing_stop_positive",
                 "trailing_stop_positive_offset",
                 "trailing_only_offset_is_reached"):
        if attr in trailing:
            try:
                setattr(strategy_class, attr, trailing[attr])
                counts["applied"] += 1
            except Exception:
                counts["skipped"] += 1

    return counts


def _sample_params(
    params: Dict[str, Any], rng: Any = None
) -> Dict[str, Any]:
    """
    Sample a random set of parameter values.

    Args:
        params: Name -> Parameter descriptor mapping.
        rng: Random source with `choice`/`randint` (e.g. `random.Random`
            instance for deterministic parallel pre-sampling). Defaults to
            the global `random` module for backwards compatibility.
    """
    r = rng if rng is not None else random
    sampled = {}
    for name, param in params.items():
        if isinstance(param, BooleanParameter):
            sampled[name] = r.choice([True, False])
        elif isinstance(param, IntParameter):
            low, high = int(param.low), int(param.high)
            if high < low:
                low, high = high, low
            sampled[name] = r.randint(low, high)
        elif isinstance(param, DecimalParameter):
            decimals = max(0, int(getattr(param, "decimals", 3)))
            step = 10 ** -decimals
            span = float(param.high) - float(param.low)
            steps = int(round(span / step)) if step > 0 else 0
            if steps <= 0:
                sampled[name] = round(float(param.low), decimals)
            else:
                sampled[name] = round(
                    float(param.low) + r.randint(0, steps) * step, decimals
                )
        elif isinstance(param, CategoricalParameter):
            choices = list(getattr(param, "choices", []) or [])
            if not choices:
                logger.warning(f"Skipping CategoricalParameter {name}: empty choices")
                continue
            sampled[name] = r.choice(choices)
    return sampled


def _suggest_optuna_params(trial: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Suggest one value per Parameter via an Optuna trial (TPE)."""
    sampled: Dict[str, Any] = {}
    for name, param in params.items():
        if isinstance(param, BooleanParameter):
            sampled[name] = trial.suggest_categorical(name, [True, False])
        elif isinstance(param, IntParameter):
            low, high = int(param.low), int(param.high)
            if high < low:
                low, high = high, low
            sampled[name] = trial.suggest_int(name, low, high)
        elif isinstance(param, DecimalParameter):
            decimals = max(0, int(getattr(param, "decimals", 3)))
            step = 10 ** -decimals
            sampled[name] = trial.suggest_float(
                name, float(param.low), float(param.high), step=step
            )
        elif isinstance(param, CategoricalParameter):
            choices = list(getattr(param, "choices", []) or [])
            if not choices:
                logger.warning(f"Skipping CategoricalParameter {name}: empty choices")
                continue
            sampled[name] = trial.suggest_categorical(name, choices)
    return sampled


def _apply_params(strategy: IStrategy, params: Dict[str, Any]) -> None:
    """
    Apply parameter values to a strategy instance (per-instance storage).
    """
    cls = strategy.__class__
    for name, value in params.items():
        attr = getattr(cls, name, None)
        if isinstance(attr, (BooleanParameter, IntParameter, DecimalParameter, CategoricalParameter)):
            try:
                attr.__set__(strategy, value)
            except Exception as e:
                logger.warning(f"Failed to apply hyperopt param {name}={value}: {e}")
        elif hasattr(strategy, name):
            setattr(strategy, name, value)
        else:
            logger.warning(f"Ignoring unknown hyperopt param {name}")


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
            "loss": _finite(self.loss, fallback=100.0),
            "metrics": self.metrics,
            "epoch": self.epoch,
            "is_best": False,
        }


class HyperoptEngine:
    """
    Hyperparameter optimization engine for Bullseye.

    Supports:
    - Random search optimization (parallel via `jobs` ThreadPool)
    - Optuna TPE Bayesian optimization (`optimizer="optuna"`, opt-in)
    - Multiple loss functions
    - Holdout validation (`validation_timerange`/`validation_data`)
    - Result export

    Notes:
    - Optimization selects on the training timerange (in-sample). Pass a
      non-overlapping `validation_timerange` to detect overfitting; the
      winner is re-backtested out-of-sample and the gap is logged/exported.
    - Random search pre-samples deterministically from `random_state`, so
      `jobs=N` reproduces `jobs=1` results (modulo logging order).

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
        self._strategy_name: Optional[str] = None
        self._loss_function = "default"
        self._spaces = "all"
        self._random_state: Optional[int] = None
        self._timerange: Optional[str] = None
        self._optimizer = "random"
        self._validation_timerange: Optional[str] = None
        self._validation_metrics: Dict[str, Any] = {}
        self._validation_loss: Optional[float] = None
        self._walk_forward: Dict[str, Any] = {}
        self._params_file: Optional[str] = None

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
        slippage: Optional[float] = None,
        data: Optional[Dict[str, Any]] = None,
        optimizer: str = "random",
        validation_timerange: Optional[str] = None,
        validation_data: Optional[Dict[str, Any]] = None,
        walk_forward: int = 0,
        wf_min_train_candles: int = 50,
        params_file: Optional[str] = None,
    ) -> "HyperoptEngine":
        """
        Run hyperparameter optimization.

        Args:
            strategy_class: Strategy class
            strategy_name: Strategy name to load
            pairlist: Trading pairs
            timeframe: Candle timeframe
            timerange: Training time range (in-sample selection)
            epochs: Number of optimization epochs (random samples / Optuna trials)
            spaces: Parameter spaces to optimize (`all` or e.g. "buy sell")
            loss_function: Loss function name
            jobs: Parallel backtest workers for random search
                (`-1` = all CPUs, 1 = serial). Sampling is pre-seeded so
                results are reproducible regardless of completion order.
            min_trades: Minimum trades required
            stake_amount: Stake amount per trade
            max_open_trades: Max concurrent trades
            initial_balance: Starting balance
            fee: Fee rate
            export: Export filename
            random_state: Random seed for reproducibility (seeds `random`
                and `numpy` when available; random search uses a dedicated
                `random.Random` instance — no global side effects)
            slippage: Adverse fill adjustment passed to backtests
            data: In-memory OHLCV {pair: DataFrame} reused across epochs
                (avoids per-epoch disk reloads)
            optimizer: `random` (parallel random search) or `optuna`
                (TPE Bayesian optimization; requires `optuna` installed)
            validation_timerange: Optional holdout range for out-of-sample
                evaluation of the winner (overfit detection)
            validation_data: Optional in-memory OHLCV for validation
                (takes precedence over `validation_timerange` loading)
            walk_forward: Rolling walk-forward splits (>= 2 enables). Each
                fold re-optimizes on an expanding train window and is scored
                on the next unseen segment. `epochs` applies per fold.
            wf_min_train_candles: Minimum train candles per fold (folds with
                less are skipped)
            params_file: Freqtrade hyperopt params JSON (ft_stratparam_v).
                buy/sell values become the Parameter defaults and
                roi/stoploss/trailing sections override the strategy before
                sampling. None (default) auto-discovers the sibling
                `{Strategy}.json` next to the strategy file; pass "" to
                disable auto-discovery. Note this orients (not centers) the
                search: sampled dimensions still explore their full ranges;
                the file values govern non-searched params and the
                roi/stoploss/trailing setup.

        Returns:
            Self (for chaining)
        """
        if random_state is not None:
            try:
                import numpy as np

                np.random.seed(random_state)
            except ImportError:
                pass

        # jobs is honored inside _run_random (ThreadPool); Optuna trials
        # stay serial to avoid oversubscribing the GIL-bound backtests.

        # Load strategy (normalize class-or-instance; _load_strategy
        # returns an instance, not a class).
        loaded_instance = None
        if strategy_class is None:
            if strategy_name is None:
                strategy_name = self._config.strategy
            if strategy_name is None:
                raise HyperoptError("No strategy specified")
            loaded_instance = self._backtest_engine._load_strategy(strategy_name)
            strategy_class = _resolve_strategy_class(None, loaded_instance)
        else:
            strategy_class = _resolve_strategy_class(strategy_class, None)

        resolved_name = (
            strategy_name
            or getattr(strategy_class, "__name__", None)
            or (type(loaded_instance).__name__ if loaded_instance else "Unknown")
        )

        # Get loss function (normalize Freqtrade-style names)
        loss_key = (loss_function or "default").strip()
        norm = loss_key.replace("HyperOptLoss", "").replace("HyperoptLoss", "")
        norm = norm.replace("_", "").replace("-", "").lower()
        alias = {
            "default": "default", "sharpe": "sharpe", "sortino": "sortino",
            "calmar": "calmar", "winratio": "winratio", "win_rate": "winratio",
            "profitdrawdown": "profit_drawdown",
            "onlyprofit": "onlyprofit",
            "onlyprofitdaily": "onlyprofitdaily",
            "maxdrawdown": "maxdrawdown",
            "expecteddrawdown": "expecteddrawdown", "bankruptcy": "bankruptcy",
        }
        loss_cls = LOSS_FUNCTIONS.get(alias.get(norm, norm), HyperoptLoss)
        if loss_cls is HyperoptLoss and alias.get(norm, norm) not in LOSS_FUNCTIONS:
            logger.warning(f"Unknown loss function '{loss_function}', using default")
        loss_fn = loss_cls.calculate

        # Params file: explicit path wins; empty string disables;
        # otherwise auto-discover the sibling {Strategy}.json so a
        # shipped tuning applies by default (loudly logged).
        self._params_file = params_file
        if params_file is None:
            auto = find_default_params_file(
                strategy_class=strategy_class,
                strategy_name=strategy_name,
                strategy_path=self._config.strategy_path,
            )
            if auto:
                logger.info(f"Auto-using params file: {auto}")
                params_file = auto
                self._params_file = auto
        if params_file:
            file_params = load_params_file(params_file)
            counts = apply_params_file(strategy_class, file_params)
            logger.info(
                f"Params file {params_file}: applied "
                f"{counts['applied']}, skipped {counts['skipped']}"
            )

        # Get optimizable parameters (honors spaces filter)
        params = _get_optimizable_params(strategy_class, spaces=spaces)
        if not params:
            logger.warning("No optimizable parameters found in strategy. "
                           "Use optimize=True on IntParameter/DecimalParameter/etc. "
                           f"(spaces='{spaces}')")
            return self

        logger.warning(
            "Hyperopt is IN-SAMPLE optimization on the given timerange — "
            "best_params may overfit. Validate on unseen data before trading."
        )
        logger.info(
            f"Hyperopt: {len(params)} parameters to optimize "
            f"(spaces='{spaces}'), {epochs} epochs, loss='{loss_key}'"
        )

        # Run optimization
        start_time = time.time()
        resolved_timeframe = timeframe or getattr(strategy_class, "timeframe", "5m")
        resolved_pairlist = pairlist or self._backtest_engine._get_pairlist()
        self._strategy_name = resolved_name
        self._loss_function = loss_key
        self._spaces = spaces
        self._random_state = random_state
        self._timerange = timerange
        self._optimizer = optimizer
        self._validation_timerange = validation_timerange
        self._validation_metrics: Dict[str, Any] = {}
        self._validation_loss: Optional[float] = None
        self._walk_forward: Dict[str, Any] = {}

        bt_kwargs = dict(
            pairlist=resolved_pairlist,
            timeframe=resolved_timeframe,
            timerange=timerange,
            stake_amount=stake_amount,
            max_open_trades=max_open_trades,
            initial_balance=initial_balance,
            fee=fee,
            slippage=slippage,
            data=data,
            # Forward the raw flag (None/"" decides auto/disabled per run).
            params_file=params_file,
        )

        # Walk-forward mode: rolling re-optimization per expanding window.
        try:
            wf_splits = int(walk_forward or 0)
        except (TypeError, ValueError):
            wf_splits = 0
        if wf_splits >= 2:
            if validation_timerange is not None or validation_data is not None:
                logger.warning(
                    "walk_forward>=2 takes over validation: explicit "
                    "validation_* is ignored (each fold has its own holdout)."
                )
            self._run_walk_forward(
                strategy_class=strategy_class,
                params=params,
                loss_fn=loss_fn,
                epochs=epochs,
                n_splits=wf_splits,
                min_train_candles=wf_min_train_candles,
                pairlist=resolved_pairlist,
                timeframe=resolved_timeframe,
                timerange=timerange,
                data=data,
                bt_base_kwargs=dict(
                    stake_amount=stake_amount,
                    max_open_trades=max_open_trades,
                    initial_balance=initial_balance,
                    fee=fee,
                    slippage=slippage,
                ),
                min_trades=min_trades,
                optimizer=optimizer,
                jobs=jobs,
                random_state=random_state,
                spaces=spaces,
                loss_key=loss_key,
            )
            elapsed = time.time() - start_time
            n_folds = len((self._walk_forward or {}).get("folds", []))
            logger.info(
                f"Walk-forward complete: {n_folds} folds x {epochs} epochs "
                f"in {elapsed:.1f}s"
            )
            if export:
                self._export_results(export)
            return self

        if optimizer == "optuna":
            self._run_optuna(
                strategy_class=strategy_class,
                params=params,
                epochs=epochs,
                loss_fn=loss_fn,
                min_trades=min_trades,
                bt_kwargs=bt_kwargs,
                random_state=random_state,
                jobs=jobs,
            )
        else:
            if optimizer not in ("random", None):
                logger.warning(
                    f"Unknown optimizer '{optimizer}', falling back to random search"
                )
            self._run_random(
                strategy_class=strategy_class,
                params=params,
                epochs=epochs,
                loss_fn=loss_fn,
                min_trades=min_trades,
                bt_kwargs=bt_kwargs,
                random_state=random_state,
                jobs=jobs,
            )

        elapsed = time.time() - start_time
        logger.info(
            f"Hyperopt complete: {len(self._results)}/{epochs} epochs "
            f"in {elapsed:.1f}s (optimizer={getattr(self, '_optimizer', 'random')})"
        )

        # Out-of-sample validation of the winner (overfit detection).
        if self._best_params and (
            validation_timerange is not None or validation_data is not None
        ):
            self._run_validation(
                strategy_class=strategy_class,
                loss_fn=loss_fn,
                min_trades=min_trades,
                bt_kwargs=bt_kwargs,
                validation_timerange=validation_timerange,
                validation_data=validation_data,
            )

        # Export results
        if export:
            self._export_results(export)

        return self

    # ==================== Walk-forward ====================

    @staticmethod
    def _filter_data_by_timerange(
        data: Dict[str, Any], timerange: Optional[str]
    ) -> Dict[str, Any]:
        """Apply a `YYYYMMDD-YYYYMMDD` filter to in-memory frames.

        Delegates to the engine helper so walk-forward windows and
        in-memory backtests share identical, end-of-day-inclusive bounds.
        """
        return BacktestEngine._filter_frames_by_timerange(data, timerange)

    def _load_full_data(
        self,
        pairlist: List[str],
        timeframe: str,
        timerange: Optional[str],
        data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Load + clean the full-range dataset walk-forward splits from."""
        if data is not None:
            cleaned = self._backtest_engine._clean_data(dict(data))
            return self._filter_data_by_timerange(cleaned, timerange)
        loaded = self._backtest_engine._load_data(pairlist, timeframe, timerange)
        return self._backtest_engine._clean_data(loaded)

    @staticmethod
    def _split_walk_forward(
        data: Dict[str, Any], n_splits: int, min_train_candles: int
    ) -> List[Dict[str, Any]]:
        """Split into expanding train / next-segment test folds.

        Mirrors `sklearn.model_selection.TimeSeriesSplit(n_splits)`: the
        unified timeline is cut into `n_splits + 1` contiguous segments;
        fold `i` trains on segments `[0..i]` and tests on segment `i + 1`.
        Folds whose train side is shorter than `min_train_candles`
        (unified count) are skipped.
        """
        all_dates = sorted(
            {dt for df in data.values() for dt in df["date"]}
        )
        total = len(all_dates)
        segments = n_splits + 1
        if total < segments:
            raise HyperoptError(
                f"Not enough candles ({total}) for "
                f"walk_forward={n_splits} (need >= {segments})"
            )
        base = total // segments
        remainder = total % segments
        bounds = [0]
        for s in range(segments):
            bounds.append(bounds[-1] + base + (1 if s < remainder else 0))

        folds: List[Dict[str, Any]] = []
        for i in range(n_splits):
            train_dates = set(all_dates[bounds[0]:bounds[i + 1]])
            test_dates = set(all_dates[bounds[i + 1]:bounds[i + 2]])
            if len(train_dates) < min_train_candles or not test_dates:
                logger.warning(
                    f"Walk-forward fold {i + 1} skipped: train "
                    f"{len(train_dates)} candles (< {min_train_candles}) or "
                    "empty test segment"
                )
                continue
            train_data: Dict[str, Any] = {}
            test_data: Dict[str, Any] = {}
            for pair, df in data.items():
                tr = df[df["date"].isin(train_dates)].reset_index(drop=True)
                te = df[df["date"].isin(test_dates)].reset_index(drop=True)
                if not tr.empty:
                    train_data[pair] = tr
                if not te.empty:
                    test_data[pair] = te
            if not train_data or not test_data:
                logger.warning(f"Walk-forward fold {i + 1} skipped: empty side")
                continue
            folds.append({
                "fold": i + 1,
                "train_start": all_dates[bounds[0]],
                "train_end": all_dates[bounds[i + 1] - 1],
                "test_start": all_dates[bounds[i + 1]],
                "test_end": all_dates[bounds[i + 2] - 1],
                "train_data": train_data,
                "test_data": test_data,
            })
        if not folds:
            raise HyperoptError("All walk-forward folds skipped (too little data)")
        return folds

    def _run_walk_forward(
        self,
        strategy_class: Type[IStrategy],
        params: Dict[str, Any],
        loss_fn: Any,
        epochs: int,
        n_splits: int,
        min_train_candles: int,
        pairlist: List[str],
        timeframe: str,
        timerange: Optional[str],
        data: Optional[Dict[str, Any]],
        bt_base_kwargs: Dict[str, Any],
        min_trades: int,
        optimizer: str,
        jobs: Any,
        random_state: Optional[int],
        spaces: str,
        loss_key: str,
    ) -> None:
        """Re-optimize per expanding window; score each winner forward."""
        from bullseye.optimize.hyperopt import HyperoptEngine as _ChildEngine

        full = self._load_full_data(pairlist, timeframe, timerange, data)
        if not full:
            raise HyperoptError("No data available for walk-forward")
        folds = self._split_walk_forward(full, n_splits, min_train_candles)
        logger.warning(
            f"Walk-forward: {len(folds)} folds x {epochs} epochs "
            f"(optimizer={optimizer}); cost ~{len(folds) * epochs} backtests. "
            "Each fold re-optimizes on its train window and is scored on "
            "the next unseen segment."
        )

        fold_results: List[Dict[str, Any]] = []
        for f in folds:
            seed = None if random_state is None else int(random_state) + f["fold"]
            child = _ChildEngine(self._config)
            child.run(
                strategy_class=strategy_class,
                pairlist=pairlist,
                timeframe=timeframe,
                epochs=epochs,
                spaces=spaces,
                loss_function=loss_key,
                jobs=jobs,
                optimizer=optimizer,
                min_trades=min_trades,
                random_state=seed,
                data=f["train_data"],
                **bt_base_kwargs,
            )
            if not child.best_params:
                logger.warning(f"Walk-forward fold {f['fold']}: no winner, skipped")
                continue
            # Score the fold winner on its holdout segment.
            val_strategy = strategy_class()
            _apply_params(val_strategy, child.best_params)
            val_kwargs = dict(
                bt_base_kwargs,
                pairlist=pairlist,
                timeframe=timeframe,
                data=f["test_data"],
            )
            try:
                engine = BacktestEngine(self._config)
                val_result = engine.run(
                    strategy_instance=val_strategy, **val_kwargs
                )
            except Exception as e:
                logger.warning(f"Walk-forward fold {f['fold']} test failed: {e}")
                continue
            if val_result.metrics.total_trades < min_trades:
                val_loss: float = 100.0 + (
                    min_trades - val_result.metrics.total_trades
                )
            else:
                try:
                    val_loss = _finite(float(loss_fn(val_result)), 100.0)
                except Exception:
                    val_loss = 100.0
            train_loss = _finite(child.best_loss, 100.0)
            fold_results.append({
                "fold": f["fold"],
                "train_start": str(f["train_start"]),
                "train_end": str(f["train_end"]),
                "test_start": str(f["test_start"]),
                "test_end": str(f["test_end"]),
                "best_params": dict(child.best_params),
                "train_loss": train_loss,
                "train_metrics": dict(child.best_metrics),
                "test_loss": val_loss,
                "test_metrics": val_result.metrics.to_dict(),
                "gap": val_loss - train_loss,
            })
            logger.info(
                f"WF fold {f['fold']}/{len(folds)}: train_loss={train_loss:.4f} "
                f"test_loss={val_loss:.4f} gap={val_loss - train_loss:+.4f}"
            )
            # Fold trials contribute to the global trial list for export.
            for hr in child.results:
                self._results.append(hr)

        if not fold_results:
            raise HyperoptError("Walk-forward produced no scored folds")

        # Aggregate: worst-case-aware summary + most generalizable winner.
        import statistics as _stats

        test_losses = [r["test_loss"] for r in fold_results]
        gaps = [r["gap"] for r in fold_results]
        summary = {
            "n_folds": len(fold_results),
            "epochs_per_fold": epochs,
            "avg_test_loss": sum(test_losses) / len(test_losses),
            "median_test_loss": _stats.median(test_losses),
            "worst_test_loss": max(test_losses),
            "avg_gap": sum(gaps) / len(gaps),
            "param_stability": {
                name: len({repr(r["best_params"].get(name)) for r in fold_results})
                for name in params
            },
        }
        # Winner = lowest holdout loss (most generalizable, not best in-sample).
        winner = min(fold_results, key=lambda r: r["test_loss"])
        summary["winner_fold"] = winner["fold"]
        self._walk_forward = {"folds": fold_results, "summary": summary}
        self._best_params = dict(winner["best_params"])
        self._best_loss = float(winner["train_loss"])
        self._best_metrics = dict(winner["train_metrics"])
        self._validation_metrics = dict(winner["test_metrics"])
        self._validation_loss = float(winner["test_loss"])
        self._validation_timerange = (
            f"{winner['test_start']}..{winner['test_end']}"
        )
        if summary["avg_gap"] > 0:
            logger.warning(
                f"Walk-forward avg gap +{summary['avg_gap']:.4f} "
                f"(avg test {summary['avg_test_loss']:.4f}): params vary "
                f"{summary['param_stability']} — prefer stable params."
            )

    def _evaluate_sampled(
        self,
        strategy_class: Type[IStrategy],
        sampled: Dict[str, Any],
        loss_fn: Any,
        min_trades: int,
        bt_kwargs: Dict[str, Any],
    ) -> Optional[HyperoptResult]:
        """Build one sampled strategy instance and backtest it (thread-safe).

        Each call constructs a fresh `BacktestEngine` so parallel workers
        never share the mutable per-run state (`_fee_rate`, `_fee_model`,
        `_callback_failures`) on `self._backtest_engine`.
        """
        try:
            strategy = strategy_class()
        except Exception as e:
            logger.debug(f"Strategy instantiation failed: {e}")
            return None
        _apply_params(strategy, sampled)
        try:
            engine = BacktestEngine(self._config)
            result = engine.run(strategy_instance=strategy, **bt_kwargs)
        except Exception as e:
            logger.debug(f"Backtest failed for {sampled}: {e}")
            return None
        if result.metrics.total_trades < min_trades:
            loss = 100.0 + (min_trades - result.metrics.total_trades)
        else:
            try:
                loss = float(loss_fn(result))
            except Exception as e:
                logger.debug(f"Loss failed for {sampled}: {e}")
                return None
            loss = _finite(loss, fallback=100.0)
        return HyperoptResult(
            params=dict(sampled),
            loss=loss,
            metrics=result.metrics.to_dict(),
            epoch=0,
        )

    def _record_results(self, outcomes: List[HyperoptResult], epochs: int) -> None:
        """Store epoch-ordered outcomes and track best (deterministic)."""
        outcomes.sort(key=lambda r: r.epoch)
        for hr in outcomes:
            self._results.append(hr)
            if hr.loss < self._best_loss:
                self._best_loss = hr.loss
                self._best_params = dict(hr.params)
                self._best_metrics = dict(hr.metrics)
                logger.info(
                    f"Epoch {hr.epoch}/{epochs}: New best! loss={hr.loss:.6f}, "
                    f"trades={hr.metrics.get('total_trades')}, "
                    f"profit={hr.metrics.get('total_profit', 0):.4f}"
                )
            elif hr.epoch % 10 == 0:
                logger.info(
                    f"Epoch {hr.epoch}/{epochs}: loss={hr.loss:.6f}, "
                    f"best_loss={self._best_loss:.6f}"
                )

    def _resolve_workers(self, jobs: Any, epochs: int) -> int:
        """Normalize `jobs` to a worker count (1 = serial)."""
        try:
            j = int(jobs) if jobs is not None else 1
        except (TypeError, ValueError):
            return 1
        if j < 0:
            import os as _os

            j = _os.cpu_count() or 1
        if j <= 1 or epochs <= 1:
            return 1
        return max(1, min(j, epochs))

    def _run_random(
        self,
        strategy_class: Type[IStrategy],
        params: Dict[str, Any],
        epochs: int,
        loss_fn: Any,
        min_trades: int,
        bt_kwargs: Dict[str, Any],
        random_state: Optional[int],
        jobs: Any,
    ) -> None:
        """Random search with deterministic pre-sampling + parallel backtests."""
        import random as _random

        workers = self._resolve_workers(jobs, epochs)
        # Pre-sample sequentially with a dedicated RNG so results are
        # reproducible regardless of worker completion order (no global
        # random side effects).
        rng = _random.Random(random_state)
        sampled_list = [_sample_params(params, rng=rng) for _ in range(epochs)]

        if workers == 1:
            outcomes: List[HyperoptResult] = []
            for i, sampled in enumerate(sampled_list, start=1):
                hr = self._evaluate_sampled(
                    strategy_class, sampled, loss_fn, min_trades, bt_kwargs
                )
                if hr is None:
                    continue
                hr.epoch = i
                outcomes.append(hr)
            self._record_results(outcomes, epochs)
            return

        from concurrent.futures import ThreadPoolExecutor, as_completed

        logger.info(f"Hyperopt parallel random search with {workers} workers")
        futures = {}
        outcomes = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i, sampled in enumerate(sampled_list, start=1):
                fut = pool.submit(
                    self._evaluate_sampled,
                    strategy_class, sampled, loss_fn, min_trades, bt_kwargs,
                )
                futures[fut] = i
            for fut in as_completed(futures):
                try:
                    hr = fut.result()
                except Exception as e:
                    logger.debug(f"Epoch worker failed: {e}")
                    continue
                if hr is None:
                    continue
                hr.epoch = futures[fut]
                outcomes.append(hr)
        self._record_results(outcomes, epochs)

    def _run_optuna(
        self,
        strategy_class: Type[IStrategy],
        params: Dict[str, Any],
        epochs: int,
        loss_fn: Any,
        min_trades: int,
        bt_kwargs: Dict[str, Any],
        random_state: Optional[int],
        jobs: Any,
    ) -> None:
        """Bayesian optimization via Optuna TPE (opt-in)."""
        try:
            import optuna as _optuna
        except ImportError:
            logger.warning("optuna not installed; falling back to random search")
            return self._run_random(
                strategy_class, params, epochs, loss_fn, min_trades,
                bt_kwargs, random_state, 1,
            )

        sampler: Any = None
        try:
            from optuna.samplers import TPESampler

            sampler = TPESampler(seed=random_state)
        except Exception:
            sampler = None
        study = _optuna.create_study(direction="minimize", sampler=sampler)
        # Trial bookkeeping stays local (thread-safe); epochs map to
        # trial.number + 1 in completion order of suggestion (serial).
        collected: List[Any] = []

        def _objective(trial: Any) -> float:
            sampled = _suggest_optuna_params(trial, params)
            hr = self._evaluate_sampled(
                strategy_class, sampled, loss_fn, min_trades, bt_kwargs
            )
            if hr is None:
                return 100.0
            collected.append((trial.number + 1, hr))
            return float(hr.loss)

        _optuna.logging.set_verbosity(_optuna.logging.WARNING)
        # Serial trials: backtests release little GIL (pandas/numpy), and
        # parallel Optuna trials would oversubscribe; use optimizer="random"
        # with jobs=N for parallel search.
        study.optimize(_objective, n_trials=epochs)
        outcomes = []
        for epoch_no, hr in collected:
            hr.epoch = epoch_no
            outcomes.append(hr)
        self._record_results(outcomes, epochs)

    def _run_validation(
        self,
        strategy_class: Type[IStrategy],
        loss_fn: Any,
        min_trades: int,
        bt_kwargs: Dict[str, Any],
        validation_timerange: Optional[str],
        validation_data: Optional[Dict[str, Any]],
    ) -> None:
        """Re-backtest the winner on unseen data and report the gap."""
        try:
            strategy = strategy_class()
        except Exception as e:
            logger.warning(f"Validation skipped (instantiation failed): {e}")
            return
        _apply_params(strategy, self._best_params)
        val_kwargs = dict(bt_kwargs)
        if validation_timerange is not None:
            val_kwargs["timerange"] = validation_timerange
        if validation_data is not None:
            val_kwargs["data"] = validation_data
        try:
            engine = BacktestEngine(self._config)
            result = engine.run(strategy_instance=strategy, **val_kwargs)
        except Exception as e:
            logger.warning(f"Validation backtest failed: {e}")
            return
        self._validation_metrics = result.metrics.to_dict()
        if result.metrics.total_trades < min_trades:
            self._validation_loss = 100.0 + (
                min_trades - result.metrics.total_trades
            )
        else:
            try:
                self._validation_loss = _finite(float(loss_fn(result)), 100.0)
            except Exception:
                self._validation_loss = 100.0
        train_loss = _finite(self._best_loss, 0.0)
        gap = (self._validation_loss or 0.0) - train_loss
        if gap > 0:
            logger.warning(
                f"Validation loss {self._validation_loss:.4f} worse than train "
                f"{train_loss:.4f} (gap +{gap:.4f}) — best_params may overfit. "
                f"train_profit={self._best_metrics.get('total_profit', 0):.2f} vs "
                f"val_profit={self._validation_metrics.get('total_profit', 0):.2f}"
            )
        else:
            logger.info(
                f"Validation loss {self._validation_loss:.4f} vs train "
                f"{train_loss:.4f} (gap {gap:+.4f})"
            )

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
    def validation_metrics(self) -> Dict[str, Any]:
        """Out-of-sample metrics for the winner (empty if no validation)."""
        return dict(getattr(self, "_validation_metrics", {}) or {})

    @property
    def validation_loss(self) -> Optional[float]:
        """Out-of-sample loss for the winner (None if no validation)."""
        return getattr(self, "_validation_loss", None)

    @property
    def walk_forward(self) -> Dict[str, Any]:
        """Walk-forward folds + summary (empty if disabled)."""
        import copy

        return copy.deepcopy(getattr(self, "_walk_forward", {}) or {})

    @property
    def results(self) -> List[HyperoptResult]:
        """Get all results."""
        return self._results.copy()

    def get_results_sorted(self, ascending: bool = True) -> List[HyperoptResult]:
        """Get results sorted by loss."""
        return sorted(self._results, key=lambda x: x.loss, reverse=not ascending)

    def _export_results(self, filepath: Optional[str] = None) -> str:
        """Export hyperopt results to strict-JSON file.

        Default name follows the {strategy}-hyperopt-{timerange}-{timestamp}
        convention so runs are identifiable without opening them.
        """
        if filepath is None:
            results_dir = Path("user_data/hyperopt")
            results_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            strategy = "".join(
                c for c in str(getattr(self, "_strategy_name", "")
                               or "hyperopt").strip()
                if c.isalnum() or c in "._+-"
            ) or "hyperopt"
            timerange = "".join(
                c for c in str(getattr(self, "_timerange", "") or "").strip()
                if c.isalnum() or c in "._+-"
            )
            stem = f"{strategy}-hyperopt"
            if timerange:
                stem += f"-{timerange}"
            filepath = str(results_dir / f"{stem}-{timestamp}.json")

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        sorted_results = self.get_results_sorted()
        best_loss = _finite(getattr(self, "_best_loss", float("inf")), float("inf"))
        # JSON cannot represent inf — persist null instead (internal keeps inf
        # semantics for "no successful epoch").
        best_loss_json = None if best_loss == float("inf") else best_loss
        val_loss = getattr(self, "_validation_loss", None)
        data = {
            "strategy": getattr(self, "_strategy_name", None),
            "loss_function": getattr(self, "_loss_function", "default"),
            "spaces": getattr(self, "_spaces", "all"),
            "optimizer": getattr(self, "_optimizer", "random"),
            "timerange": getattr(self, "_timerange", None),
            "validation_timerange": getattr(self, "_validation_timerange", None),
            "random_state": getattr(self, "_random_state", None),
            "params_file": getattr(self, "_params_file", None),
            "best_params": self._best_params,
            "best_loss": best_loss_json,
            "best_metrics": self._best_metrics,
            "validation_loss": val_loss,
            "validation_metrics": getattr(self, "_validation_metrics", {}),
            "walk_forward": getattr(self, "_walk_forward", {}),
            "walk_forward_splits": len(
                (getattr(self, "_walk_forward", {}) or {}).get("folds", [])
            ),
            "total_epochs": len(self._results),
            # Backwards-compat top-level fields for list/show commands that
            # predate the nested schema.
            "total_profit": (self._best_metrics or {}).get("total_profit", 0),
            "total_profit_percent": (self._best_metrics or {}).get(
                "total_profit_pct", 0
            ),
            "results": [r.to_dict() for r in sorted_results[:100]],
        }

        # Mark best
        if data["results"]:
            data["results"][0]["is_best"] = True

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str, allow_nan=False)

        return filepath
