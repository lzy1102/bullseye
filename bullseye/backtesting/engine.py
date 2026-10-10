"""
Backtest Engine - Core backtesting engine for Bullseye.

Provides iterative backtesting that simulates the trading loop,
processing each candle sequentially and executing trades based
on strategy signals.

Compatible with Freqtrade IStrategy v3 interface.
"""
import importlib
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import pandas as pd

from bullseye.configuration.config import Config
from bullseye.data.history import ParquetDataHandler, FeatherDataHandler, JSONDataHandler
from bullseye.exceptions import (
    BacktestError,
    StrategyLoadError,
    StrategyValidationError,
)
from bullseye.order.position_manager import LocalTrade, PositionManager, MarketType
from bullseye.order.order_executor import OrderExecutor
from bullseye.order.fees import FeeModel
from bullseye.order.settlement import (
    SettlementType,
    get_settlement_date,
    init_settlement_detector,
    settlement_pending,
)
from bullseye.strategy.interface import (
    IStrategy,
    collect_informative_specs,
    merge_informative_pair,
    resolve_informative_pair,
)
from bullseye.wallets.wallets import Wallets

from .result import BacktestResult, BacktestTrade

logger = logging.getLogger(__name__)


class _ArrayRow:
    """Lightweight row accessor over per-column numpy arrays.

    Avoids pandas ``DataFrame.iloc[idx]`` Series construction in the hot
    backtesting loop (mixed-dtype row extraction is very slow).
    """

    __slots__ = ("_arrays", "_idx")

    def __init__(self, arrays: Dict[str, Any], idx: int):
        self._arrays = arrays
        self._idx = idx

    def get(self, column: str, default: Any = 0) -> Any:
        arr = self._arrays.get(column)
        if arr is None:
            return default
        return arr[self._idx]


class BacktestDataProvider:
    """
    DataProvider for backtesting mode.

    Instead of fetching from a live gateway, it reads from local data files
    and provides data frame by frame as the backtest progresses.
    """

    def __init__(
        self,
        data: Dict[str, pd.DataFrame],
        pairlist: List[str],
    ):
        self._data = data
        self._pairlist = pairlist
        self._current_index: Dict[str, int] = {p: 0 for p in pairlist}
        # Precomputed signal frames (indicators + entry/exit columns),
        # attached by the engine after vectorized precomputation.
        self._signal_data: Dict[str, pd.DataFrame] = {}

    def set_signal_data(self, signal_data: Dict[str, pd.DataFrame]) -> None:
        """Attach precomputed signal frames for analyzed reads."""
        self._signal_data = signal_data or {}

    def get_analyzed_dataframe(
        self, pair: str, timeframe: str
    ) -> tuple:
        """Freqtrade-compat: (analyzed_df_up_to_now, signal_date).

        Returns the precomputed signal frame sliced to closed candles only
        (mirrors historic_ohlcv's no-lookahead rule). Falls back to raw
        OHLCV when no signal frame is attached.
        """
        df = self._signal_data.get(pair, self._data.get(pair))
        if df is None or df.empty:
            return pd.DataFrame(), None
        idx = self._current_index.get(pair, len(df))
        if idx <= 0:
            return pd.DataFrame(), None
        sliced = df.iloc[:idx]
        last_date = sliced["date"].iloc[-1] if "date" in sliced else None
        return sliced.reset_index(drop=True), last_date

    def historic_ohlcv(
        self,
        pair: str,
        timeframe: str,
        limit: Optional[int] = None,
        startup_candles: Optional[int] = None,
    ) -> pd.DataFrame:
        df = self._data.get(pair)
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        idx = self._current_index.get(pair, len(df))
        if idx == 0:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        end = idx
        start = max(0, end - (limit or startup_candles or len(df)))
        return df.iloc[start:end].reset_index(drop=True)

    def get_dataframe_up_to(self, pair: str, index: int) -> pd.DataFrame:
        """
        Get the dataframe up to (and including) the given index.

        Returns a basic slice sharing the underlying data blocks (cheap);
        original index labels are preserved. Callers must not mutate the
        returned frame.
        """
        df = self._data.get(pair)
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        if index <= 0:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        return df.iloc[:index]

    def set_current_index(self, pair: str, index: int) -> None:
        self._current_index[pair] = index

    def current_whitelist(self) -> List[str]:
        return self._pairlist.copy()

    def get_pairlist(self) -> List[str]:
        return self._pairlist.copy()

    def runmode(self) -> str:
        return "backtest"

    def send_msg(self, message: str, *, msg_type: str = "info") -> None:
        pass

    def get_messages(self) -> List[str]:
        return []


class BacktestEngine:
    """
    Backtesting engine for Bullseye.

    Simulates the trading loop by iterating through historical candles,
    running strategy analysis, and executing trades based on signals.

    Features:
    - 100% Freqtrade strategy compatible
    - Supports stoploss, trailing stop, ROI
    - Supports custom entry/exit callbacks
    - Supports T+1 settlement rules for stocks
    - Detailed result metrics and export

    Usage:
        engine = BacktestEngine(config)
        result = engine.run(
            strategy_class=MyStrategy,
            pairlist=["BTC/USDT", "ETH/USDT"],
            timeframe="5m",
            timerange="20240101-20241231",
        )
        print(result.metrics)
    """

    def __init__(self, config: Optional[Config] = None):
        self._config = config or Config()
        self._fee_rate = 0.001
        # Optional structured fee model (commission min / stamp duty / transfer)
        self._fee_model: Optional[FeeModel] = FeeModel.from_config(self._config)
        # Adverse fill price adjustment (e.g. 0.001 = 0.1% worse on both sides)
        self._slippage_rate = 0.0
        self._data_handler = self._create_data_handler()
        # Count of strategy-callback failures swallowed per run (visibility)
        self._callback_failures = 0

    def _calc_fee(self, value: float, is_sell: bool) -> float:
        """Transaction fee: structured model when configured, else flat rate."""
        if self._fee_model is not None:
            return self._fee_model.fee(value, is_sell)
        return value * self._fee_rate

    def _create_data_handler(self):
        data_dir = self._config.get("datadir", "user_data/data")
        fmt = self._config.get("dataformat_ohlcv", "parquet")
        if fmt == "feather":
            return FeatherDataHandler(data_dir)
        elif fmt == "json":
            return JSONDataHandler(data_dir)
        else:
            return ParquetDataHandler(data_dir)

    def _find_data_handler(self, pair: str, timeframe: str):
        """
        Try to find data for a pair across multiple directories and formats.

        Search order:
        1. user_data/data/{exchange}/{pair}-{timeframe}.{format}
        2. user_data/data/{pair}-{timeframe}.{format}
        3. Try all formats (parquet, feather, json)
        """
        exchange_name = self._config.exchange_name
        base_dir = Path(self._config.get("datadir", "user_data/data"))
        formats = ["parquet", "feather", "json"]

        search_dirs = [
            base_dir / exchange_name,
            base_dir,
        ]

        pair_filename = pair.replace("/", "_")
        for search_dir in search_dirs:
            for fmt in formats:
                filepath = search_dir / f"{pair_filename}-{timeframe}.{fmt}"
                if filepath.exists():
                    if fmt == "parquet":
                        return ParquetDataHandler(str(search_dir))
                    elif fmt == "feather":
                        return FeatherDataHandler(str(search_dir))
                    elif fmt == "json":
                        return JSONDataHandler(str(search_dir))

        return self._data_handler

    def _find_data_file(self, filename: str) -> Optional[Path]:
        """Locate a sidecar file ({pair}-{tf}.meta.json / {pair}.dividends.json).

        Mirrors the OHLCV search order (exchange subdir first, then base).
        """
        base_dir = Path(self._config.get("datadir", "user_data/data"))
        for search_dir in (base_dir / self._config.exchange_name, base_dir):
            candidate = search_dir / filename
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _normalize_adjust(value: Any) -> Optional[str]:
        """Normalize adjustment labels (None/'none'/'' mean unadjusted)."""
        if value is None:
            return None
        text = str(value).strip().lower()
        if text in ("", "none", "null", "unadjusted", "bfq"):
            return None
        return text

    def _validate_stock_adjust(self, pair: str, timeframe: str) -> None:
        """Verify a stock file's adjustment口径 matches the declared one.

        Declared口径 is `stock.adjust` (default qfq, matching the downloader).
        Explicit mismatches raise; legacy files without a sidecar only warn.
        Crypto pairs are never checked.
        """
        if self._detect_market_type(pair) != MarketType.STOCK:
            return
        declared = self._normalize_adjust(self._config.get("stock.adjust", "qfq"))
        meta_path = self._find_data_file(f"{pair.replace('/', '_')}-{timeframe}.meta.json")
        if meta_path is None:
            logger.warning(
                f"{pair} {timeframe}: no .meta.json sidecar (legacy download?) — "
                f"assuming declared adjust={declared or 'none'}. Re-download "
                "to record the口径."
            )
            return
        try:
            import json as _json

            with open(meta_path, "r", encoding="utf-8") as f:
                file_adjust = self._normalize_adjust((_json.load(f) or {}).get("adjust"))
        except Exception as e:
            logger.warning(f"Ignoring unreadable sidecar {meta_path}: {e}")
            return
        if file_adjust != declared:
            raise BacktestError(
                f"Adjustment mismatch for {pair} {timeframe}: file is "
                f"{file_adjust or 'unadjusted'} but stock.adjust declares "
                f"{declared or 'unadjusted'}. Re-download with matching "
                "--adjust or align stock.adjust (mixing qfq with unadjusted "
                "turns ex-div gaps into fake signals)."
            )

    @staticmethod
    def _parse_dividend_entries(raw: Any) -> List[tuple]:
        """Normalize dividend entries to [(date, cash_per_share)]."""
        import pandas as pd

        entries: List[tuple] = []
        if not raw:
            return entries
        items = raw if isinstance(raw, list) else []
        for item in items:
            try:
                if not isinstance(item, dict):
                    continue
                ex = pd.to_datetime(item.get("ex_date")).date()
                cash = float(item.get("cash_div", 0) or 0)
                if cash <= 0:
                    continue
                entries.append((ex, cash))
            except Exception:
                continue
        entries.sort(key=lambda e: e[0])
        return entries

    def _load_dividends(self, pair: str) -> List[tuple]:
        """Load a pair's dividend calendar from its sidecar JSON file."""
        if self._detect_market_type(pair) != MarketType.STOCK:
            return []
        div_path = self._find_data_file(f"{pair.replace('/', '_')}.dividends.json")
        if div_path is None:
            return []
        try:
            import json as _json

            with open(div_path, "r", encoding="utf-8") as f:
                payload = _json.load(f) or {}
            return self._parse_dividend_entries(payload.get("dividends"))
        except Exception as e:
            logger.warning(f"Ignoring unreadable dividends file {div_path}: {e}")
            return []

    def _dividend_credit_allowed(self, pair: str, timeframe: str) -> bool:
        """Whether sidecar cash dividends should be credited for a pair.

        Only unadjusted (raw) stock series qualify; adjusted files
        (qfq/hfq) and files without a sidecar (declared `stock.adjust`
        defaults to qfq) keep dividends embedded in the price series.
        """
        if self._detect_market_type(pair) != MarketType.STOCK:
            return False
        declared = self._normalize_adjust(self._config.get("stock.adjust", "qfq"))
        meta_path = self._find_data_file(
            f"{pair.replace('/', '_')}-{timeframe}.meta.json"
        )
        if meta_path is None:
            return declared is None
        try:
            import json as _json

            with open(meta_path, "r", encoding="utf-8") as f:
                file_adjust = self._normalize_adjust(
                    (_json.load(f) or {}).get("adjust")
                )
        except Exception:
            return declared is None
        return file_adjust is None

    def run(
        self,
        strategy_class: Optional[Type[IStrategy]] = None,
        strategy_name: Optional[str] = None,
        strategy_instance: Optional[IStrategy] = None,
        pairlist: Optional[List[str]] = None,
        timeframe: Optional[str] = None,
        timerange: Optional[str] = None,
        stake_amount: Optional[float] = None,
        max_open_trades: Optional[int] = None,
        initial_balance: Optional[float] = None,
        fee: Optional[float] = None,
        export: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        slippage: Optional[float] = None,
            dividends: Optional[Dict[str, Any]] = None,
        benchmark: Optional[Any] = None,
        params_file: Optional[str] = None,
    ) -> BacktestResult:
        """
        Run backtesting.

        Args:
            strategy_class: Strategy class to use
            strategy_name: Strategy name to load (if class not provided)
            strategy_instance: Pre-built strategy instance (e.g. hyperopt
                sampled params). Takes precedence; the instance is used
                as-is so caller-side parameter overrides are honored.
            pairlist: List of trading pairs
            timeframe: Candle timeframe
            timerange: Time range string (e.g., "20240101-20241231")
            stake_amount: Stake amount per trade
            max_open_trades: Maximum concurrent open trades
            initial_balance: Starting balance
            fee: Fee rate (e.g., 0.001 for 0.1%)
            export: Export filename for results
            data: In-memory OHLCV data {pair: DataFrame}; skips disk loading
            slippage: Adverse fill adjustment (e.g. 0.001 = 0.1% worse fills)
            dividends: In-memory dividend calendars
                {pair: [{"ex_date": date/str, "cash_div": float per share}]};
                disk-loaded runs read `{pair}.dividends.json` instead
            benchmark: Relative-performance baseline — a pair code loaded
                from disk (same timeframe/timerange, e.g. "000300.SH"), an
                OHLCV DataFrame with date/close, or a {date: close} dict.
                Missing files warn and continue without relative metrics.
            params_file: Freqtrade hyperopt params JSON applied onto the
                strategy (roi/stoploss/trailing + Parameter defaults).
                None (default) auto-discovers the sibling `{Strategy}.json`;
                pass "" to disable.

        Returns:
            BacktestResult with trades and metrics
        """
        # Load strategy (pre-built instance wins so hyperopt-sampled params
        # are not silently discarded by re-instantiation).
        if strategy_instance is not None:
            strategy = strategy_instance
        elif strategy_class:
            strategy = strategy_class()
        elif strategy_name:
            strategy = self._load_strategy(strategy_name)
        else:
            strategy_name = self._config.strategy
            if strategy_name:
                strategy = self._load_strategy(strategy_name)
            else:
                raise BacktestError("No strategy specified. Provide strategy_class or strategy_name.")

        # Params file: explicit path wins; empty string disables; otherwise
        # auto-discover the sibling {Strategy}.json (deferred import: the
        # optimize package depends on this engine).
        if params_file is None:
            from bullseye.optimize.hyperopt import find_default_params_file

            auto = find_default_params_file(
                strategy_class=strategy.__class__,
                strategy_name=(strategy_name
                               if isinstance(strategy_name, str) else None),
                strategy_path=self._config.strategy_path,
            )
            if auto:
                logger.info(f"Auto-using params file: {auto}")
                params_file = auto
        if params_file:
            from bullseye.optimize.hyperopt import (
                apply_params_file,
                load_params_file,
            )

            counts = apply_params_file(
                strategy.__class__, load_params_file(params_file)
            )
            logger.info(
                f"Params file {params_file}: applied "
                f"{counts['applied']}, skipped {counts['skipped']}"
            )

        # Apply config overrides
        pairlist = pairlist or self._get_pairlist()
        timeframe = timeframe or getattr(strategy, 'timeframe', None) or self._config.timeframe
        # "unlimited" stake is dynamic — keep None as marker instead of 0
        # so _check_entry can size from available balance per open slot.
        unlimited_stake = self._config.stake_amount_unlimited and stake_amount is None
        if stake_amount is None and not unlimited_stake:
            stake_amount = self._config.stake_amount
        max_open_trades = max_open_trades or self._config.max_open_trades
        # Freqtrade semantics: -1 means unlimited. The engine holds at most
        # one trade per pair, so the practical cap is len(pairlist).
        if max_open_trades is not None and int(max_open_trades) < 0:
            max_open_trades = len(pairlist)
        initial_balance = initial_balance or self._config.dry_run_wallet
        # Refresh structured model from current config (Config may have changed
        # after engine construction).
        self._fee_model = FeeModel.from_config(self._config)
        if fee is not None:
            # Explicit flat fee overrides any structured config
            self._fee_rate = fee
            self._fee_model = None
        else:
            # Honor flat fee from config when no structured model is set.
            # Previously backtest.fee was silently ignored (always 0.001).
            cfg_fee = self._config.get("backtest.fee", self._config.get("fee", None))
            if cfg_fee is not None and self._fee_model is None:
                try:
                    self._fee_rate = float(cfg_fee)
                except (TypeError, ValueError):
                    logger.warning(f"Ignoring invalid backtest.fee={cfg_fee!r}")
        self._callback_failures = 0

        # Position stacking (multiple concurrent trades per pair) is not
        # implemented in the iterative engine (open_trades is keyed by pair).
        # Fail loudly instead of silently returning single-position results.
        stacking = self._config.get(
            "backtest.position_stacking",
            self._config.get("position_stacking", False),
        )
        if stacking:
            raise BacktestError(
                "position_stacking=true is not supported by the backtest engine "
                "(one open trade per pair). Set position_stacking=false or "
                "implement stacking before backtesting."
            )

        # Slippage: explicit argument > config (backtest.slippage / slippage) > 0
        if slippage is not None:
            self._slippage_rate = slippage
        else:
            configured = self._config.get(
                "backtest.slippage", self._config.get("slippage", 0.0)
            )
            self._slippage_rate = float(configured or 0.0)

        logger.info(f"Starting backtest: strategy={strategy.__class__.__name__}, "
                     f"pairs={pairlist}, timeframe={timeframe}")

        # Apply settlement configuration (simple "t0"/"t1" string or dict)
        # so LocalTrade auto-detection honors user settings in backtests too.
        # ALWAYS reinitialize: the detector is process-global, so skipping
        # when unconfigured leaked a previous run's manual mode (e.g. a t1
        # backtest made every later crypto run treat BTC as T+1).
        settlement_cfg = self._config.settlement
        init_settlement_detector(settlement_cfg if settlement_cfg else {})

        # Load data (in-memory injection takes precedence over disk)
        from_disk = data is None
        if data is None:
            data = self._load_data(pairlist, timeframe, timerange)
        if not data:
            logger.error("No data available for backtesting")
            return BacktestResult(strategy_name=strategy.__class__.__name__)

        # Clean + validate data (sort, dedupe, tz-normalize).
        # In-memory `data=` previously skipped the cleaning that disk
        # loading applies, so unsorted/duplicated frames silently misaligned
        # signals via positional indexing.
        data = self._clean_data(data)
        # In-memory data must honor timerange too: validation / walk-forward
        # pass frames directly, and ignoring the window silently leaked the
        # training range into "out-of-sample" runs.
        if not from_disk and timerange:
            data = self._filter_frames_by_timerange(data, timerange)
        if not data:
            logger.error("No data available for backtesting")
            return BacktestResult(strategy_name=strategy.__class__.__name__)

        # Adjustment口径 check (disk loads only): refuse to mix qfq files
        # with an unadjusted declaration and vice versa.
        if from_disk:
            for pair in list(data.keys()):
                self._validate_stock_adjust(pair, timeframe)

        # Dividend calendars: explicit argument wins, else per-pair sidecar
        # files written by download-data (missing file = no dividends).
        if dividends is not None:
            dividend_map = {
                pair: self._parse_dividend_entries(entries)
                for pair, entries in dividends.items()
            }
        else:
            # Sidecar dividends apply to UNADJUSTED series only: qfq/hfq
            # prices are already continuous across ex-dates (the price
            # return embeds the payout), so cash crediting there double
            # counts. Explicit `dividends=` stays caller-responsibility.
            dividend_map = {
                pair: (self._load_dividends(pair)
                       if self._dividend_credit_allowed(pair, timeframe)
                       else [])
                for pair in data
            }
        try:
            dividend_tax = float(self._config.get("backtest.dividend_tax", 0.1))
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid backtest.dividend_tax")
            dividend_tax = 0.1
        self._dividends_paid = 0.0

        # Initialize components
        wallets = Wallets(self._config, initial_balance=initial_balance)
        position_manager = PositionManager(self._config, wallets)
        position_manager.set_strategy(strategy)
        order_executor = OrderExecutor(self._config, position_manager, wallets)
        order_executor.set_strategy(strategy)

        bt_dp = BacktestDataProvider(data, pairlist)
        strategy.dp = bt_dp
        strategy.wallets = wallets
        strategy.config = self._config.to_dict()

        # Call bot_start
        try:
            strategy.bot_start()
        except Exception as e:
            logger.warning(f"Strategy bot_start() failed: {e}", exc_info=True)

        # Run backtest
        trades = self._run_backtest_loop(
            strategy=strategy,
            data=data,
            pairlist=pairlist,
            timeframe=timeframe,
            wallets=wallets,
            position_manager=position_manager,
            order_executor=order_executor,
            bt_dp=bt_dp,
            max_open_trades=max_open_trades,
            stake_amount=stake_amount,
            initial_balance=initial_balance,
            dividends=dividend_map,
            dividend_tax=dividend_tax,
            timerange=timerange,
        )

        # Build result
        if self._callback_failures:
            logger.warning(
                f"Backtest finished with {self._callback_failures} "
                "strategy-callback failures (see warnings above)"
            )
        result = BacktestResult(
            strategy_name=strategy.__class__.__name__,
            trades=trades,
            config={
                "timeframe": timeframe,
                "pairlist": pairlist,
                "timerange": timerange,
                "stake_amount": stake_amount,
                "max_open_trades": max_open_trades,
                "initial_balance": initial_balance,
                "fee_rate": self._fee_rate,
                "callback_failures": self._callback_failures,
                "dividends_paid": getattr(self, "_dividends_paid", 0.0),
                "dividend_tax": dividend_tax,
                "benchmark": benchmark if isinstance(benchmark, str) else None,
            },
            equity_curve=getattr(self, "_last_equity_curve", []),
        )
        result.calculate_metrics(
            initial_balance=initial_balance,
            benchmark=self._resolve_benchmark(
                benchmark, timeframe, timerange, pairlist
            ),
        )

        # Fold ex-date dividend cash (credited to the wallet during the
        # loop) into the headline profit figures so metrics, final balance
        # and the equity curve agree. Trade-level profits stay pure price
        # PnL; the aggregate carries the cash component.
        dividends_paid = float(getattr(self, "_dividends_paid", 0.0) or 0.0)
        if dividends_paid:
            m = result.metrics
            m.total_profit += dividends_paid
            if initial_balance > 0:
                m.total_profit_pct = m.total_profit / initial_balance * 100
            if m.total_trades:
                m.avg_profit += dividends_paid / m.total_trades
            m.final_balance += dividends_paid

        # Export if requested
        if export:
            result.save(export)

        return result

    def _resolve_benchmark(
        self,
        benchmark: Optional[Any],
        timeframe: str,
        timerange: Optional[str],
        pairlist: List[str],
    ) -> Optional[Any]:
        """Normalize the `benchmark` argument to an OHLCV DataFrame.

        A pair code (e.g. "000300.SH" for 沪深300) is loaded from disk with
        the same timeframe/timerange; a missing file warns and yields None
        instead of failing the backtest. DataFrames/dicts pass through.
        """
        if benchmark is None or not isinstance(benchmark, str):
            return benchmark
        if benchmark in pairlist:
            logger.warning(
                f"Benchmark '{benchmark}' is also traded; relative metrics "
                "remain valid but interpret with care."
            )
        try:
            data = self._load_data([benchmark], timeframe, timerange)
            df = data.get(benchmark)
            if df is None or df.empty:
                logger.warning(
                    f"Benchmark data not found for '{benchmark}' "
                    f"{timeframe}; continuing without relative metrics. "
                    "Download it first, e.g. "
                    f"bullseye download-data --market stock --pairs {benchmark}"
                )
                return None
            return df
        except Exception as e:
            logger.warning(f"Benchmark load failed for '{benchmark}': {e}")
            return None

    def _load_strategy(self, strategy_name: str) -> IStrategy:
        """Load a strategy by name."""
        strategy_path = Path(self._config.strategy_path)
        if strategy_path.exists():
            sys.path.insert(0, str(strategy_path.parent))

        try:
            module = importlib.import_module(f"{strategy_path.name}.{strategy_name}")
            cls = getattr(module, strategy_name)
            instance = cls()
            if not isinstance(instance, IStrategy):
                raise StrategyValidationError(
                    strategy_name, [f"'{strategy_name}' does not implement IStrategy"]
                )
            return instance
        except (ImportError, AttributeError):
            pass

        try:
            module = importlib.import_module(strategy_name)
            cls = getattr(module, strategy_name)
            instance = cls()
            if not isinstance(instance, IStrategy):
                raise StrategyValidationError(
                    strategy_name, [f"'{strategy_name}' does not implement IStrategy"]
                )
            return instance
        except (ImportError, AttributeError):
            pass

        # Freqtrade-style resolution: scan the strategy directory for a
        # module defining the class (file name need not match, e.g.
        # sample_strategy.py defining SampleStrategy).
        if strategy_path.exists():
            for candidate in sorted(strategy_path.glob("*.py")):
                if candidate.name.startswith("_"):
                    continue
                try:
                    module = importlib.import_module(
                        f"{strategy_path.name}.{candidate.stem}"
                    )
                except ImportError:
                    continue
                cls = getattr(module, strategy_name, None)
                if cls is None:
                    continue
                try:
                    instance = cls()
                except TypeError:
                    continue
                if not isinstance(instance, IStrategy):
                    raise StrategyValidationError(
                        strategy_name,
                        [f"'{strategy_name}' does not implement IStrategy"],
                    )
                return instance

        raise StrategyLoadError(strategy_name)

    def _get_pairlist(self) -> List[str]:
        """Get pairlist from config."""
        pairlist_config = self._config.pairlist
        for pl_config in pairlist_config:
            method = pl_config.get("method", "")
            if method == "StaticPairList":
                pairs = pl_config.get("config", {}).get("pairs", [])
                if pairs:
                    return pairs
        return ["BTC/USDT"]

    @staticmethod
    def _normalize_dates(df: "pd.DataFrame") -> "pd.DataFrame":
        """Normalize the `date` column to tz-naive UTC for safe comparisons.

        Data files may be tz-aware while `timerange` bounds and settlement
        dates are naive (or vice versa); mixing them raises TypeError in
        pandas/datetime comparisons. Converting aware -> UTC -> naive keeps
        chronological order while making every downstream comparison safe.
        """
        df = df.copy()
        dates = pd.to_datetime(df["date"], utc=True)
        try:
            dates = dates.dt.tz_convert(None)
        except Exception:
            pass
        df["date"] = dates
        return df

    def _clean_data(
        self, data: Dict[str, "pd.DataFrame"]
    ) -> Dict[str, "pd.DataFrame"]:
        """Sort, dedupe, tz-normalize and validate OHLCV frames.

        Applied to both disk-loaded and in-memory `data=` frames so signal
        precomputation (positional indexing) can never silently misalign.
        """
        cleaned: Dict[str, "pd.DataFrame"] = {}
        required_cols = {"date", "open", "high", "low", "close", "volume"}
        for pair, df in data.items():
            if df is None or df.empty:
                logger.warning(f"No data for {pair}, skipping")
                continue
            missing = required_cols - set(df.columns)
            if missing:
                raise BacktestError(f"Data for {pair} missing columns: {sorted(missing)}")
            df = self._normalize_dates(df)
            # Drop exact-duplicate timestamps (keep last), then sort.
            before = len(df)
            df = df.drop_duplicates(subset="date", keep="last")
            if len(df) < before:
                logger.warning(
                    f"Removed {before - len(df)} duplicate candles for {pair}"
                )
            df = df.sort_values("date").reset_index(drop=True)
            # Basic OHLC sanity: high >= max(open, close), low <= min(...)
            # (only warn — some feeds include gaps/bad ticks).
            try:
                bad = df[(df["high"] < df[["open", "close"]].max(axis=1)) | (
                    df["low"] > df[["open", "close"]].min(axis=1))]
                if not bad.empty:
                    logger.warning(
                        f"{pair}: {len(bad)} candles have high/low "
                        "inconsistent with open/close"
                    )
            except Exception:
                pass
            if not df.empty:
                cleaned[pair] = df
        return cleaned

    def _load_data(
        self,
        pairlist: List[str],
        timeframe: str,
        timerange: Optional[str] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Load historical data for all pairs.
        """
        data = {}
        start_date = None
        end_date = None

        if timerange:
            parts = timerange.split("-")
            if len(parts) == 2:
                if parts[0]:
                    start_date = pd.Timestamp(parts[0])
                if parts[1]:
                    end_date = pd.Timestamp(parts[1])
            elif len(parts) == 1 and parts[0]:
                start_date = pd.Timestamp(parts[0])

        for pair in pairlist:
            handler = self._find_data_handler(pair, timeframe)
            df = handler.ohlcv_get(pair, timeframe)
            if df is None or df.empty:
                logger.warning(f"No data found for {pair} {timeframe}")
                continue

            if "date" not in df.columns:
                if df.index.name == "date" or isinstance(df.index, pd.DatetimeIndex):
                    df = df.reset_index()
                else:
                    raise BacktestError(
                        f"Data for {pair} has no 'date' column or DatetimeIndex. "
                        "Refusing to fabricate timestamps (previous behavior "
                        "generated date_range with an invalid freq and anchored "
                        "at now, silently breaking timerange filtering)."
                    )

            df = self._normalize_dates(df)

            # Timerange bounds are naive; df dates are normalized naive above,
            # so comparisons are always safe.
            if start_date is not None:
                start_naive = pd.Timestamp(start_date).tz_localize(None) \
                    if getattr(pd.Timestamp(start_date), "tzinfo", None) else start_date
                df = df[df["date"] >= start_naive]
            if end_date is not None:
                end_naive = pd.Timestamp(end_date).tz_localize(None) \
                    if getattr(pd.Timestamp(end_date), "tzinfo", None) else end_date
                # A date-only end bound (00:00) must include that whole
                # trading day; previously intraday frames silently dropped
                # the final day while daily frames kept it.
                end_naive = pd.Timestamp(end_naive)
                if end_naive == end_naive.normalize():
                    end_naive = end_naive + pd.Timedelta(days=1) \
                        - pd.Timedelta(nanoseconds=1)
                df = df[df["date"] <= end_naive]

            df = df.sort_values("date").reset_index(drop=True)

            if not df.empty:
                data[pair] = df

        return self._clean_data(data)

    @staticmethod
    def _filter_frames_by_timerange(
        data: Dict[str, Any], timerange: Optional[str]
    ) -> Dict[str, Any]:
        """Apply a `YYYYMMDD[-YYYYMMDD]` window to in-memory frames.

        Shared by the engine (in-memory `data=` runs) and the hyperopt
        walk-forward splitter. An end bound that is exactly midnight is
        treated as end-of-day so date-only windows include the final
        trading day for every timeframe.
        """
        if not timerange:
            return data
        parts = timerange.split("-")
        start = pd.Timestamp(parts[0]) if len(parts) > 0 and parts[0] else None
        end = None
        if len(parts) > 1 and parts[1]:
            end = pd.Timestamp(parts[1])
            if end == end.normalize():
                end = end + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        out: Dict[str, Any] = {}
        for pair, df in data.items():
            if df is None or getattr(df, "empty", False):
                continue
            f = df
            if start is not None:
                f = f[f["date"] >= start]
            if end is not None:
                f = f[f["date"] <= end]
            if not f.empty:
                # Positional signal/price reads downstream require a
                # RangeIndex; a slice keeps the original labels otherwise.
                out[pair] = f.reset_index(drop=True)
        return out

    def _load_informative_data(
        self,
        inf_pair: str,
        inf_tf: str,
        timerange: Optional[str],
    ) -> Optional[Any]:
        """Load (and clean) informative-timeframe data from disk."""
        try:
            handler = self._find_data_handler(inf_pair, inf_tf)
            df = handler.ohlcv_get(inf_pair, inf_tf)
        except Exception as e:
            logger.warning(
                f"Informative data load failed for {inf_pair} {inf_tf}: {e}"
            )
            return None
        if df is None or df.empty:
            return None
        try:
            cleaned = self._clean_data({inf_pair: df})
            return cleaned.get(inf_pair)
        except Exception as e:
            logger.warning(
                f"Informative data invalid for {inf_pair} {inf_tf}: {e}"
            )
            return None

    def _apply_informative(
        self,
        strategy: IStrategy,
        spec: Dict[str, Any],
        base_df: Any,
        base_pair: str,
        base_timeframe: str,
        inf_pair: str,
        inf_tf: str,
        data: Dict[str, pd.DataFrame],
        timerange: Optional[str],
        cache: Dict[tuple, Any],
    ) -> Any:
        """Run one @informative method and merge it into the base frame.

        Same pair + same timeframe reuses the base frame directly. Missing
        informative data warns and leaves the base frame untouched (never
        fails the run; strategies should guard optional informative columns
        with `in dataframe.columns`, as the sample strategy does).
        """
        try:
            if inf_pair == base_pair and inf_tf == base_timeframe:
                inf_df = base_df.copy()
            else:
                cache_key = (inf_pair, inf_tf)
                if cache_key not in cache:
                    cache[cache_key] = self._load_informative_data(
                        inf_pair, inf_tf, timerange
                    )
                inf_df = cache[cache_key]
                if inf_df is None or inf_df.empty:
                    logger.warning(
                        f"Informative {spec['method_name']} skipped: no data "
                        f"for {inf_pair} {inf_tf}. Download it first, e.g. "
                        f"bullseye download-data --market stock "
                        f"--pairs {inf_pair} --timeframes {inf_tf}"
                    )
                    return base_df
                inf_df = inf_df.copy()
            analyzed = spec["method"](inf_df, {"pair": inf_pair})
            if analyzed is None or getattr(analyzed, "empty", False):
                return base_df
            return merge_informative_pair(
                base_df, analyzed, base_timeframe, inf_tf
            )
        except Exception as e:
            logger.warning(
                f"Informative {spec.get('method_name')} failed for "
                f"{base_pair}: {e}. Continuing without it."
            )
            return base_df

    def _run_backtest_loop(
        self,
        strategy: IStrategy,
        data: Dict[str, pd.DataFrame],
        pairlist: List[str],
        timeframe: str,
        wallets: Wallets,
        position_manager: PositionManager,
        order_executor: OrderExecutor,
        bt_dp: BacktestDataProvider,
        max_open_trades: int,
        stake_amount: float,
        initial_balance: float,
        dividends: Optional[Dict[str, List[tuple]]] = None,
        dividend_tax: float = 0.1,
        timerange: Optional[str] = None,
    ) -> List[BacktestTrade]:
        """
        Main backtesting loop.

        Iterates through all candles chronologically, executing trades based
        on precomputed strategy signals (computed once per pair, freqtrade-style).

        `dividends` maps pair -> [(ex_date, cash_per_share)]; holders of
        record on ex-date are credited cash (net of `dividend_tax`) into
        the wallet before exits are evaluated.
        """
        # Build unified timeline
        all_dates = set()
        for pair, df in data.items():
            for dt in df["date"]:
                all_dates.add(dt)

        sorted_dates = sorted(all_dates)
        if not sorted_dates:
            return []

        # Build date-to-index mapping for each pair
        pair_date_index: Dict[str, Dict[datetime, int]] = {
            pair: dict(zip(df["date"], df.index))
            for pair, df in data.items()
        }

        # Precompute strategy signals once per pair (vectorized upfront).
        # Indicators must only depend on past data (rolling/EMA/shift etc.),
        # matching freqtrade semantics; non-causal operations would differ.
        #
        # @informative methods run first on their own timeframe/pair and are
        # merged into the base frame (lookahead-safe) before the base
        # populate_* calls — full Freqtrade multi-timeframe semantics.
        informative_specs = collect_informative_specs(strategy)
        informative_cache: Dict[tuple, Any] = {}
        if informative_specs:
            logger.info(
                f"Backtest informative: {len(informative_specs)} method(s) "
                f"({sorted({s['timeframe'] for s in informative_specs})})"
            )
        precomputed_signals: Dict[str, Any] = {}
        for pair, df in data.items():
            metadata = {"pair": pair}
            work_df = df.copy()
            for spec in informative_specs:
                inf_tf = spec["timeframe"]
                if not inf_tf:
                    continue
                inf_pair = resolve_informative_pair(
                    pair, spec["asset"],
                    stake_currency=self._config.stake_currency,
                )
                work_df = self._apply_informative(
                    strategy=strategy,
                    spec=spec,
                    base_df=work_df,
                    base_pair=pair,
                    base_timeframe=timeframe,
                    inf_pair=inf_pair,
                    inf_tf=inf_tf,
                    data=data,
                    timerange=timerange,
                    cache=informative_cache,
                )
            signal_df = strategy.populate_indicators(work_df, metadata)
            signal_df = strategy.populate_entry_trend(signal_df, metadata)
            signal_df = strategy.populate_exit_trend(signal_df, metadata)
            precomputed_signals[pair] = signal_df

        # Signal rows are read positionally against the price data, so a
        # strategy that dropped/reordered rows inside populate_* would
        # silently trade on misaligned signals. Fail loudly instead.
        for pair, signal_df in precomputed_signals.items():
            if len(signal_df) != len(data[pair]):
                raise BacktestError(
                    f"Signal misalignment for {pair}: populate_* returned "
                    f"{len(signal_df)} rows for {len(data[pair])} input candles. "
                    "populate_indicators/entry_trend/exit_trend must not "
                    "drop, reorder, or extend rows (use startup_candle_count "
                    "for warm-up periods instead of dropna())."
                )

        # Expose analyzed frames to strategies (get_analyzed_dataframe).
        bt_dp.set_signal_data(precomputed_signals)

        # Extract per-column numpy arrays once: O(1) scalar reads in the loop
        price_arrays: Dict[str, Dict[str, Any]] = {}
        signal_arrays: Dict[str, Dict[str, Any]] = {}
        for pair, df in data.items():
            price_arrays[pair] = {
                col: df[col].to_numpy()
                for col in ("date", "open", "high", "low", "close")
            }
            signal_arrays[pair] = {
                col: s[col].to_numpy() for col in s.columns
            } if (s := precomputed_signals.get(pair)) is not None else {}

        # Track open trades
        open_trades: Dict[str, LocalTrade] = {}
        closed_bt_trades: List[BacktestTrade] = []
        equity_curve: List[tuple] = []
        # Last processed candle index per pair, for mark-to-market of
        # pairs that have no candle at the current timestamp
        pair_last_index: Dict[str, int] = {}
        # Dividend calendars indexed by calendar date for O(1) lookup.
        div_by_date: Dict[str, Dict[Any, float]] = {}
        for _pair, _entries in (dividends or {}).items():
            _day_map: Dict[Any, float] = {}
            for _ex, _cash in (_entries or []):
                try:
                    _day = _ex.date() if hasattr(_ex, "date") else _ex
                    _day_map[_day] = _day_map.get(_day, 0.0) + float(_cash)
                except Exception:
                    continue
            if _day_map:
                div_by_date[_pair] = _day_map
        dividends_paid = 0.0
        # One credit per (pair, ex-date): intraday candles share the date.
        credited_divs: set = set()

        # Balance tracking for equity curve
        startup_candle_count = getattr(strategy, 'startup_candle_count', 30)
        startup_bars = startup_candle_count

        # Optional freqtrade-style fill semantics: entry/exit SIGNALS from
        # the previous closed candle execute at the current candle's open
        # (default false keeps same-bar close fills). Stop/ROI/trailing
        # remain level-based; custom_exit and DCA adds keep same-bar
        # semantics in this mode.
        fill_next_open = bool(
            self._config.get("backtest.fill_next_open", False)
        )

        logger.info(f"Backtest: {len(sorted_dates)} candles, {len(pairlist)} pairs")

        for date_idx, current_date in enumerate(sorted_dates):
            # Cash dividends on ex-dates, paid out BEFORE exits/entries:
            # a position opened strictly before the ex-date is the holder
            # of record and keeps the payout even if sold today, while a
            # position opened on the ex-date itself (entries run below)
            # was not entitled and receives nothing.
            if div_by_date:
                try:
                    today = current_date.date() \
                        if hasattr(current_date, "date") else current_date
                except Exception:
                    today = None
                if today is not None:
                    for trade in open_trades.values():
                        if trade.is_short:
                            continue
                        if (trade.pair, today) in credited_divs:
                            continue
                        day_map = div_by_date.get(trade.pair)
                        if not day_map or today not in day_map:
                            continue
                        # Entitlement: held since before the ex-date.
                        try:
                            open_day = trade.open_date.date()
                        except AttributeError:
                            open_day = None
                        if open_day is not None and open_day >= today:
                            continue
                        payout = day_map[today] * (1 - dividend_tax) * trade.amount
                        if payout > 0:
                            wallets.add_amount(
                                self._config.stake_currency, payout
                            )
                            dividends_paid += payout
                            credited_divs.add((trade.pair, today))
                            logger.debug(
                                f"Dividend for {trade.pair} on {today}: "
                                f"+{payout:.2f}"
                            )

            # Process each pair at this timestamp
            for pair in pairlist:
                if pair not in data:
                    continue

                # Get the index for this pair at this date
                idx = pair_date_index[pair].get(current_date)
                if idx is None:
                    continue

                # Skip startup period
                if idx < startup_bars:
                    continue

                # Update data provider index. Expose only CLOSED candles
                # (exclude the in-progress current candle) so
                # historic_ohlcv() cannot see the close it is trading on —
                # in live trading that close is unknown until the candle ends.
                bt_dp.set_current_index(pair, idx)

                # Scalar reads from precomputed column arrays
                prices = price_arrays[pair]
                current_rate = prices["close"][idx]
                current_high = prices["high"][idx]
                current_low = prices["low"][idx]
                closes = prices["close"]
                prev_close = closes[idx - 1] if idx > 0 else current_rate
                signal_row = _ArrayRow(signal_arrays[pair], idx)
                pair_last_index[pair] = idx

                # Deferred fill plumbing (see fill_next_open above).
                prev_signal_row = (
                    _ArrayRow(signal_arrays[pair], idx - 1)
                    if fill_next_open and idx > 0 else None
                )
                open_rate = prices["open"][idx]

                # === Check exits for open trades ===
                if pair in open_trades:
                    trade = open_trades[pair]
                    self._check_exit(
                        trade=trade,
                        strategy=strategy,
                        signal_row=signal_row,
                        exit_signal_row=prev_signal_row,
                        exit_signal_rate=(open_rate if fill_next_open else None),
                        current_rate=current_rate,
                        current_high=current_high,
                        current_low=current_low,
                        prev_close=prev_close,
                        current_date=current_date,
                        position_manager=position_manager,
                        wallets=wallets,
                        open_trades=open_trades,
                        closed_bt_trades=closed_bt_trades,
                    )

                # === Check entries ===
                if (
                    pair not in open_trades
                    and len(open_trades) < max_open_trades
                    and (not fill_next_open or idx > 0)
                ):
                    self._check_entry(
                        pair=pair,
                        strategy=strategy,
                        signal_row=(prev_signal_row if fill_next_open
                                    else signal_row),
                        current_rate=(open_rate if fill_next_open
                                      else current_rate),
                        prev_close=prev_close,
                        current_date=current_date,
                        timeframe=timeframe,
                        wallets=wallets,
                        position_manager=position_manager,
                        open_trades=open_trades,
                        stake_amount=stake_amount,
                        max_open_trades=max_open_trades,
                    )

            # Sample mark-to-market equity once per timestamp (net of fees,
            # leverage-aware — previously gross-only and unleveraged, so the
            # curve drifted above final_balance and understated leverage).
            equity = wallets.get_free(self._config.stake_currency)
            for trade in open_trades.values():
                last_idx = pair_last_index.get(trade.pair)
                if last_idx is None:
                    continue
                rate = price_arrays[trade.pair]["close"][last_idx]
                leverage = trade.leverage or 1.0
                gross_pnl = (
                    (rate - trade.open_rate) * trade.amount
                    if not trade.is_short
                    else (trade.open_rate - rate) * trade.amount
                ) * leverage
                est_close_fee = self._calc_fee(
                    rate * trade.amount, is_sell=not trade.is_short
                )
                equity += trade.stake_amount + gross_pnl - trade.fee_open - est_close_fee
            equity_curve.append((current_date, equity))

        # Close any remaining open trades at the last price
        for pair, trade in list(open_trades.items()):
            df = data.get(pair)
            if df is not None and not df.empty:
                last_rate = df.iloc[-1]["close"]
                last_date = df.iloc[-1]["date"]
            else:
                last_rate = trade.open_rate
                last_date = current_date

            self._close_trade(
                trade=trade,
                rate=last_rate,
                exit_reason="force_exit",
                current_date=last_date,
                position_manager=position_manager,
                wallets=wallets,
                open_trades=open_trades,
                closed_bt_trades=closed_bt_trades,
                strategy=strategy,
            )

        logger.info(f"Backtest complete: {len(closed_bt_trades)} trades")
        self._last_equity_curve = equity_curve
        try:
            self._dividends_paid = float(
                getattr(self, "_dividends_paid", 0.0) + dividends_paid
            )
        except Exception:
            self._dividends_paid = dividends_paid
        return closed_bt_trades

    def _safe_callback(self, label: str, fn, default):
        """Invoke an optional strategy callback, logging failures.

        A crashing callback must not abort the backtest loop, but the
        failure must be visible (previously these were swallowed silently).
        Failures are counted on the engine for post-run visibility.
        """
        try:
            return fn()
        except Exception as e:
            self._callback_failures += 1
            logger.warning(f"Strategy callback {label} failed: {e}", exc_info=True)
            return default

    @staticmethod
    def _make_fill_order(
        pair: str,
        side: str,
        price: float,
        amount: float,
        current_date: datetime,
        order_type: str = "market",
    ):
        """Minimal fill notice (delegates to order.stock_rules)."""
        from bullseye.order.stock_rules import make_fill_order as _make

        return _make(pair, side, price, amount, current_date, order_type)

    def _fire_order_filled(self, strategy: IStrategy, pair: str,
                           trade: LocalTrade, order) -> None:
        """Invoke order_filled(); fills must never break the loop."""
        if strategy is None:
            return
        self._safe_callback(
            f"order_filled({pair})",
            lambda: strategy.order_filled(
                pair=pair, trade=trade, order=order,
                current_time=order.order_filled_date,
            ),
            None,
        )

    @staticmethod
    def _detect_market_type(pair: str) -> "MarketType":
        """Infer market type from pair format (delegates to stock_rules)."""
        from bullseye.order.stock_rules import detect_market_type as _detect

        mapping = {"stock": MarketType.STOCK, "future": MarketType.FUTURE}
        return mapping.get(_detect(pair), MarketType.CRYPTO)

    # ==================== A-share trading rules ====================

    def _enforce_lot_size(self) -> bool:
        """Whether 100-share lot rounding applies (default on, opt-out)."""
        try:
            return bool(self._config.get("backtest.enforce_lot_size", True))
        except Exception:
            return True

    def _enforce_price_limits(self) -> bool:
        """Whether limit-up/down fill blocking applies (default on)."""
        try:
            return bool(self._config.get("backtest.enforce_price_limits", True))
        except Exception:
            return True

    @staticmethod
    def _price_limit_ratio(pair: str) -> float:
        """Daily price-limit ratio (delegates to stock_rules)."""
        from bullseye.order.stock_rules import price_limit_ratio as _ratio

        return _ratio(pair)

    def _limit_ratio_for(self, pair: str) -> float:
        from bullseye.order.stock_rules import limit_ratio_for as _for

        return _for(self._config, pair)

    @staticmethod
    def _locked_at_limit_up(current_rate: float, prev_close: float, ratio: float) -> bool:
        """True when a buy fill at `current_rate` is unobtainable (limit-up)."""
        from bullseye.order.stock_rules import locked_at_limit_up as _locked

        return _locked(current_rate, prev_close, ratio)

    @staticmethod
    def _locked_at_limit_down(current_rate: float, prev_close: float, ratio: float) -> bool:
        """True when a sell fill at `current_rate` is unobtainable (limit-down)."""
        from bullseye.order.stock_rules import locked_at_limit_down as _locked

        return _locked(current_rate, prev_close, ratio)

    def _net_profit_ratio(self, trade: "LocalTrade", current_rate: float) -> float:
        """Net (fee-aware) profit ratio at a hypothetical exit price.

        `LocalTrade.calc_profit_ratio` is gross (excludes fees), so ROI /
        trailing / custom checks triggered on gross systematically overstate.
        Estimates the close fee at `current_rate` for a like-for-like net
        comparison. Short/long sides use their respective fee directions.
        """
        if not trade.open_rate or trade.open_rate <= 0 or current_rate <= 0:
            return 0.0
        leverage = trade.leverage or 1.0
        if trade.is_short:
            gross = (trade.open_rate - current_rate) / trade.open_rate * leverage
        else:
            gross = (current_rate - trade.open_rate) / trade.open_rate * leverage
        try:
            est_close_fee = self._calc_fee(
                current_rate * trade.amount, is_sell=not trade.is_short
            )
        except Exception:
            est_close_fee = 0.0
        fee_drag = ((trade.fee_open + est_close_fee) / trade.stake_amount) \
            if trade.stake_amount > 0 else 0.0
        return gross - fee_drag

    @staticmethod
    def _tz_safe_le(a: object, b: object) -> bool:
        """`a < b` comparison that tolerates naive/aware datetime mixes."""
        from datetime import datetime as _dt

        if isinstance(a, _dt) and isinstance(b, _dt):
            if (a.tzinfo is None) != (b.tzinfo is None):
                # Drop tzinfo (treat as wall-clock) rather than crashing.
                try:
                    a = a.replace(tzinfo=None)
                except Exception:
                    pass
                try:
                    b = b.replace(tzinfo=None)
                except Exception:
                    pass
        try:
            return a < b  # type: ignore[operator]
        except TypeError:
            return False

    def _resolve_stake(
        self,
        stake_amount: Optional[float],
        wallets: Wallets,
        open_trades: Dict[str, LocalTrade],
        max_open_trades: int,
    ) -> float:
        """Resolve the proposed stake, supporting `stake_amount='unlimited'`.

        Previously unlimited collapsed to 0 via `Config.stake_amount`,
        producing silent zero-trade backtests. Now sizes as
        available / remaining_slots (at least the current slot).
        """
        if stake_amount is not None:
            return float(stake_amount)
        available = wallets.get_available_stake_amount()
        remaining = max(1, max_open_trades - len(open_trades))
        return available / remaining if remaining > 0 else available

    def _resolve_leverage(
        self, strategy: IStrategy, pair: str, current_rate: float,
        current_date: datetime, entry_tag: Optional[str], side: str,
    ) -> float:
        """Resolve leverage via `strategy.leverage()` (default 1.0)."""
        try:
            lev = self._safe_callback(
                f"leverage[{side}]({pair})",
                lambda: strategy.leverage(
                    pair=pair,
                    current_time=current_date,
                    current_rate=current_rate,
                    proposed_leverage=1.0,
                    max_leverage=10,
                    entry_tag=entry_tag,
                    side=side,
                ),
                1.0,
            )
            lev_f = float(lev or 1.0)
            if lev_f <= 0 or lev_f != lev_f:  # NaN guard
                return 1.0
            return lev_f
        except Exception:
            return 1.0

    def _resolve_entry_rate(
        self, strategy: IStrategy, pair: str, current_rate: float,
        current_date: datetime, entry_tag: Optional[str], side: str,
    ) -> float:
        """Apply `custom_entry_price()` then adverse slippage."""
        proposed = current_rate
        try:
            custom = self._safe_callback(
                f"custom_entry_price[{side}]({pair})",
                lambda: strategy.custom_entry_price(
                    pair=pair,
                    current_time=current_date,
                    proposed_rate=current_rate,
                    entry_tag=entry_tag,
                    side=side,
                ),
                current_rate,
            )
            if custom is not None and float(custom) > 0:
                proposed = float(custom)
        except Exception:
            proposed = current_rate
        return self._slipped_price(proposed, buy=(side == "long"))

    def _open_backtest_trade(
        self, pair: str, strategy: IStrategy, timeframe: str,
        fill_rate: float, actual_stake: float, enter_tag: Optional[str],
        is_short: bool, current_date: datetime, current_rate: float,
        wallets: Wallets, open_trades: Dict[str, LocalTrade],
        leverage: float,
    ) -> Optional[LocalTrade]:
        amount = actual_stake / fill_rate if fill_rate > 0 else 0
        if amount <= 0:
            return None
        market_type = self._detect_market_type(pair)
        # A-share lot rule: buys in multiples of 100 shares. Round down;
        # below one lot the order is rejected by the broker.
        if market_type == MarketType.STOCK and not is_short and self._enforce_lot_size():
            from bullseye.order.stock_rules import LOT_SIZE, floor_to_lots

            floored = floor_to_lots(amount)
            if floored < LOT_SIZE:
                logger.debug(
                    f"Entry skipped for {pair}: {amount:.2f} shares < 1 lot "
                    f"(stake={actual_stake})"
                )
                return None
            amount = floored
            actual_stake = amount * fill_rate
        fee = self._calc_fee(actual_stake, is_sell=is_short)
        trade = LocalTrade(
            pair=pair,
            exchange=self._config.exchange_name,
            strategy=strategy.__class__.__name__,
            timeframe=timeframe,
            market_type=market_type,
            open_date=current_date,
            open_rate=fill_rate,
            amount=amount,
            stake_amount=actual_stake,
            fee_open=fee,
            enter_tag=enter_tag,
            max_rate=fill_rate,
            min_rate=fill_rate,
            is_short=is_short,
            leverage=leverage,
        )
        stoploss = getattr(strategy, 'stoploss', 0)
        if stoploss != 0:
            trade.stop_loss_pct = stoploss
            trade.stop_loss = fill_rate * (1 - stoploss) if is_short \
                else fill_rate * (1 + stoploss)
            trade.initial_stop_loss_pct = stoploss
            trade.initial_stop_loss = trade.stop_loss
        open_trades[pair] = trade
        # Fees (open + close) are settled once at trade close via calc_profit;
        # deducting fee_open here as well would double-charge it.
        wallets.deduct_amount(self._config.stake_currency, actual_stake)
        logger.debug(f"Entry: {pair} @ {fill_rate}, stake={actual_stake}")
        self._fire_order_filled(
            strategy, pair, trade,
            self._make_fill_order(
                pair, "buy" if not is_short else "sell",
                fill_rate, amount, current_date,
            ),
        )
        return trade

    def _check_entry(
        self,
        pair: str,
        strategy: IStrategy,
        signal_row,
        current_rate: float,
        prev_close: float,
        current_date: datetime,
        timeframe: str,
        wallets: Wallets,
        position_manager: PositionManager,
        open_trades: Dict[str, LocalTrade],
        stake_amount: Optional[float],
        max_open_trades: int = 3,
    ) -> None:
        """Check for entry signals and execute trades.

        Signals come from the precomputed per-pair dataframe (see
        _run_backtest_loop); no indicator recomputation happens here.
        """
        try:
            # A-share limit-up: no sellers at the close fill — skip buys.
            if (
                self._detect_market_type(pair) == MarketType.STOCK
                and self._enforce_price_limits()
                and self._locked_at_limit_up(
                    current_rate, prev_close, self._limit_ratio_for(pair)
                )
            ):
                logger.debug(f"Entry skipped for {pair}: locked at limit-up")
                return

            # Check for long entry
            enter_long = signal_row.get("enter_long", 0)
            enter_tag = signal_row.get("enter_tag", None)

            if enter_long == 1:
                # Confirm entry
                confirmed = self._safe_callback(
                    f"confirm_trade_entry[long]({pair})",
                    lambda: strategy.confirm_trade_entry(
                        pair=pair,
                        order_type="market",
                        amount=0,
                        rate=current_rate,
                        time_in_force="GTC",
                        current_time=current_date,
                        entry_tag=enter_tag,
                        side="long",
                    ),
                    True,
                )
                if not confirmed:
                    return

                # Calculate stake (supports unlimited + custom override)
                proposed = self._resolve_stake(
                    stake_amount, wallets, open_trades, max_open_trades
                )
                leverage = self._resolve_leverage(
                    strategy, pair, current_rate, current_date, enter_tag, "long"
                )
                custom_stake = self._safe_callback(
                    f"custom_stake_amount[long]({pair})",
                    lambda: strategy.custom_stake_amount(
                        pair=pair,
                        current_time=current_date,
                        current_rate=current_rate,
                        proposed_stake=proposed,
                        min_stake=0,
                        max_stake=wallets.get_available_stake_amount(),
                        leverage=leverage,
                        entry_tag=enter_tag,
                        side="long",
                    ),
                    None,
                )
                actual_stake = custom_stake if (
                    custom_stake is not None and custom_stake > 0
                ) else proposed

                available = wallets.get_available_stake_amount()
                actual_stake = min(actual_stake, available)

                if actual_stake <= 0:
                    return

                fill_rate = self._resolve_entry_rate(
                    strategy, pair, current_rate, current_date, enter_tag, "long"
                )
                self._open_backtest_trade(
                    pair, strategy, timeframe, fill_rate, actual_stake,
                    enter_tag, False, current_date, current_rate,
                    wallets, open_trades, leverage,
                )
                return

            # Check for short entry
            if getattr(strategy, 'can_short', False):
                enter_short = signal_row.get("enter_short", 0)
                if enter_short == 1:
                    confirmed = self._safe_callback(
                        f"confirm_trade_entry[short]({pair})",
                        lambda: strategy.confirm_trade_entry(
                            pair=pair,
                            order_type="market",
                            amount=0,
                            rate=current_rate,
                            time_in_force="GTC",
                            current_time=current_date,
                            entry_tag=enter_tag,
                            side="short",
                        ),
                        True,
                    )
                    if not confirmed:
                        return

                    proposed = self._resolve_stake(
                        stake_amount, wallets, open_trades, max_open_trades
                    )
                    leverage = self._resolve_leverage(
                        strategy, pair, current_rate, current_date, enter_tag, "short"
                    )
                    custom_stake = self._safe_callback(
                        f"custom_stake_amount[short]({pair})",
                        lambda: strategy.custom_stake_amount(
                            pair=pair,
                            current_time=current_date,
                            current_rate=current_rate,
                            proposed_stake=proposed,
                            min_stake=0,
                            max_stake=wallets.get_available_stake_amount(),
                            leverage=leverage,
                            entry_tag=enter_tag,
                            side="short",
                        ),
                        None,
                    )
                    actual_stake = custom_stake if (
                        custom_stake is not None and custom_stake > 0
                    ) else proposed
                    available = wallets.get_available_stake_amount()
                    actual_stake = min(actual_stake, available)

                    if actual_stake <= 0:
                        return

                    fill_rate = self._resolve_entry_rate(
                        strategy, pair, current_rate, current_date, enter_tag, "short"
                    )
                    self._open_backtest_trade(
                        pair, strategy, timeframe, fill_rate, actual_stake,
                        enter_tag, True, current_date, current_rate,
                        wallets, open_trades, leverage,
                    )

        except Exception as e:
            logger.warning(f"Error checking entry for {pair}: {e}", exc_info=True)

    def _check_adjust(
        self,
        trade: LocalTrade,
        strategy: IStrategy,
        current_rate: float,
        prev_close: float,
        current_date: datetime,
        wallets: Wallets,
    ) -> None:
        """Position adjustment (DCA / grid averaging-down).

        Calls `strategy.adjust_trade_position()`; a positive return value is
        treated as additional stake (long buys only — A-share grids never
        short). The trade's open_rate is repriced to the volume-weighted
        average cost so every downstream profit check uses the true basis.
        """
        if trade.is_short:
            return
        # Limit-up lock rejects buys (mirrors entry logic).
        if (
            trade.market_type == MarketType.STOCK
            and self._enforce_price_limits()
            and self._locked_at_limit_up(
                current_rate, prev_close, self._limit_ratio_for(trade.pair)
            )
        ):
            return
        available = wallets.get_available_stake_amount()
        if available <= 0:
            return
        fill = self._slipped_price(current_rate, buy=True)
        net = self._net_profit_ratio(trade, current_rate)
        add = self._safe_callback(
            f"adjust_trade_position({trade.pair})",
            lambda: strategy.adjust_trade_position(
                trade=trade,
                current_time=current_date,
                current_rate=current_rate,
                current_profit=net,
                min_stake=0.0,
                max_stake=available,
                current_entry_rate=fill,
                current_exit_rate=self._slipped_price(current_rate, buy=False),
                current_entry_profit=net,
                current_exit_profit=net,
                min_limit=0.0,
                max_limit=available,
            ),
            None,
        )
        if add is None:
            return
        # Freqtrade strategies may return (stake, tag) tuples.
        if isinstance(add, (tuple, list)) and len(add) == 2:
            add = add[0]
            if add is None:
                return
        try:
            add = float(add)
        except (TypeError, ValueError):
            logger.warning(f"Ignoring non-numeric adjust stake {add!r}")
            return
        if add <= 0:
            return
        add = min(add, available)
        amount = add / fill if fill > 0 else 0
        if amount <= 0:
            return
        if trade.market_type == MarketType.STOCK and self._enforce_lot_size():
            from bullseye.order.stock_rules import LOT_SIZE, floor_to_lots

            floored = floor_to_lots(amount)
            if floored < LOT_SIZE:
                logger.debug(f"Adjust skipped for {trade.pair}: below 1 lot")
                return
            amount = floored
            add = amount * fill
        fee = self._calc_fee(add, is_sell=False)
        # Reprice to volume-weighted average cost.
        total_cost = trade.open_rate * trade.amount + fill * amount
        trade.amount += amount
        trade.open_rate = total_cost / trade.amount if trade.amount > 0 else fill
        trade.stake_amount += add
        trade.fee_open += fee
        trade.nr_of_successful_entries += 1
        # Each add lot carries its own T+1 clock: the newest shares must
        # settle before the position (including them) can be sold.
        try:
            new_settle = get_settlement_date(
                current_date, trade.pair, trade.exchange
            )
            if trade.settlement_date is None or new_settle > trade.settlement_date:
                trade.settlement_date = new_settle
        except Exception:
            pass
        trade.update_rate(fill)
        wallets.deduct_amount(self._config.stake_currency, add)
        logger.debug(
            f"Adjust: {trade.pair} +{amount:.0f} @ {fill:.2f}, "
            f"avg={trade.open_rate:.2f}, stake={trade.stake_amount:.2f}"
        )

    def _check_exit(
        self,
        trade: LocalTrade,
        strategy: IStrategy,
        signal_row,
        current_rate: float,
        current_high: float,
        current_low: float,
        prev_close: float,
        current_date: datetime,
        position_manager: PositionManager,
        wallets: Wallets,
        open_trades: Dict[str, LocalTrade],
        closed_bt_trades: List[BacktestTrade],
        exit_signal_row: Optional[Any] = None,
        exit_signal_rate: Optional[float] = None,
    ) -> None:
        """Check exit conditions for an open trade.

        Signal columns come from the precomputed per-pair dataframe; only
        user callbacks (custom_exit / confirm_trade_exit) run per candle.
        """
        # Track intra-candle extremes (previously close-only, so trailing
        # stops missed high/low spikes and triggered late/never).
        trade.update_rate(current_high)
        trade.update_rate(current_low)
        trade.update_rate(current_rate)

        # Gross ratio (strategy semantics) + net ratio (fee-aware, for
        # trigger decisions). ROI/trailing/custom previously fired on gross,
        # systematically overstating after-fee returns.
        profit_ratio = trade.calc_profit_ratio(current_rate)
        net_ratio = self._net_profit_ratio(trade, current_rate)

        # 0. Enforce T+1/T+N settlement: the position cannot be sold before
        # its settlement date (compared against simulated time, NOT wall clock).
        # Uses tz-safe comparison (naive/aware mixes previously crashed).
        rule = trade.settlement_rule
        settlement_date = trade.settlement_date
        if (
            rule is not None
            and rule.settlement_type != SettlementType.T0
            and settlement_pending(current_date, settlement_date)
        ):
            logger.debug(
                f"Exit blocked for {trade.pair}: T+1 settlement until {settlement_date}"
            )
            return

        # 0a1. Position adjustment (DCA / grid adds). Buys only, so the
        # T+1 exit block above does not apply; a limit-up lock still
        # rejects the add (no sellers). Gated by the strategy flag so
        # existing strategies are unaffected.
        if getattr(strategy, 'position_adjustment_enable', False):
            self._check_adjust(
                trade=trade,
                strategy=strategy,
                current_rate=current_rate,
                prev_close=prev_close,
                current_date=current_date,
                wallets=wallets,
            )
            # Recompute net ratio after a possible add (average cost moved).
            net_ratio = self._net_profit_ratio(trade, current_rate)
            # An add booked above pushed settlement out (the new lot has
            # its own T+1 clock); no exit may fire for it today.
            if (
                rule is not None
                and rule.settlement_type != SettlementType.T0
                and settlement_pending(current_date, trade.settlement_date)
            ):
                return
            profit_ratio = trade.calc_profit_ratio(current_rate)

        # 0a. A-share limit-down: no buyers at the close fill — hold the
        # position (all exit paths blocked; end-of-data force_exit still
        # applies for accounting). Only for long stock positions.
        if (
            not trade.is_short
            and trade.market_type == MarketType.STOCK
            and self._enforce_price_limits()
            and self._locked_at_limit_down(
                current_rate, prev_close, self._limit_ratio_for(trade.pair)
            )
        ):
            logger.debug(f"Exit blocked for {trade.pair}: locked at limit-down")
            return

        # 0b1. Dynamic stoploss (use_custom_stoploss): reprice the stop
        # level every candle from the strategy's ratio. Previously never
        # invoked, so custom trailing/breakeven logic silently did nothing.
        if getattr(strategy, 'use_custom_stoploss', False):
            new_sl = self._safe_callback(
                f"custom_stoploss({trade.pair})",
                lambda: strategy.custom_stoploss(
                    pair=trade.pair,
                    trade=trade,
                    current_time=current_date,
                    current_rate=current_rate,
                    current_profit=net_ratio,
                ),
                None,
            )
            if new_sl is not None:
                try:
                    ratio = float(new_sl)
                except (TypeError, ValueError):
                    ratio = None
                if ratio is None or not (ratio == ratio) or ratio > 0 or ratio < -1:
                    logger.debug(
                        f"Ignoring invalid custom_stoploss {new_sl!r} "
                        f"for {trade.pair} (need -1 <= ratio <= 0)"
                    )
                else:
                    trade.stop_loss_pct = ratio
                    trade.stop_loss = trade.open_rate * (
                        (1 - ratio) if trade.is_short else (1 + ratio)
                    )
                    trade.is_stop_loss_trailing = True

        # 0b. Liquidation: leveraged loss wiping margin forces exit.
        # Previously ignored (no margin model), letting insolvent positions
        # ride to profit. Uses gross ratio vs -1/leverage.
        leverage = trade.leverage or 1.0
        # calc_profit_ratio already scales by leverage, so margin is wiped
        # at -100% of that leveraged ratio (a 2x position liquidates on a
        # ~-50% price move, not at -25%: the /leverage double-counted).
        if leverage > 1.0 and profit_ratio <= -1.0:
            self._close_trade(
                trade=trade,
                rate=current_rate,
                exit_reason="liquidation",
                current_date=current_date,
                position_manager=position_manager,
                wallets=wallets,
                open_trades=open_trades,
                closed_bt_trades=closed_bt_trades,
                strategy=strategy,
            )
            return

        # 1. Check stoploss (use low for long, high for short)
        stoploss_hit = False
        if trade.is_short:
            if current_high >= trade.stop_loss and trade.stop_loss > 0:
                stoploss_hit = True
                exit_rate = trade.stop_loss
        else:
            if current_low <= trade.stop_loss and trade.stop_loss > 0:
                stoploss_hit = True
                exit_rate = trade.stop_loss

        if stoploss_hit:
            self._close_trade(
                trade=trade,
                rate=exit_rate,
                exit_reason="stoploss",
                current_date=current_date,
                position_manager=position_manager,
                wallets=wallets,
                open_trades=open_trades,
                closed_bt_trades=closed_bt_trades,
                strategy=strategy,
            )
            return

        # 2. Check trailing stop
        trailing_stop = getattr(strategy, 'trailing_stop', False)
        if trailing_stop:
            trailing_stop_positive = getattr(strategy, 'trailing_stop_positive', 0.01)
            trailing_stop_positive_offset = getattr(strategy, 'trailing_stop_positive_offset', 0.0)
            trailing_only_offset = getattr(strategy, 'trailing_only_offset_is_reached', False)

            if not trailing_only_offset or net_ratio >= trailing_stop_positive_offset:
                if trade.is_short:
                    new_stop = trade.min_rate * (1 + trailing_stop_positive)
                    if new_stop < trade.stop_loss or trade.stop_loss == 0:
                        trade.stop_loss = new_stop
                        trade.is_stop_loss_trailing = True
                else:
                    new_stop = trade.max_rate * (1 - trailing_stop_positive)
                    if new_stop > trade.stop_loss:
                        trade.stop_loss = new_stop
                        trade.is_stop_loss_trailing = True

            # Check if trailing stop triggered
            if trade.is_stop_loss_trailing:
                if trade.is_short:
                    if current_high >= trade.stop_loss:
                        self._close_trade(
                            trade=trade,
                            rate=trade.stop_loss,
                            exit_reason="trailing_stop",
                            current_date=current_date,
                            position_manager=position_manager,
                            wallets=wallets,
                            open_trades=open_trades,
                            closed_bt_trades=closed_bt_trades,
                            strategy=strategy,
                        )
                        return
                else:
                    if current_low <= trade.stop_loss:
                        self._close_trade(
                            trade=trade,
                            rate=trade.stop_loss,
                            exit_reason="trailing_stop",
                            current_date=current_date,
                            position_manager=position_manager,
                            wallets=wallets,
                            open_trades=open_trades,
                            closed_bt_trades=closed_bt_trades,
                            strategy=strategy,
                        )
                        return

        # 3. Check ROI (fee-aware; honors ignore_roi_if_entry_signal).
        # custom_roi() overrides the static table when it returns a value.
        minimal_roi = getattr(strategy, 'minimal_roi', {})
        custom_roi_target = self._safe_callback(
            f"custom_roi({trade.pair})",
            lambda: strategy.custom_roi(
                pair=trade.pair,
                current_time=current_date,
                current_rate=current_rate,
                current_profit=net_ratio,
            ),
            None,
        )
        roi_table = dict(minimal_roi) if minimal_roi else {}
        if custom_roi_target is not None:
            try:
                roi_table = {"0": float(custom_roi_target)}
            except (TypeError, ValueError):
                pass
        if roi_table:
            # Freqtrade: skip ROI when a fresh entry signal exists and the
            # strategy opts out of ROI exits on entry candles.
            ignore_roi = getattr(strategy, 'ignore_roi_if_entry_signal', False)
            has_entry_signal = False
            if ignore_roi:
                try:
                    if trade.is_short:
                        has_entry_signal = signal_row.get("enter_short", 0) == 1
                    else:
                        has_entry_signal = signal_row.get("enter_long", 0) == 1
                except Exception:
                    has_entry_signal = False
            if not (ignore_roi and has_entry_signal):
                try:
                    trade_duration = (
                        current_date - trade.open_date
                    ).total_seconds() / 60
                except TypeError:
                    # naive/aware mix — fall back to wall-clock diff
                    trade_duration = (
                        current_date.replace(tzinfo=None)
                        - trade.open_date.replace(tzinfo=None)
                    ).total_seconds() / 60

                for minutes_str, roi_value in sorted(
                    roi_table.items(),
                    key=lambda x: int(x[0]) if str(x[0]).isdigit() else float("inf"),
                    reverse=True,
                ):
                    try:
                        minutes = int(minutes_str)
                    except ValueError:
                        continue
                    if trade_duration >= minutes and net_ratio >= roi_value:
                        self._close_trade(
                            trade=trade,
                            rate=current_rate,
                            exit_reason=f"roi_{minutes}m",
                            current_date=current_date,
                            position_manager=position_manager,
                            wallets=wallets,
                            open_trades=open_trades,
                            closed_bt_trades=closed_bt_trades,
                            strategy=strategy,
                        )
                        return

        # 4. Check custom exit (fee-aware profit; honors exit_profit_only)
        exit_reason = self._safe_callback(
            f"custom_exit({trade.pair})",
            lambda: strategy.custom_exit(
                pair=trade.pair,
                trade=trade,
                current_time=current_date,
                current_rate=current_rate,
                current_profit=net_ratio,
                exit_reason=None,
            ),
            None,
        )
        if exit_reason:
            if getattr(strategy, 'exit_profit_only', False) and net_ratio <= 0:
                pass  # loss-making custom exit suppressed by strategy flag
            else:
                # Allow custom_exit_price() to adjust the fill before slippage
                exit_rate = current_rate
                try:
                    custom_px = self._safe_callback(
                        f"custom_exit_price({trade.pair})",
                        lambda: strategy.custom_exit_price(
                            pair=trade.pair,
                            trade=trade,
                            current_time=current_date,
                            proposed_rate=current_rate,
                            current_profit=net_ratio,
                            exit_tag=exit_reason,
                        ),
                        current_rate,
                    )
                    if custom_px is not None and float(custom_px) > 0:
                        exit_rate = float(custom_px)
                except Exception:
                    exit_rate = current_rate
                self._close_trade(
                    trade=trade,
                    rate=exit_rate,
                    exit_reason=exit_reason,
                    current_date=current_date,
                    position_manager=position_manager,
                    wallets=wallets,
                    open_trades=open_trades,
                    closed_bt_trades=closed_bt_trades,
                    strategy=strategy,
                )
                return

        # 5. Check exit signal from strategy (precomputed columns).
        # Honors use_exit_signal=False and exit_profit_only=True.
        # With backtest.fill_next_open, the signal comes from the previous
        # closed candle and fills at this candle's open.
        if not getattr(strategy, 'use_exit_signal', True):
            return
        sig_row = exit_signal_row if exit_signal_row is not None else signal_row
        fill_rate = (exit_signal_rate if exit_signal_rate is not None
                     else current_rate)
        exit_long = sig_row.get("exit_long", 0)
        exit_short = sig_row.get("exit_short", 0)
        exit_tag = sig_row.get("exit_tag", None)

        should_exit = False
        if trade.is_short and exit_short == 1:
            should_exit = True
        elif not trade.is_short and exit_long == 1:
            should_exit = True
        if should_exit and getattr(strategy, 'exit_profit_only', False):
            if net_ratio <= 0:
                should_exit = False

        if should_exit:
            # Confirm exit
            confirmed = self._safe_callback(
                f"confirm_trade_exit({trade.pair})",
                lambda: strategy.confirm_trade_exit(
                    pair=trade.pair,
                    trade=trade,
                    order_type="market",
                    amount=trade.amount,
                    rate=fill_rate,
                    time_in_force="GTC",
                    exit_reason="exit_signal",
                    current_time=current_date,
                ),
                True,
            )
            if not confirmed:
                return

            self._close_trade(
                trade=trade,
                rate=fill_rate,
                exit_reason=exit_tag or "exit_signal",
                current_date=current_date,
                position_manager=position_manager,
                wallets=wallets,
                open_trades=open_trades,
                closed_bt_trades=closed_bt_trades,
                strategy=strategy,
            )

    def _close_trade(
        self,
        trade: LocalTrade,
        rate: float,
        exit_reason: str,
        current_date: datetime,
        position_manager: PositionManager,
        wallets: Wallets,
        open_trades: Dict[str, LocalTrade],
        closed_bt_trades: List[BacktestTrade],
        strategy: Optional[IStrategy] = None,
    ) -> None:
        """Close a trade and record the result."""
        # Slippage: exits are market orders - longs sell lower, shorts buy back higher
        rate = self._slipped_price(rate, buy=trade.is_short)
        close_value = rate * trade.amount
        fee_close = self._calc_fee(close_value, is_sell=not trade.is_short)

        trade.close_date = current_date
        trade.close_rate = rate
        trade.fee_close = fee_close
        trade.exit_reason = exit_reason

        profit_abs = trade.calc_profit(rate)
        # Net pct consistent with net abs (previously gross ratio, so pct
        # overstated vs abs whenever fees applied).
        if trade.stake_amount > 0:
            profit_pct = profit_abs / trade.stake_amount * 100
        else:
            profit_pct = trade.calc_profit_ratio(rate) * 100
        try:
            duration_hours = (
                current_date - trade.open_date
            ).total_seconds() / 3600
        except TypeError:
            duration_hours = (
                current_date.replace(tzinfo=None)
                - trade.open_date.replace(tzinfo=None)
            ).total_seconds() / 3600

        # Update wallet (floor at 0: leveraged wipeout cannot add negative;
        # Wallets.add_amount rejects negative amounts).
        total_return = trade.stake_amount + profit_abs
        wallets.add_amount(
            self._config.stake_currency, max(0.0, total_return)
        )

        # Record trade
        bt_trade = BacktestTrade(
            pair=trade.pair,
            entry_date=trade.open_date,
            exit_date=current_date,
            open_rate=trade.open_rate,
            close_rate=rate,
            amount=trade.amount,
            stake_amount=trade.stake_amount,
            fee_open=trade.fee_open,
            fee_close=fee_close,
            profit=profit_pct / 100,
            profit_pct=profit_pct,
            profit_abs=profit_abs,
            exit_reason=exit_reason,
            enter_tag=trade.enter_tag,
            is_short=trade.is_short,
            leverage=trade.leverage,
            trade_duration=duration_hours,
            entries=trade.nr_of_successful_entries,
        )
        closed_bt_trades.append(bt_trade)

        # Remove from open trades
        if trade.pair in open_trades:
            del open_trades[trade.pair]

        logger.debug(
            f"Exit: {trade.pair} @ {rate}, profit={profit_abs:.4f} "
            f"({profit_pct:.2f}%), reason={exit_reason}"
        )
        self._fire_order_filled(
            strategy, trade.pair, trade,
            self._make_fill_order(
                trade.pair, "sell" if not trade.is_short else "buy",
                rate, trade.amount, current_date,
            ),
        )

    def _slipped_price(self, rate: float, *, buy: bool) -> float:
        """
        Apply adverse slippage to a fill price.

        Buys fill higher, sells fill lower - the direction that costs money.
        With slippage 0 (default) prices are unchanged.
        """
        if self._slippage_rate <= 0 or rate <= 0:
            return rate
        return rate * (1 + self._slippage_rate) if buy else rate * (1 - self._slippage_rate)

    @staticmethod
    def _timeframe_to_minutes(timeframe: str) -> int:
        """Convert timeframe string to minutes."""
        timeframe = timeframe.lower()
        if timeframe.endswith("m"):
            return int(timeframe[:-1])
        elif timeframe.endswith("h"):
            return int(timeframe[:-1]) * 60
        elif timeframe.endswith("d"):
            return int(timeframe[:-1]) * 60 * 24
        elif timeframe.endswith("w"):
            return int(timeframe[:-1]) * 60 * 24 * 7
        return 60
