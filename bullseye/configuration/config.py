"""
Configuration management for Bullseye.

Loads and manages configuration from YAML files with support for
environment variables and default values.
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class Config:
    """
    Configuration manager for Bullseye trading bot.

    Handles loading configuration from YAML files, accessing config values,
    and providing property shortcuts for common settings.

    Example:
        config = Config("config.yaml")
        print(config.dry_run)  # True/False
        print(config.get("exchange.name"))  # "binance"
    """

    # Default configuration values
    DEFAULTS: Dict[str, Any] = {
        "max_open_trades": 3,
        "stake_currency": "USDT",
        "stake_amount": 100,
        "tradable_balance_ratio": 0.99,
        "dry_run": True,
        "dry_run_wallet": 1000,
        "market_type": "auto",
        "db_url": "sqlite:///user_data/tradesv3.sqlite",
        "logfile": "user_data/logs/bullseye.log",
        "log_level": "INFO",
        "internals": {
            "process_throttle_secs": 5,
        },
        # Settlement configuration for T+0/T+1 rules
        # Set to "auto" for auto-detection, or specify per-pair rules
        "settlement": {
            "mode": "auto",  # "auto" or "manual"
            # Per-pair overrides (when mode is "auto", these take precedence)
            # Format: "pair": "t0" | "t1" | "t2"
            "overrides": {
                # Examples:
                # "000001.SZ": "t1",    # Force A-share to T+1
                # "SOMEPAIR": "t0",     # Force custom pair to T+0
            },
            # Default settlement type for unknown pairs (when auto-detection fails)
            "default": "t0",  # "t0", "t1", or "t2"
        },
    }

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration.

        Args:
            config_path: Path to YAML configuration file.
                        If None, uses default configuration only.
        """
        self._config: Dict[str, Any] = {}
        self._config_path: Optional[str] = None

        # Load defaults first
        self._config = self._deep_copy_dict(self.DEFAULTS)

        # Load from file if provided
        if config_path:
            self._config_path = config_path
            self._load_config(config_path)

        # Override with environment variables
        self._load_from_env()

    def _deep_copy_dict(self, d: Dict) -> Dict:
        """Deep copy a dictionary."""
        result = {}
        for key, value in d.items():
            if isinstance(value, dict):
                result[key] = self._deep_copy_dict(value)
            else:
                result[key] = value
        return result

    def _load_config(self, path: str) -> None:
        """
        Load configuration from a YAML file.

        Args:
            path: Path to the YAML configuration file.
        """
        config_file = Path(path)

        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with open(config_file, "r", encoding="utf-8") as f:
            file_config = yaml.safe_load(f) or {}

        # Merge with defaults (file config takes precedence)
        self._config = self._merge_dicts(self._config, file_config)

    def _merge_dicts(self, base: Dict, override: Dict) -> Dict:
        """
        Recursively merge two dictionaries.

        Args:
            base: Base dictionary (default values)
            override: Override dictionary (file values)

        Returns:
            Merged dictionary with override values taking precedence.
        """
        result = self._deep_copy_dict(base)

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_dicts(result[key], value)
            else:
                result[key] = value

        return result

    def _load_from_env(self) -> None:
        """Load configuration from environment variables."""
        # BULLSEYE_CONFIG override
        env_config = os.environ.get("BULLSEYE_CONFIG")
        if env_config and not self._config_path:
            self._load_config(env_config)

        # Individual environment variables
        env_mappings = {
            "BULLSEYE_DRY_RUN": ("dry_run", lambda x: x.lower() in ("true", "1", "yes")),
            "BULLSEYE_STAKE_CURRENCY": ("stake_currency", str),
            "BULLSEYE_STAKE_AMOUNT": ("stake_amount", float),
            "BULLSEYE_MAX_OPEN_TRADES": ("max_open_trades", int),
            "BULLSEYE_DB_URL": ("db_url", str),
            "BULLSEYE_LOG_LEVEL": ("log_level", str),
        }

        for env_var, (config_key, converter) in env_mappings.items():
            value = os.environ.get(env_var)
            if value is not None:
                try:
                    self._config[config_key] = converter(value)
                except (ValueError, TypeError):
                    pass  # Keep existing value if conversion fails

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value by key.

        Supports dot notation for nested keys.

        Args:
            key: Configuration key (e.g., "exchange.name" or "dry_run")
            default: Default value if key not found

        Returns:
            Configuration value or default.

        Example:
            config.get("dry_run")  # True
            config.get("exchange.name")  # "binance"
            config.get("nonexistent", "default")  # "default"
        """
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set a configuration value.

        Args:
            key: Configuration key (supports dot notation)
            value: Value to set
        """
        keys = key.split(".")
        config = self._config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

    def to_dict(self) -> Dict[str, Any]:
        """
        Get the entire configuration as a dictionary.

        Returns:
            Copy of the configuration dictionary.
        """
        return self._deep_copy_dict(self._config)

    # ==================== Property Shortcuts ====================

    @property
    def dry_run(self) -> bool:
        """Whether to run in dry-run (paper trading) mode."""
        return self._config.get("dry_run", True)

    @dry_run.setter
    def dry_run(self, value: bool) -> None:
        self._config["dry_run"] = value

    @property
    def dry_run_wallet(self) -> float:
        """Initial wallet balance for dry-run mode."""
        return float(self._config.get("dry_run_wallet", 1000))

    @property
    def stake_currency(self) -> str:
        """The currency used for staking (e.g., USDT, BTC)."""
        return self._config.get("stake_currency", "USDT")

    @property
    def stake_amount(self) -> float:
        """Amount to stake per trade."""
        amount = self._config.get("stake_amount", 100)
        return float(amount) if amount != "unlimited" else 0

    @property
    def stake_amount_unlimited(self) -> bool:
        """Whether stake amount is set to unlimited."""
        return self._config.get("stake_amount") == "unlimited"

    @property
    def max_open_trades(self) -> int:
        """Maximum number of concurrent open trades."""
        return int(self._config.get("max_open_trades", 3))

    @property
    def tradable_balance_ratio(self) -> float:
        """Ratio of balance that can be used for trading."""
        return float(self._config.get("tradable_balance_ratio", 0.99))

    @property
    def market_type(self) -> str:
        """Market type (auto, crypto, stock, future)."""
        return self._config.get("market_type", "auto")

    @property
    def db_url(self) -> str:
        """Database connection URL."""
        return self._config.get("db_url", "sqlite:///user_data/tradesv3.sqlite")

    @property
    def strategy(self) -> Optional[str]:
        """Strategy name from configuration."""
        return self._config.get("strategy")

    @property
    def strategy_path(self) -> str:
        """Path to strategy files."""
        return self._config.get("strategy_path", "user_data/strategies")

    @property
    def timeframe(self) -> str:
        """Default timeframe for the bot."""
        return self._config.get("timeframe", "5m")

    @property
    def exchange(self) -> Dict[str, Any]:
        """Exchange configuration."""
        return self._config.get("exchange", {})

    @property
    def exchange_name(self) -> str:
        """Exchange name."""
        return self.exchange.get("name", "binance")

    @property
    def pairlist(self) -> List[Dict[str, Any]]:
        """Pairlist configuration."""
        return self._config.get("pairlist", [])

    @property
    def internals(self) -> Dict[str, Any]:
        """Internal configuration."""
        return self._config.get("internals", {})

    @property
    def process_throttle_secs(self) -> int:
        """Throttle interval in seconds."""
        return int(self.internals.get("process_throttle_secs", 5))

    @property
    def log_level(self) -> str:
        """Logging level."""
        return self._config.get("log_level", "INFO")

    @property
    def logfile(self) -> Optional[str]:
        """Log file path."""
        return self._config.get("logfile")

    @property
    def settlement(self) -> Dict[str, Any]:
        """Settlement configuration for T+0/T+1 rules."""
        return self._config.get("settlement", {})

    @property
    def settlement_mode(self) -> str:
        """Settlement mode: 'auto' or 'manual'."""
        return self.settlement.get("mode", "auto")

    @property
    def settlement_overrides(self) -> Dict[str, str]:
        """Per-pair settlement type overrides."""
        return self.settlement.get("overrides", {})

    @property
    def settlement_default(self) -> str:
        """Default settlement type for unknown pairs."""
        return self.settlement.get("default", "t0")

    def __repr__(self) -> str:
        return f"Config(dry_run={self.dry_run}, exchange={self.exchange_name})"
