"""
BullseyeBot - Core trading bot for Bullseye.

The main bot class that integrates all components and runs
the trading loop.
"""
import importlib
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from bullseye.configuration.config import Config
from bullseye.data.dataprovider import DataProvider
from bullseye.gateway.base import BaseGateway
from bullseye.gateway.crypto.ccxt_gateway import CcxtGateway
from bullseye.gateway.dryrun.dryrun_gateway import DryRunGateway
from bullseye.order.order_executor import OrderExecutor
from bullseye.order.position_manager import PositionManager
from bullseye.order.settlement import init_settlement_detector
from bullseye.strategy.interface import IStrategy
from bullseye.trader.eventengine import EventEngine
from bullseye.trader.engine import MainEngine
from bullseye.wallets.wallets import Wallets

from .strategy_runner import StrategyRunner

logger = logging.getLogger(__name__)


class BullseyeBot:
    """
    Bullseye Trading Bot.

    The main bot class that:
    - Loads configuration
    - Initializes gateways
    - Sets up data providers and wallets
    - Loads trading strategies
    - Runs the main trading loop

    Example:
        config = Config("config.yaml")
        bot = BullseyeBot(config, MyStrategy)
        bot.run()
    """

    def __init__(
        self,
        config: Config,
        strategy_class: Optional[Type[IStrategy]] = None,
    ):
        """
        Initialize the Bullseye Bot.

        Args:
            config: Configuration object
            strategy_class: Strategy class to use (optional, can be loaded from config)
        """
        self._config = config
        self._strategy_class = strategy_class

        # Components
        self._event_engine: Optional[EventEngine] = None
        self._main_engine: Optional[MainEngine] = None
        self._gateway: Optional[BaseGateway] = None
        self._real_gateway: Optional[BaseGateway] = None
        self._data_provider: Optional[DataProvider] = None
        self._wallets: Optional[Wallets] = None
        self._position_manager: Optional[PositionManager] = None
        self._order_executor: Optional[OrderExecutor] = None
        self._strategy: Optional[IStrategy] = None
        self._strategy_runner: Optional[StrategyRunner] = None

        # State
        self._pairlist: List[str] = []
        self._running = False
        self._startup_time: Optional[datetime] = None

        logger.info(f"BullseyeBot initialized with config: dry_run={config.dry_run}")

    # ==================== Initialization ====================

    def _initialize(self) -> None:
        """Initialize all bot components with proper cleanup on failure."""
        logger.info("Initializing Bullseye Bot...")

        try:
            # 0. Initialize settlement detector with config
            init_settlement_detector(self._config.settlement)
            logger.debug("Settlement detector initialized")

            # 1. Create event engine
            self._event_engine = EventEngine()
            logger.debug("Event engine created")

            # 2. Create main engine
            self._main_engine = MainEngine(self._event_engine)
            logger.debug("Main engine created")

            # 3. Create gateway
            self._gateway = self._create_gateway()
            logger.info(f"Gateway created: {self._gateway.gateway_name}")

            # 4. Create data provider
            self._data_provider = DataProvider(
                config=self._config,
                gateway=self._gateway,
            )
            logger.debug("Data provider created")

            # 5. Load pairlist
            self._pairlist = self._create_pairlist()
            if not self._pairlist:
                raise ValueError("No trading pairs configured")
            self._data_provider.set_pairlist(self._pairlist)
            logger.info(f"Pairlist loaded: {self._pairlist}")

            # 6. Create wallets
            self._wallets = Wallets(
                config=self._config,
                initial_balance=self._config.dry_run_wallet if self._config.dry_run else None,
            )
            logger.debug(f"Wallets created: {self._wallets}")

            # 7. Create position manager
            self._position_manager = PositionManager(
                config=self._config,
                wallets=self._wallets,
            )
            logger.debug("Position manager created")

            # 8. Create order executor
            self._order_executor = OrderExecutor(
                config=self._config,
                position_manager=self._position_manager,
                wallets=self._wallets,
            )
            logger.debug("Order executor created")

            # 9. Load strategy
            self._strategy = self._load_strategy()
            logger.info(f"Strategy loaded: {self._strategy.__class__.__name__}")

            # 10. Create strategy runner
            self._strategy_runner = StrategyRunner(
                config=self._config,
                strategy=self._strategy,
                data_provider=self._data_provider,
                order_executor=self._order_executor,
                position_manager=self._position_manager,
                wallets=self._wallets,
            )
            logger.debug("Strategy runner created")

            logger.info("Bullseye Bot initialization complete")

        except Exception as e:
            logger.error(f"Initialization failed: {e}", exc_info=True)
            # Cleanup partially initialized resources
            self._cleanup()
            raise

    def _cleanup(self) -> None:
        """Cleanup resources on initialization failure or shutdown."""
        # Stop and cleanup event engine
        if self._event_engine:
            try:
                self._event_engine.stop()
            except Exception as e:
                logger.debug(f"Error stopping event engine during cleanup: {e}")
            self._event_engine = None

        # Close gateway
        if self._gateway:
            try:
                self._gateway.close()
            except Exception as e:
                logger.debug(f"Error closing gateway during cleanup: {e}")
            self._gateway = None

        # Clear other references
        self._main_engine = None
        self._data_provider = None
        self._wallets = None
        self._position_manager = None
        self._order_executor = None
        self._strategy_runner = None
        logger.debug("Cleanup completed")

    def _create_gateway(self) -> BaseGateway:
        """
        Create the appropriate gateway based on configuration.

        Returns:
            Gateway instance
        """
        exchange_config = self._config.exchange
        exchange_name = exchange_config.get("name", "binance")

        if self._config.dry_run:
            # Create real gateway for market data
            self._real_gateway = CcxtGateway(
                event_engine=self._event_engine,
                exchange_name=exchange_name,
            )

            # Wrap in DryRun gateway
            return DryRunGateway(
                event_engine=self._event_engine,
                real_gateway=self._real_gateway,
                initial_balance=self._config.dry_run_wallet,
                stake_currency=self._config.stake_currency,
            )
        else:
            # Live mode - use real gateway
            return CcxtGateway(
                event_engine=self._event_engine,
                exchange_name=exchange_name,
            )

    def _create_pairlist(self) -> List[str]:
        """
        Create the trading pairlist from configuration.

        Returns:
            List of trading pairs
        """
        pairlist_config = self._config.pairlist

        for pl_config in pairlist_config:
            method = pl_config.get("method", "")

            if method == "StaticPairList":
                pairs = pl_config.get("config", {}).get("pairs", [])
                if pairs:
                    return pairs

        # Default pairs if nothing configured
        default_pairs = ["BTC/USDT", "ETH/USDT"]
        logger.warning(f"No pairlist configured, using defaults: {default_pairs}")
        return default_pairs

    def _load_strategy(self) -> IStrategy:
        """
        Load the trading strategy.

        Returns:
            Strategy instance

        Raises:
            ValueError: If no strategy is specified
            ImportError: If strategy cannot be loaded
        """
        errors = []

        # If strategy class was provided directly
        if self._strategy_class:
            try:
                return self._strategy_class()
            except Exception as e:
                raise ImportError(f"Failed to instantiate provided strategy class: {e}") from e

        # Load from config
        strategy_name = self._config.strategy
        if not strategy_name:
            raise ValueError(
                "No strategy specified in configuration. "
                "Add 'strategy: YourStrategyName' to config.yaml or pass strategy class directly."
            )

        # Try to import from user_data/strategies
        strategy_path = Path(self._config.strategy_path)
        if strategy_path.exists():
            sys.path.insert(0, str(strategy_path.parent))

        # Try direct import from strategy path
        try:
            module = importlib.import_module(f"{strategy_path.name}.{strategy_name}")
            strategy_class = getattr(module, strategy_name)
            logger.info(f"Loaded strategy '{strategy_name}' from {strategy_path}")
            return strategy_class()
        except ImportError as e:
            errors.append(f"From strategy path '{strategy_path}': {e}")
        except AttributeError:
            errors.append(
                f"Module found at '{strategy_path}' but no class named '{strategy_name}'"
            )

        # Try importing by name
        try:
            module = importlib.import_module(strategy_name)
            strategy_class = getattr(module, strategy_name)
            logger.info(f"Loaded strategy '{strategy_name}' from installed modules")
            return strategy_class()
        except ImportError as e:
            errors.append(f"As installed module: {e}")
        except AttributeError:
            errors.append(f"Module '{strategy_name}' found but no class named '{strategy_name}'")

        # Provide helpful error message
        error_msg = (
            f"Could not load strategy '{strategy_name}'.\n"
            f"Attempted paths:\n"
        )
        for i, err in enumerate(errors, 1):
            error_msg += f"  {i}. {err}\n"
        error_msg += (
            f"\nSearched in:\n"
            f"  - {strategy_path}/{strategy_name}.py\n"
            f"  - Installed Python modules\n"
            f"\nMake sure the strategy file exists and contains a class named '{strategy_name}'."
        )
        raise ImportError(error_msg)

    # ==================== Bot Lifecycle ====================

    def start(self) -> None:
        """Start the trading bot."""
        if self._running:
            logger.warning("Bot is already running")
            return

        # Initialize if not done
        if self._gateway is None:
            self._initialize()

        logger.info("Starting Bullseye Bot...")
        self._startup_time = datetime.now()

        # Connect gateway
        exchange_config = self._config.exchange
        self._gateway.connect(
            api_key=exchange_config.get("key", ""),
            secret=exchange_config.get("secret", ""),
            passphrase=exchange_config.get("passphrase", ""),
            sandbox=exchange_config.get("sandbox", False),
        )

        # Start event engine
        self._event_engine.start()

        # Start strategy runner
        self._strategy_runner.start()

        self._running = True
        logger.info("Bullseye Bot started successfully")

    def stop(self) -> None:
        """Stop the trading bot."""
        if not self._running:
            return

        logger.info("Stopping Bullseye Bot...")

        self._running = False

        # Stop strategy runner
        if self._strategy_runner:
            self._strategy_runner.stop()

        # Stop event engine
        if self._event_engine:
            self._event_engine.stop()

        # Close gateway
        if self._gateway:
            self._gateway.close()

        # Log final statistics
        self._log_statistics()

        logger.info("Bullseye Bot stopped")

    def run(self) -> None:
        """
        Run the trading bot (blocking).

        This starts the bot and runs the main loop until interrupted.
        """
        self.start()

        try:
            # Main loop
            while self._running:
                # Process each pair
                self._process_cycle()

                # Sleep for throttle interval
                time.sleep(self._config.process_throttle_secs)

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        finally:
            self.stop()

    def _process_cycle(self) -> None:
        """Process one cycle of the trading loop."""
        if not self._strategy_runner or not self._strategy_runner.is_running():
            return

        # Process each pair in the pairlist
        for pair in self._pairlist:
            try:
                self._strategy_runner.process_pair(pair)
            except Exception as e:
                logger.error(f"Error processing {pair}: {e}")

    # ==================== Statistics ====================

    def _log_statistics(self) -> None:
        """Log trading statistics."""
        if not self._position_manager:
            return

        stats = self._position_manager.get_stats()

        logger.info("=" * 50)
        logger.info("Trading Statistics:")
        logger.info(f"  Total Trades: {stats['total_trades']}")
        logger.info(f"  Winning Trades: {stats['winning_trades']}")
        logger.info(f"  Losing Trades: {stats['losing_trades']}")
        logger.info(f"  Win Rate: {stats['win_rate'] * 100:.2f}%")
        logger.info(f"  Total Profit: {stats['total_profit']:.4f}")
        logger.info(f"  Average Profit: {stats['avg_profit']:.4f}")
        logger.info(f"  Open Trades: {stats['open_trades']}")
        logger.info("=" * 50)

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get current trading statistics.

        Returns:
            Dictionary with trading statistics
        """
        if not self._position_manager:
            return {}

        stats = self._position_manager.get_stats()
        stats["running"] = self._running
        stats["uptime"] = str(datetime.now() - self._startup_time) if self._startup_time else "0"
        stats["balance"] = self._wallets.get_total() if self._wallets else 0
        stats["available"] = self._wallets.get_available_stake_amount() if self._wallets else 0

        return stats

    # ==================== Utility ====================

    @property
    def is_running(self) -> bool:
        """Check if bot is running."""
        return self._running

    @property
    def pairlist(self) -> List[str]:
        """Get current pairlist."""
        return self._pairlist.copy()

    @property
    def strategy(self) -> Optional[IStrategy]:
        """Get current strategy."""
        return self._strategy

    @property
    def balance(self) -> float:
        """Get current balance."""
        if self._wallets:
            return self._wallets.get_total()
        return 0.0

    def __repr__(self) -> str:
        status = "running" if self._running else "stopped"
        return f"BullseyeBot({status}, strategy={self._strategy.__class__.__name__ if self._strategy else 'None'})"
