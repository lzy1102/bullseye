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
from bullseye.order.settlement import SettlementType
from bullseye.strategy.interface import IStrategy
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
        self._data_handler = self._create_data_handler()

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

    def run(
        self,
        strategy_class: Optional[Type[IStrategy]] = None,
        strategy_name: Optional[str] = None,
        pairlist: Optional[List[str]] = None,
        timeframe: Optional[str] = None,
        timerange: Optional[str] = None,
        stake_amount: Optional[float] = None,
        max_open_trades: Optional[int] = None,
        initial_balance: Optional[float] = None,
        fee: Optional[float] = None,
        export: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> BacktestResult:
        """
        Run backtesting.

        Args:
            strategy_class: Strategy class to use
            strategy_name: Strategy name to load (if class not provided)
            pairlist: List of trading pairs
            timeframe: Candle timeframe
            timerange: Time range string (e.g., "20240101-20241231")
            stake_amount: Stake amount per trade
            max_open_trades: Maximum concurrent open trades
            initial_balance: Starting balance
            fee: Fee rate (e.g., 0.001 for 0.1%)
            export: Export filename for results
            data: In-memory OHLCV data {pair: DataFrame}; skips disk loading

        Returns:
            BacktestResult with trades and metrics
        """
        # Load strategy
        if strategy_class:
            strategy = strategy_class()
        elif strategy_name:
            strategy = self._load_strategy(strategy_name)
        else:
            strategy_name = self._config.strategy
            if strategy_name:
                strategy = self._load_strategy(strategy_name)
            else:
                raise BacktestError("No strategy specified. Provide strategy_class or strategy_name.")

        # Apply config overrides
        pairlist = pairlist or self._get_pairlist()
        timeframe = timeframe or getattr(strategy, 'timeframe', None) or self._config.timeframe
        stake_amount = stake_amount or self._config.stake_amount
        max_open_trades = max_open_trades or self._config.max_open_trades
        initial_balance = initial_balance or self._config.dry_run_wallet
        if fee is not None:
            self._fee_rate = fee

        logger.info(f"Starting backtest: strategy={strategy.__class__.__name__}, "
                     f"pairs={pairlist}, timeframe={timeframe}")

        # Load data (in-memory injection takes precedence over disk)
        if data is None:
            data = self._load_data(pairlist, timeframe, timerange)
        if not data:
            logger.error("No data available for backtesting")
            return BacktestResult(strategy_name=strategy.__class__.__name__)

        # Validate data
        for pair, df in data.items():
            if df.empty:
                logger.warning(f"No data for {pair}, skipping")
                continue
            required_cols = {"date", "open", "high", "low", "close", "volume"}
            missing = required_cols - set(df.columns)
            if missing:
                raise ValueError(f"Data for {pair} missing columns: {missing}")

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
        )

        # Build result
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
            },
            equity_curve=getattr(self, "_last_equity_curve", []),
        )
        result.calculate_metrics(initial_balance=initial_balance)

        # Export if requested
        if export:
            result.save(export)

        return result

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
                    df["date"] = pd.date_range(end=datetime.now(), periods=len(df), freq=timeframe)

            df["date"] = pd.to_datetime(df["date"])

            if start_date:
                df = df[df["date"] >= start_date]
            if end_date:
                df = df[df["date"] <= end_date]

            df = df.sort_values("date").reset_index(drop=True)

            if not df.empty:
                data[pair] = df

        return data

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
    ) -> List[BacktestTrade]:
        """
        Main backtesting loop.

        Iterates through all candles chronologically, executing trades based
        on precomputed strategy signals (computed once per pair, freqtrade-style).
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
        precomputed_signals: Dict[str, Any] = {}
        for pair, df in data.items():
            metadata = {"pair": pair}
            signal_df = strategy.populate_indicators(df.copy(), metadata)
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

        # Balance tracking for equity curve
        startup_candle_count = getattr(strategy, 'startup_candle_count', 30)
        startup_bars = startup_candle_count

        logger.info(f"Backtest: {len(sorted_dates)} candles, {len(pairlist)} pairs")

        for date_idx, current_date in enumerate(sorted_dates):
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

                # Update data provider index
                bt_dp.set_current_index(pair, idx + 1)

                # Scalar reads from precomputed column arrays
                prices = price_arrays[pair]
                current_rate = prices["close"][idx]
                current_high = prices["high"][idx]
                current_low = prices["low"][idx]
                signal_row = _ArrayRow(signal_arrays[pair], idx)
                pair_last_index[pair] = idx

                # === Check exits for open trades ===
                if pair in open_trades:
                    trade = open_trades[pair]
                    self._check_exit(
                        trade=trade,
                        strategy=strategy,
                        signal_row=signal_row,
                        current_rate=current_rate,
                        current_high=current_high,
                        current_low=current_low,
                        current_date=current_date,
                        position_manager=position_manager,
                        wallets=wallets,
                        open_trades=open_trades,
                        closed_bt_trades=closed_bt_trades,
                    )

                # === Check entries ===
                if pair not in open_trades and len(open_trades) < max_open_trades:
                    self._check_entry(
                        pair=pair,
                        strategy=strategy,
                        signal_row=signal_row,
                        current_rate=current_rate,
                        current_date=current_date,
                        timeframe=timeframe,
                        wallets=wallets,
                        position_manager=position_manager,
                        open_trades=open_trades,
                        stake_amount=stake_amount,
                    )

            # Sample mark-to-market equity once per timestamp
            equity = wallets.get_free(self._config.stake_currency)
            for trade in open_trades.values():
                last_idx = pair_last_index.get(trade.pair)
                if last_idx is None:
                    continue
                rate = price_arrays[trade.pair]["close"][last_idx]
                gross_pnl = (
                    (rate - trade.open_rate) * trade.amount
                    if not trade.is_short
                    else (trade.open_rate - rate) * trade.amount
                )
                equity += trade.stake_amount + gross_pnl
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
            )

        logger.info(f"Backtest complete: {len(closed_bt_trades)} trades")
        self._last_equity_curve = equity_curve
        return closed_bt_trades

    @staticmethod
    def _safe_callback(label: str, fn, default):
        """Invoke an optional strategy callback, logging failures.

        A crashing callback must not abort the backtest loop, but the
        failure must be visible (previously these were swallowed silently).
        """
        try:
            return fn()
        except Exception as e:
            logger.warning(f"Strategy callback {label} failed: {e}", exc_info=True)
            return default

    def _check_entry(
        self,
        pair: str,
        strategy: IStrategy,
        signal_row,
        current_rate: float,
        current_date: datetime,
        timeframe: str,
        wallets: Wallets,
        position_manager: PositionManager,
        open_trades: Dict[str, LocalTrade],
        stake_amount: float,
    ) -> None:
        """Check for entry signals and execute trades.

        Signals come from the precomputed per-pair dataframe (see
        _run_backtest_loop); no indicator recomputation happens here.
        """
        try:
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

                # Calculate stake
                actual_stake = stake_amount
                custom_stake = self._safe_callback(
                    f"custom_stake_amount[long]({pair})",
                    lambda: strategy.custom_stake_amount(
                        pair=pair,
                        current_time=current_date,
                        current_rate=current_rate,
                        proposed_stake=stake_amount,
                        min_stake=0,
                        max_stake=wallets.get_available_stake_amount(),
                        leverage=1.0,
                        entry_tag=enter_tag,
                        side="long",
                    ),
                    None,
                )
                if custom_stake is not None and custom_stake > 0:
                    actual_stake = custom_stake

                available = wallets.get_available_stake_amount()
                actual_stake = min(actual_stake, available)

                if actual_stake <= 0:
                    return

                amount = actual_stake / current_rate if current_rate > 0 else 0
                if amount <= 0:
                    return

                fee = actual_stake * self._fee_rate

                trade = LocalTrade(
                    pair=pair,
                    exchange=self._config.exchange_name,
                    strategy=strategy.__class__.__name__,
                    timeframe=timeframe,
                    market_type=MarketType.CRYPTO,
                    open_date=current_date,
                    open_rate=current_rate,
                    amount=amount,
                    stake_amount=actual_stake,
                    fee_open=fee,
                    enter_tag=enter_tag,
                    max_rate=current_rate,
                    min_rate=current_rate,
                    is_short=False,
                )

                # Set stoploss
                stoploss = getattr(strategy, 'stoploss', 0)
                if stoploss != 0:
                    trade.stop_loss_pct = stoploss
                    trade.stop_loss = current_rate * (1 + stoploss)
                    trade.initial_stop_loss_pct = stoploss
                    trade.initial_stop_loss = trade.stop_loss

                open_trades[pair] = trade
                # Fees (open + close) are settled once at trade close via calc_profit;
                # deducting fee_open here as well would double-charge it.
                wallets.deduct_amount(self._config.stake_currency, actual_stake)

                logger.debug(f"Entry: {pair} @ {current_rate}, stake={actual_stake}")
                return

            # Check for short entry
            if getattr(strategy, 'can_short', False):
                enter_short = signal_row.get("enter_short", 0)
                if enter_short == 1:
                    # Similar to long but with is_short=True
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

                    actual_stake = stake_amount
                    available = wallets.get_available_stake_amount()
                    actual_stake = min(actual_stake, available)

                    if actual_stake <= 0:
                        return

                    amount = actual_stake / current_rate if current_rate > 0 else 0
                    if amount <= 0:
                        return

                    fee = actual_stake * self._fee_rate

                    trade = LocalTrade(
                        pair=pair,
                        exchange=self._config.exchange_name,
                        strategy=strategy.__class__.__name__,
                        timeframe=timeframe,
                        market_type=MarketType.CRYPTO,
                        open_date=current_date,
                        open_rate=current_rate,
                        amount=amount,
                        stake_amount=actual_stake,
                        fee_open=fee,
                        enter_tag=enter_tag,
                        max_rate=current_rate,
                        min_rate=current_rate,
                        is_short=True,
                    )

                    stoploss = getattr(strategy, 'stoploss', 0)
                    if stoploss != 0:
                        trade.stop_loss_pct = stoploss
                        trade.stop_loss = current_rate * (1 - stoploss)
                        trade.initial_stop_loss_pct = stoploss
                        trade.initial_stop_loss = trade.stop_loss

                    open_trades[pair] = trade
                    wallets.deduct_amount(self._config.stake_currency, actual_stake)

        except Exception as e:
            logger.warning(f"Error checking entry for {pair}: {e}", exc_info=True)

    def _check_exit(
        self,
        trade: LocalTrade,
        strategy: IStrategy,
        signal_row,
        current_rate: float,
        current_high: float,
        current_low: float,
        current_date: datetime,
        position_manager: PositionManager,
        wallets: Wallets,
        open_trades: Dict[str, LocalTrade],
        closed_bt_trades: List[BacktestTrade],
    ) -> None:
        """Check exit conditions for an open trade.

        Signal columns come from the precomputed per-pair dataframe; only
        user callbacks (custom_exit / confirm_trade_exit) run per candle.
        """
        # Update rate tracking
        trade.update_rate(current_rate)

        # Profit ratio at current rate - identical for trailing/ROI/custom
        # checks below, so compute once.
        profit_ratio = trade.calc_profit_ratio(current_rate)

        # 0. Enforce T+1/T+N settlement: the position cannot be sold before
        # its settlement date (compared against simulated time, NOT wall clock)
        rule = trade.settlement_rule
        settlement_date = trade.settlement_date
        if (
            rule is not None
            and rule.settlement_type != SettlementType.T0
            and settlement_date is not None
            and current_date < settlement_date
        ):
            logger.debug(
                f"Exit blocked for {trade.pair}: T+1 settlement until {settlement_date}"
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
            )
            return

        # 2. Check trailing stop
        trailing_stop = getattr(strategy, 'trailing_stop', False)
        if trailing_stop:
            trailing_stop_positive = getattr(strategy, 'trailing_stop_positive', 0.01)
            trailing_stop_positive_offset = getattr(strategy, 'trailing_stop_positive_offset', 0.0)
            trailing_only_offset = getattr(strategy, 'trailing_only_offset_is_reached', False)

            if not trailing_only_offset or profit_ratio >= trailing_stop_positive_offset:
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
                        )
                        return

        # 3. Check ROI
        minimal_roi = getattr(strategy, 'minimal_roi', {})
        if minimal_roi:
            trade_duration = (current_date - trade.open_date).total_seconds() / 60

            for minutes_str, roi_value in sorted(
                minimal_roi.items(),
                key=lambda x: int(x[0]) if str(x[0]).isdigit() else float("inf"),
                reverse=True,
            ):
                try:
                    minutes = int(minutes_str)
                except ValueError:
                    continue
                if trade_duration >= minutes and profit_ratio >= roi_value:
                    self._close_trade(
                        trade=trade,
                        rate=current_rate,
                        exit_reason=f"roi_{minutes}m",
                        current_date=current_date,
                        position_manager=position_manager,
                        wallets=wallets,
                        open_trades=open_trades,
                        closed_bt_trades=closed_bt_trades,
                    )
                    return

        # 4. Check custom exit
        exit_reason = self._safe_callback(
            f"custom_exit({trade.pair})",
            lambda: strategy.custom_exit(
                pair=trade.pair,
                trade=trade,
                current_time=current_date,
                current_rate=current_rate,
                current_profit=profit_ratio,
                exit_reason=None,
            ),
            None,
        )
        if exit_reason:
            self._close_trade(
                trade=trade,
                rate=current_rate,
                exit_reason=exit_reason,
                current_date=current_date,
                position_manager=position_manager,
                wallets=wallets,
                open_trades=open_trades,
                closed_bt_trades=closed_bt_trades,
            )
            return

        # 5. Check exit signal from strategy (precomputed columns)
        exit_long = signal_row.get("exit_long", 0)
        exit_short = signal_row.get("exit_short", 0)
        exit_tag = signal_row.get("exit_tag", None)

        should_exit = False
        if trade.is_short and exit_short == 1:
            should_exit = True
        elif not trade.is_short and exit_long == 1:
            should_exit = True

        if should_exit:
            # Confirm exit
            confirmed = self._safe_callback(
                f"confirm_trade_exit({trade.pair})",
                lambda: strategy.confirm_trade_exit(
                    pair=trade.pair,
                    trade=trade,
                    order_type="market",
                    amount=trade.amount,
                    rate=current_rate,
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
                rate=current_rate,
                exit_reason=exit_tag or "exit_signal",
                current_date=current_date,
                position_manager=position_manager,
                wallets=wallets,
                open_trades=open_trades,
                closed_bt_trades=closed_bt_trades,
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
    ) -> None:
        """Close a trade and record the result."""
        close_value = rate * trade.amount
        fee_close = close_value * self._fee_rate

        trade.close_date = current_date
        trade.close_rate = rate
        trade.fee_close = fee_close
        trade.exit_reason = exit_reason

        profit_abs = trade.calc_profit(rate)
        profit_pct = trade.calc_profit_ratio(rate) * 100
        duration_hours = (current_date - trade.open_date).total_seconds() / 3600

        # Update wallet
        total_return = trade.stake_amount + profit_abs
        wallets.add_amount(self._config.stake_currency, total_return)

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
        )
        closed_bt_trades.append(bt_trade)

        # Remove from open trades
        if trade.pair in open_trades:
            del open_trades[trade.pair]

        logger.debug(
            f"Exit: {trade.pair} @ {rate}, profit={profit_abs:.4f} "
            f"({profit_pct:.2f}%), reason={exit_reason}"
        )

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
