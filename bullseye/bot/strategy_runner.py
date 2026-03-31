"""
Strategy Runner - Strategy execution engine for Bullseye.

Manages the lifecycle and execution of trading strategies,
including data fetching, signal processing, and order execution.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

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

        Args:
            dataframe: Main timeframe dataframe
            pair: Current trading pair

        Returns:
            DataFrame with informative data merged in
        """
        try:
            # Get informative pairs from strategy
            informative_pairs = self._strategy.informative_pairs()

            for info_pair, info_timeframe in informative_pairs:
                if info_pair is None:
                    continue

                # Fetch informative data
                info_df = self._dp.historic_ohlcv(
                    pair=info_pair,
                    timeframe=info_timeframe,
                )

                if info_df.empty:
                    continue

                # Run strategy's informative indicator method if it exists
                # (handled by @informative decorator in strategy)
                metadata = {"pair": info_pair}

                # Check for informative decorator methods
                for attr_name in dir(self._strategy):
                    attr = getattr(self._strategy, attr_name, None)
                    if callable(attr) and hasattr(attr, "_informative"):
                        info_config = attr._informative
                        if info_config.get("pair") == info_pair or info_config.get("pair") is None:
                            # Call the informative method
                            try:
                                info_df = attr(info_df, metadata)
                            except Exception as e:
                                logger.debug(f"Error in informative method: {e}")

                # Merge informative data
                # Use suffix based on timeframe
                suffix = f"_{info_timeframe}"
                for col in info_df.columns:
                    if col not in ["date", "open", "high", "low", "close", "volume"]:
                        if col + suffix not in dataframe.columns:
                            # Simple merge - forward fill informative data
                            dataframe[col + suffix] = info_df[col].reindex(
                                dataframe.index, method="ffill"
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

        if enter_long == 1:
            self._handle_entry_signal(
                pair=pair,
                direction="long",
                rate=current_rate,
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
    ) -> None:
        """
        Handle an entry signal.

        Args:
            pair: Trading pair
            direction: "long" or "short"
            rate: Entry price
            enter_tag: Entry signal tag
            current_time: Current time
        """
        # Confirm entry with strategy
        try:
            confirmed = self._strategy.confirm_trade_entry(
                pair=pair,
                order_type="market",
                amount=0,  # Will be calculated
                rate=rate,
                time_in_force="GTC",
                current_time=current_time,
                entry_tag=enter_tag,
                side=direction,
            )

            if not confirmed:
                logger.debug(f"Entry signal rejected by strategy for {pair}")
                return

        except Exception as e:
            logger.warning(f"Error in confirm_trade_entry: {e}")
            # Continue with entry if confirm method not implemented

        # Execute entry
        trade = self._executor.execute_entry(
            pair=pair,
            rate=rate,
            enter_tag=enter_tag,
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

        Order of exit checks:
        1. Stop loss
        2. Trailing stop
        3. ROI
        4. Custom exit
        5. Exit signal

        Args:
            pair: Trading pair
            dataframe: Analyzed dataframe
            current_rate: Current price
            current_time: Current time
        """
        # Get open trade for this pair
        trade = self._pm.get_trade_for_pair(pair)
        if not trade:
            return

        # Update trade's rate tracking
        trade.update_rate(current_rate)

        # 1. Check stop loss
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

        # 3. Check ROI
        roi_reason = self._pm.check_roi(trade, current_rate, current_time)
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
            self._handle_exit_signal(
                trade=trade,
                rate=current_rate,
                exit_reason=custom_reason,
                current_time=current_time,
            )
            return

        # 5. Check exit signal from dataframe
        latest = dataframe.iloc[-1]
        exit_long = latest.get("exit_long", 0)
        exit_tag = latest.get("exit_tag", None)

        if exit_long == 1:
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
