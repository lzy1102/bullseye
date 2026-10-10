"""
Strategy Runner - Strategy execution engine for Bullseye.

Manages the lifecycle and execution of trading strategies,
including data fetching, signal processing, and order execution.
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

from bullseye.configuration.config import Config
from bullseye.data.dataprovider import DataProvider
from bullseye.order.order_executor import OrderExecutor
from bullseye.order.position_manager import LocalTrade, PositionManager
from bullseye.strategy.interface import IStrategy
from bullseye.wallets.wallets import Wallets

logger = logging.getLogger(__name__)


class StrategyRunner:
    """
    Strategy Runner for Bullseye.

    This class manages the execution of a trading strategy:
    - Initializes the strategy with required dependencies
    - Fetches market data for each trading pair
    - Executes strategy methods (indicators, signals)
    - Processes entry and exit signals
    - Manages stop-loss, trailing stop, and ROI

    The runner is called periodically by the bot's main loop.
    """

    def __init__(
        self,
        config: Config,
        strategy: IStrategy,
        data_provider: DataProvider,
        order_executor: OrderExecutor,
        position_manager: PositionManager,
        wallets: Wallets,
    ):
        """
        Initialize the Strategy Runner.

        Args:
            config: Configuration object
            strategy: Strategy instance
            data_provider: Data provider for market data
            order_executor: Order executor for trade execution
            position_manager: Position manager for trade tracking
            wallets: Wallet manager for balance tracking
        """
        self._config = config
        self._strategy = strategy
        self._dp = data_provider
        self._executor = order_executor
        self._pm = position_manager
        self._wallets = wallets

        # Set strategy dependencies
        self._strategy.dp = data_provider
        self._strategy.wallets = wallets
        self._strategy.config = config.to_dict()

        # Set strategy on executor and position manager
        self._executor.set_strategy(strategy)
        self._pm.set_strategy(strategy)

        # Analysis cache: pair -> (dataframe, last_analyzed_time)
        self._analysis_cache: Dict[str, tuple] = {}
        # Last processed (closed) candle per pair: gates re-analysis to
        # once per new candle instead of every throttle tick.
        self._last_candle: Dict[str, Any] = {}

        # Running state
        self._running = False
        self._last_process_time: Optional[datetime] = None

    # ==================== Lifecycle ====================

    def start(self) -> None:
        """Start the strategy runner."""
        logger.info(f"Starting strategy: {self._strategy.__class__.__name__}")

        # Call strategy's bot_start callback
        try:
            self._strategy.bot_start()
            logger.info("Strategy bot_start callback completed")
        except Exception as e:
            logger.error(f"Error in strategy bot_start: {e}")

        self._running = True

    def stop(self) -> None:
        """Stop the strategy runner."""
        logger.info("Stopping strategy runner")
        self._running = False

        # Call strategy's bot_stop callback
        try:
            self._strategy.bot_stop()
        except Exception as e:
            logger.error(f"Error in strategy bot_stop: {e}")

    # ==================== Main Processing ====================

    def process_pair(self, pair: str) -> None:
        """
        Process a single trading pair.

        This is the main entry point for strategy execution on a pair.

        Args:
            pair: Trading pair to process
        """
        if not self._running:
            return

        try:
            # Get current time
            current_time = datetime.now()

            # 1. Fetch and analyze data
            dataframe = self._analyze_pair(pair)
            if dataframe is None or dataframe.empty:
                logger.debug(f"No data available for {pair}")
                return

            # Get latest candle
            latest = dataframe.iloc[-1]
            current_rate = latest.get("close", 0)

            if current_rate <= 0:
                return

            # Process only once per new closed candle (freqtrade
            # process_only_new_candles semantics): re-evaluating the same
            # bar every throttle tick duplicated signals and burned CPU
            # re-running indicators on full history.
            candle = latest.get("date") if hasattr(latest, "get") else None
            if candle is not None:
                if self._last_candle.get(pair) == candle:
                    return
                self._last_candle[pair] = candle

            # 2. Check for exit signals (if we have an open trade)
            self._check_exit_signals(pair, dataframe, current_rate, current_time)

            # 3. Check for entry signals
            self._check_entry_signals(pair, dataframe, current_rate, current_time)

            # Update last process time
            self._last_process_time = current_time

        except Exception as e:
            logger.error(f"Error processing {pair}: {e}", exc_info=True)

    def _analyze_pair(self, pair: str) -> Optional[pd.DataFrame]:
        """
        Analyze a trading pair using the strategy.

        This fetches data and runs all strategy analysis methods.

        Args:
            pair: Trading pair

        Returns:
            Analyzed DataFrame or None if error
        """
        try:
            # Get historical data
            timeframe = self._strategy.timeframe
            startup_candles = getattr(self._strategy, "startup_candle_count", 30)

            dataframe = self._dp.historic_ohlcv(
                pair=pair,
                timeframe=timeframe,
                startup_candles=startup_candles + 100,  # Extra for indicators
            )

            if dataframe.empty:
                return None

            # Drop the still-forming candle: acting on it repaints (the
            # signal can appear/disappear within the same bar) and makes
            # live results diverge from backtests, which only ever see
            # closed candles.
            try:
                from bullseye.strategy.interface import timeframe_to_minutes
                tf_min = timeframe_to_minutes(timeframe)
                last_ts = pd.Timestamp(dataframe["date"].iloc[-1])
                now_ts = (pd.Timestamp.now(tz=last_ts.tzinfo)
                          if last_ts.tzinfo else pd.Timestamp.now())
                if last_ts + pd.Timedelta(minutes=tf_min) > now_ts:
                    dataframe = dataframe.iloc[:-1]
            except Exception:
                pass
            if dataframe.empty:
                return None

            # Add informative pairs data
            dataframe = self._add_informative_pairs(dataframe, pair)

            # Run strategy analysis
            metadata = {"pair": pair}

            # Populate indicators
            dataframe = self._strategy.populate_indicators(dataframe, metadata)

            # Populate entry signals
            dataframe = self._strategy.populate_entry_trend(dataframe, metadata)

            # Populate exit signals
            dataframe = self._strategy.populate_exit_trend(dataframe, metadata)

            return dataframe

        except Exception as e:
            logger.error(f"Error analyzing {pair}: {e}")
            return None

    def _add_informative_pairs(
        self,
        dataframe: pd.DataFrame,
        pair: str,
    ) -> pd.DataFrame:
        """
        Add informative pair data to the dataframe.

        Runs every @informative-declared method on its own timeframe/pair
        and merges the result with the lookahead-safe date-shift merge
        (previously: wrong marker attribute so methods never ran, matched
        on a nonexistent key, and merged positionally across different
        timeframe row counts).

        Args:
            dataframe: Main timeframe dataframe
            pair: Current trading pair

        Returns:
            DataFrame with informative data merged in
        """
        from bullseye.strategy.interface import (
            collect_informative_specs,
            merge_informative_pair,
            resolve_informative_pair,
        )

        try:
            base_timeframe = getattr(self._strategy, "timeframe", "")
            stake_currency = self._config.stake_currency
            for spec in collect_informative_specs(self._strategy):
                inf_tf = spec["timeframe"]
                if not inf_tf:
                    continue
                inf_pair = resolve_informative_pair(
                    pair, spec["asset"], stake_currency=stake_currency
                )
                try:
                    if inf_pair == pair and inf_tf == base_timeframe:
                        info_df = dataframe.copy()
                    else:
                        info_df = self._dp.historic_ohlcv(
                            pair=inf_pair,
                            timeframe=inf_tf,
                        )
                        if info_df.empty:
                            logger.debug(
                                f"No informative data for {inf_pair} {inf_tf}"
                            )
                            continue
                        info_df = info_df.copy()
                    analyzed = spec["method"](info_df, {"pair": inf_pair})
                    if analyzed is None or getattr(analyzed, "empty", False):
                        continue
                    dataframe = merge_informative_pair(
                        dataframe, analyzed, base_timeframe, inf_tf
                    )
                except Exception as e:
                    logger.debug(
                        f"Error in informative {spec['method_name']}: {e}"
                    )
        except Exception as e:
            logger.debug(f"Error adding informative pairs: {e}")

        return dataframe

    # ==================== Entry Signals ====================

    def _check_entry_signals(
        self,
        pair: str,
        dataframe: pd.DataFrame,
        current_rate: float,
        current_time: datetime,
    ) -> None:
        """
        Check for entry signals in the analyzed dataframe.

        Args:
            pair: Trading pair
            dataframe: Analyzed dataframe
            current_rate: Current price
            current_time: Current time
        """
        # Check if we already have an open trade for this pair
        if self._pm.has_open_trade(pair):
            return

        # Check if we can open new trades
        if not self._pm.can_open_trade():
            return

        # Get latest row
        latest = dataframe.iloc[-1]

        # Check for long entry signal
        enter_long = latest.get("enter_long", 0)
        enter_tag = latest.get("enter_tag", None)

        # Previous close for limit-up guards (A-shares).
        prev_close = (
            float(dataframe["close"].iloc[-2])
            if len(dataframe) >= 2 else current_rate
        )

        if enter_long == 1:
            self._handle_entry_signal(
                pair=pair,
                direction="long",
                rate=current_rate,
                prev_close=prev_close,
                enter_tag=enter_tag,
                current_time=current_time,
            )

        # Check for short entry signal (if strategy supports shorting)
        if getattr(self._strategy, "can_short", False):
            enter_short = latest.get("enter_short", 0)
            if enter_short == 1:
                self._handle_entry_signal(
                    pair=pair,
                    direction="short",
                    rate=current_rate,
                    prev_close=prev_close,
                    enter_tag=enter_tag,
                    current_time=current_time,
                )

    def _handle_entry_signal(
        self,
        pair: str,
        direction: str,
        rate: float,
        enter_tag: Optional[str],
        current_time: datetime,
        prev_close: Optional[float] = None,
    ) -> None:
        """
        Handle an entry signal.

        Args:
            pair: Trading pair
            direction: "long" or "short"
            rate: Entry price
            enter_tag: Entry signal tag
            current_time: Current time
            prev_close: Previous close for limit-up guard (optional)
        """
        from bullseye.order.stock_rules import (
            detect_market_type,
            limit_ratio_for,
            locked_at_limit_up,
        )

        # A-share limit-up lock rejects buys (mirrors backtests).
        if (
            direction != "short"
            and detect_market_type(pair) == "stock"
            and prev_close
            and locked_at_limit_up(
                rate, prev_close, limit_ratio_for(self._config, pair)
            )
        ):
            logger.debug(f"Entry skipped for {pair}: locked at limit-up")
            return

        # confirm_trade_entry is invoked exactly once, inside
        # OrderExecutor.execute_entry (canonical freqtrade placement);
        # the runner used to call it a second time with placeholder args.

        # Execute entry (stake/leverage/entry-price resolved inside)
        trade = self._executor.execute_entry(
            pair=pair,
            rate=rate,
            enter_tag=enter_tag,
            side=direction,
            current_time=current_time,
        )

        if trade:
            logger.info(
                f"Entry signal executed: {pair} {direction} @ {rate}, tag={enter_tag}"
            )

    # ==================== Exit Signals ====================

    def _check_exit_signals(
        self,
        pair: str,
        dataframe: pd.DataFrame,
        current_rate: float,
        current_time: datetime,
    ) -> None:
        """
        Check for exit signals and conditions.

        Order mirrors the backtest engine so live and paper agree:
        0. Position adjustment (DCA)
        0a. Limit-down block (A-shares)
        1. Stop loss (incl. custom_stoploss)
        2. Trailing stop
        3. ROI (incl. custom_roi, ignore_roi_if_entry_signal)
        4. Custom exit
        5. Exit signal (use_exit_signal / exit_profit_only)

        Args:
            pair: Trading pair
            dataframe: Analyzed dataframe
            current_rate: Current price
            current_time: Current time
        """
        from bullseye.order.stock_rules import (
            detect_market_type,
            limit_ratio_for,
            locked_at_limit_down,
        )

        # Get open trade for this pair
        trade = self._pm.get_trade_for_pair(pair)
        if not trade:
            return

        # Update trade's rate tracking
        trade.update_rate(current_rate)

        prev_close = (
            float(dataframe["close"].iloc[-2])
            if len(dataframe) >= 2 else current_rate
        )

        # 0. Position adjustment (DCA adds are buys; T+1 does not block them)
        try:
            self._executor.execute_adjust(
                trade=trade,
                rate=current_rate,
                current_time=current_time,
            )
        except Exception as e:
            logger.warning(f"Error in position adjustment: {e}")

        # 0a. Limit-down lock blocks all sells (mirrors backtests).
        if (
            not trade.is_short
            and detect_market_type(pair) == "stock"
            and locked_at_limit_down(
                current_rate, prev_close,
                limit_ratio_for(self._config, pair),
            )
        ):
            logger.debug(f"Exit blocked for {pair}: locked at limit-down")
            return

        # 1. Check stop loss (incl. custom_stoploss via position manager)
        if self._pm.check_stoploss(trade, current_rate):
            self._handle_exit_signal(
                trade=trade,
                rate=current_rate,
                exit_reason="stoploss",
                current_time=current_time,
            )
            return

        # 2. Check trailing stop
        if self._executor.check_trailing_stop(trade, current_rate):
            self._handle_exit_signal(
                trade=trade,
                rate=current_rate,
                exit_reason="trailing_stop",
                current_time=current_time,
            )
            return

        # 3. Check ROI (custom_roi + entry-signal guard inside)
        latest = dataframe.iloc[-1]
        has_entry = bool(
            latest.get("enter_long", 0) == 1
            or latest.get("enter_short", 0) == 1
        )
        roi_reason = self._pm.check_roi(
            trade, current_rate, current_time,
            has_entry_signal=has_entry,
        )
        if roi_reason:
            self._handle_exit_signal(
                trade=trade,
                rate=current_rate,
                exit_reason=roi_reason,
                current_time=current_time,
            )
            return

        # 4. Check custom exit
        custom_reason = self._executor.check_custom_exit(
            trade=trade,
            current_rate=current_rate,
            current_time=current_time,
        )
        if custom_reason:
            if getattr(self._strategy, "exit_profit_only", False):
                if trade.calc_profit_ratio(current_rate) <= 0:
                    return
            self._handle_exit_signal(
                trade=trade,
                rate=current_rate,
                exit_reason=custom_reason,
                current_time=current_time,
            )
            return

        # 5. Check exit signal from dataframe
        if not getattr(self._strategy, "use_exit_signal", True):
            return
        exit_long = latest.get("exit_long", 0)
        exit_short = latest.get("exit_short", 0)
        exit_tag = latest.get("exit_tag", None)

        should_exit = (
            (trade.is_short and exit_short == 1)
            or (not trade.is_short and exit_long == 1)
        )
        if should_exit and getattr(self._strategy, "exit_profit_only", False):
            if trade.calc_profit_ratio(current_rate) <= 0:
                return

        if should_exit:
            # Confirm exit with strategy
            try:
                confirmed = self._strategy.confirm_trade_exit(
                    pair=pair,
                    trade=trade,
                    order_type="market",
                    amount=trade.amount,
                    rate=current_rate,
                    time_in_force="GTC",
                    exit_reason="exit_signal",
                    current_time=current_time,
                )

                if not confirmed:
                    logger.debug(f"Exit signal rejected by strategy for {pair}")
                    return

            except Exception as e:
                logger.warning(f"Error in confirm_trade_exit: {e}")

            self._handle_exit_signal(
                trade=trade,
                rate=current_rate,
                exit_reason=exit_tag or "exit_signal",
                current_time=current_time,
            )

    def _handle_exit_signal(
        self,
        trade: LocalTrade,
        rate: float,
        exit_reason: str,
        current_time: datetime,
    ) -> None:
        """
        Handle an exit signal.

        Args:
            trade: Trade to close
            rate: Exit price
            exit_reason: Reason for exit
            current_time: Current time
        """
        # Custom exit price (e.g. limit offset) before execution.
        if self._strategy is not None:
            try:
                custom_rate = self._strategy.custom_exit_price(
                    pair=trade.pair,
                    trade=trade,
                    current_time=current_time,
                    proposed_rate=rate,
                    current_profit=trade.calc_profit_ratio(rate),
                    exit_tag=exit_reason,
                )
                if custom_rate is not None and float(custom_rate) > 0:
                    rate = float(custom_rate)
            except AttributeError:
                pass
            except Exception as e:
                logger.warning(f"Error in custom_exit_price: {e}")

        # Execute exit
        closed_trade = self._executor.execute_exit(
            trade=trade,
            rate=rate,
            exit_reason=exit_reason,
        )

        if closed_trade:
            logger.info(
                f"Exit signal executed: {trade.pair} @ {rate}, "
                f"profit={closed_trade.close_profit_abs:.4f}, "
                f"reason={exit_reason}"
            )

    # ==================== Utility ====================

    def get_strategy_name(self) -> str:
        """Get the strategy class name."""
        return self._strategy.__class__.__name__

    def is_running(self) -> bool:
        """Check if the runner is active."""
        return self._running

    def get_last_process_time(self) -> Optional[datetime]:
        """Get the last process time."""
        return self._last_process_time
