"""
Settlement Rules - Automatic T+1/T+0 Detection for Bullseye.

Automatically detects settlement rules based on trading pair format
and market configuration.

T+1 Markets:
- A-shares (China): 000001.SZ, 600000.SH, etc.
- Some other stock markets

T+0 Markets (No settlement restriction):
- Cryptocurrency: BTC/USDT, ETH/USDT, etc.
- US Stocks: AAPL, GOOGL, TSLA, etc.
- Hong Kong Stocks: 00700.HK, 09988.HK, etc.
- Futures: AU2506@SHFE, IF2506@CFFEX, etc.
- Options: 10003419@SH (stock options)
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class SettlementType(Enum):
    """Settlement type enumeration."""
    T0 = "t0"  # Can sell immediately (crypto, US stock, HK stock, futures)
    T1 = "t1"  # Can sell next trading day (A-share)
    T2 = "t2"  # Can sell in 2 trading days (some markets)


@dataclass
class SettlementRule:
    """Settlement rule for a market."""
    market_name: str
    settlement_type: SettlementType
    description: str
    # For T+N, the number of days to wait
    settlement_days: int = 1
    # Skip weekends for settlement calculation
    skip_weekends: bool = True
    # Market open time (for settlement date)
    market_open_hour: int = 9
    market_open_minute: int = 30
    # exchange_calendars calendar code (e.g. "XSHG" for Shanghai).
    # When set and exchange_calendars is installed, holidays are skipped too.
    calendar_code: Optional[str] = None


# Predefined settlement rules for different markets
SETTLEMENT_RULES: Dict[str, SettlementRule] = {
    # ==================== T+0 Markets ====================
    "crypto": SettlementRule(
        market_name="Cryptocurrency",
        settlement_type=SettlementType.T0,
        description="24/7 trading, no settlement restriction",
        settlement_days=0,
    ),
    "us_stock": SettlementRule(
        market_name="US Stock",
        settlement_type=SettlementType.T0,
        description="US stocks can be sold same day (T+0)",
        settlement_days=0,
        market_open_hour=9,
        market_open_minute=30,
    ),
    "hk_stock": SettlementRule(
        market_name="Hong Kong Stock",
        settlement_type=SettlementType.T0,
        description="HK stocks can be sold same day (T+0)",
        settlement_days=0,
        market_open_hour=9,
        market_open_minute=30,
    ),
    "future": SettlementRule(
        market_name="Futures",
        settlement_type=SettlementType.T0,
        description="Futures can be closed anytime (T+0)",
        settlement_days=0,
    ),
    "option": SettlementRule(
        market_name="Options",
        settlement_type=SettlementType.T0,
        description="Options can be closed anytime (T+0)",
        settlement_days=0,
    ),
    "forex": SettlementRule(
        market_name="Forex",
        settlement_type=SettlementType.T0,
        description="Forex can be closed anytime (T+0)",
        settlement_days=0,
    ),

    # ==================== T+1 Markets ====================
    "a_share": SettlementRule(
        market_name="A-Share (China)",
        settlement_type=SettlementType.T1,
        description="A-shares can only be sold next trading day (T+1)",
        settlement_days=1,
        skip_weekends=True,
        market_open_hour=9,
        market_open_minute=30,
        calendar_code="XSHG",  # Shanghai Stock Exchange calendar (holidays aware)
    ),
    "tw_stock": SettlementRule(
        market_name="Taiwan Stock",
        settlement_type=SettlementType.T1,
        description="Taiwan stocks T+1 settlement",
        settlement_days=1,
        skip_weekends=True,
        market_open_hour=9,
        market_open_minute=0,
    ),
}


class SettlementDetector:
    """
    Automatic settlement rule detector.

    Detects the appropriate settlement rule based on:
    1. Configuration override (highest priority)
    2. Trading pair format (auto-detection)
    3. Exchange name hint
    4. Default rule (fallback)

    Pair Format Recognition:
    - A-shares: 000001.SZ, 600000.SH, 300001.SZ, 688001.SH
    - US Stocks: AAPL, GOOGL, TSLA (pure letters)
    - HK Stocks: 00700.HK, 09988.HK (5-digit + .HK)
    - Crypto: BTC/USDT, ETH/USDT (with /)
    - Futures: AU2506@SHFE, IF2506@CFFEX

    Configuration Support:
    - mode: "auto" (default) or "manual" (overrides + default only, no detection)
    - overrides: Per-pair settlement type overrides
    - default: Default settlement type for unknown pairs

    Example config.yaml:
        settlement:
          mode: "auto"
          overrides:
            "000001.SZ": "t1"
            "CUSTOM/PAIR": "t0"
          default: "t0"
    """

    # A-share patterns
    A_SHARE_PATTERNS = [
        r'^\d{6}\.(SZ|SH|BJ)$',  # 000001.SZ, 600000.SH, etc.
        r'^[036]\d{5}$',  # 6-digit code starting with 0, 3, or 6
    ]

    # US stock pattern (1-5 letters, possibly with .US suffix)
    US_STOCK_PATTERN = r'^[A-Z]{1,5}(\.US)?$'

    # HK stock pattern (5-digit + .HK)
    HK_STOCK_PATTERN = r'^\d{5}\.HK$'

    # Crypto pattern (BASE/QUOTE)
    CRYPTO_PATTERN = r'^[A-Z]+/[A-Z]+$'

    # Futures pattern (product + month + @exchange)
    FUTURE_PATTERN = r'^[A-Z]+\d+@[A-Z]+$'

    # Option pattern
    OPTION_PATTERN = r'^\d+@[A-Z]+$'

    def __init__(
        self,
        config_overrides: Optional[Dict[str, SettlementRule]] = None,
        settlement_config: Optional[Dict] = None,
    ):
        """
        Initialize the settlement detector.

        Args:
            config_overrides: (Deprecated) Direct rule overrides
            settlement_config: Settlement configuration dict with:
                - mode: "auto" or "manual"
                - overrides: Dict[str, str] - pair -> settlement type mapping
                - default: Default settlement type ("t0", "t1", "t2")
        """
        self._rule_overrides = config_overrides or {}
        self._settlement_config = settlement_config or {}
        self._pair_overrides: Dict[str, str] = {}
        self._default_type: str = "t0"

        # Parse settlement config
        if settlement_config:
            self._pair_overrides = settlement_config.get("overrides", {})
            self._default_type = settlement_config.get("default", "t0")

    def detect_settlement_rule(
        self,
        pair: str,
        exchange: Optional[str] = None,
    ) -> SettlementRule:
        """
        Detect settlement rule for a trading pair.

        Priority order (mode: "auto", the default):
        1. Direct rule overrides (from constructor)
        2. Config pair overrides (from settlement.overrides)
        3. Auto-detection from pair format
        4. Exchange hint detection
        5. Default rule from config or T+0

        With mode: "manual" auto-detection is disabled entirely - only
        overrides apply, everything else falls back to the default rule.

        Args:
            pair: Trading pair
            exchange: Exchange name (optional, helps with detection)

        Returns:
            SettlementRule for the pair
        """
        pair_upper = pair.upper()

        # 1. Check direct rule overrides first (highest priority)
        if pair in self._rule_overrides:
            return self._rule_overrides[pair]

        # 2. Check config pair overrides
        if pair_upper in self._pair_overrides:
            override_type = self._pair_overrides[pair_upper].lower()
            return self._get_rule_by_type(override_type, pair_upper)

        # Check lowercase key as well
        if pair in self._pair_overrides:
            override_type = self._pair_overrides[pair].lower()
            return self._get_rule_by_type(override_type, pair_upper)

        # Manual mode: no auto-detection, everything unlisted uses default
        if self._settlement_config.get("mode", "auto") == "manual":
            return self._get_default_rule()

        # 3. Auto-detect from pair format
        rule = self._detect_from_pair(pair)
        if rule:
            return rule

        # 4. Use exchange hint if available
        if exchange:
            rule = self._detect_from_exchange(exchange)
            if rule:
                return rule

        # 5. Use default from config
        return self._get_default_rule()

    def _get_rule_by_type(self, settlement_type: str, pair: str) -> SettlementRule:
        """
        Get settlement rule by type string.

        Args:
            settlement_type: "t0", "t1", or "t2"
            pair: Pair name for logging

        Returns:
            SettlementRule for the type
        """
        type_map = {
            "t0": SETTLEMENT_RULES["crypto"],  # Use crypto rule for T+0
            "t1": SETTLEMENT_RULES["a_share"],
            "t2": SettlementRule(
                market_name="Custom T+2",
                settlement_type=SettlementType.T2,
                description="T+2 settlement (2 trading days)",
                settlement_days=2,
                skip_weekends=True,
                calendar_code="XSHG",
            ),
        }
        rule = type_map.get(settlement_type.lower())
        if rule is None:
            logger.warning(
                f"Unknown settlement type '{settlement_type}' for {pair}, "
                "falling back to T+0. Valid values: t0, t1, t2."
            )
            rule = SETTLEMENT_RULES["crypto"]
        return rule

    def _get_default_rule(self) -> SettlementRule:
        """Get the default settlement rule from config."""
        return self._get_rule_by_type(self._default_type, "default")

    def _detect_from_pair(self, pair: str) -> Optional[SettlementRule]:
        """Detect market type from pair format."""
        pair_upper = pair.upper()

        # Check crypto first (most common format)
        if re.match(self.CRYPTO_PATTERN, pair_upper):
            return SETTLEMENT_RULES["crypto"]

        # Check A-shares
        for pattern in self.A_SHARE_PATTERNS:
            if re.match(pattern, pair_upper):
                return SETTLEMENT_RULES["a_share"]

        # Check HK stocks
        if re.match(self.HK_STOCK_PATTERN, pair_upper):
            return SETTLEMENT_RULES["hk_stock"]

        # Check US stocks
        if re.match(self.US_STOCK_PATTERN, pair_upper):
            return SETTLEMENT_RULES["us_stock"]

        # Check futures
        if re.match(self.FUTURE_PATTERN, pair_upper):
            return SETTLEMENT_RULES["future"]

        # Check options
        if re.match(self.OPTION_PATTERN, pair_upper):
            return SETTLEMENT_RULES["option"]

        return None

    def _detect_from_exchange(self, exchange: str) -> Optional[SettlementRule]:
        """Detect market type from exchange name."""
        exchange_lower = exchange.lower()

        # Crypto exchanges
        crypto_exchanges = [
            "binance", "okx", "bybit", "gate", "kucoin",
            "coinbase", "kraken", "bitfinex", "huobi", "bitget",
        ]
        if any(ex in exchange_lower for ex in crypto_exchanges):
            return SETTLEMENT_RULES["crypto"]

        # A-share exchanges
        a_share_exchanges = ["xtp", "tora", "emt", "ost", "v5"]
        if any(ex in exchange_lower for ex in a_share_exchanges):
            return SETTLEMENT_RULES["a_share"]

        # US stock exchanges
        us_exchanges = ["ib", "alpaca", "robinhood", "td_ameritrade"]
        if any(ex in exchange_lower for ex in us_exchanges):
            return SETTLEMENT_RULES["us_stock"]

        return None

    def is_t1_market(self, pair: str, exchange: Optional[str] = None) -> bool:
        """
        Check if a pair requires T+1 settlement.

        Args:
            pair: Trading pair
            exchange: Exchange name (optional)

        Returns:
            True if T+1 applies
        """
        rule = self.detect_settlement_rule(pair, exchange)
        return rule.settlement_type == SettlementType.T1

    def get_settlement_date(
        self,
        open_date: datetime,
        pair: str,
        exchange: Optional[str] = None,
    ) -> datetime:
        """
        Calculate settlement date for a position.

        Args:
            open_date: Position open date
            pair: Trading pair
            exchange: Exchange name (optional)

        Returns:
            Settlement date (when position can be sold)
        """
        rule = self.detect_settlement_rule(pair, exchange)

        if rule.settlement_type == SettlementType.T0:
            # T+0: Can sell immediately
            return open_date

        settlement_session = None

        # Preferred path: use the exchange trading calendar (holidays aware)
        if rule.calendar_code:
            settlement_session = self._next_trading_sessions(
                open_date, rule.settlement_days, rule.calendar_code
            )

        if settlement_session is not None:
            settlement_dt = datetime.combine(
                settlement_session, datetime.min.time()
            ).replace(
                hour=rule.market_open_hour,
                minute=rule.market_open_minute,
                second=0,
                microsecond=0,
            )
            # Preserve the timezone of the open date so downstream
            # comparisons never mix naive and aware datetimes
            return settlement_dt.replace(tzinfo=open_date.tzinfo)

        # Fallback: weekend-skip only (no calendar available)
        settlement_date = open_date
        days_added = 0
        max_iterations = rule.settlement_days * 10 + 100  # Safeguard against infinite loops

        while days_added < rule.settlement_days:
            max_iterations -= 1
            if max_iterations <= 0:
                logger.warning(
                    f"Settlement date calculation exceeded max iterations for {pair}, "
                    "returning open_date + settlement_days"
                )
                return open_date + timedelta(days=rule.settlement_days)

            settlement_date += timedelta(days=1)

            # Skip weekends if configured
            if rule.skip_weekends:
                weekend_iterations = 0
                while settlement_date.weekday() >= 5:  # Saturday=5, Sunday=6
                    settlement_date += timedelta(days=1)
                    weekend_iterations += 1
                    if weekend_iterations > 100:  # Safeguard
                        logger.warning(
                            f"Weekend skip exceeded max iterations for {pair}"
                        )
                        break

            days_added += 1

        # Set to market open time
        try:
            settlement_date = settlement_date.replace(
                hour=rule.market_open_hour,
                minute=rule.market_open_minute,
                second=0,
                microsecond=0,
            )
        except ValueError as e:
            logger.warning(f"Error setting market open time: {e}")
            # Return date without time adjustment
            return settlement_date

        return settlement_date.replace(tzinfo=open_date.tzinfo)

    @staticmethod
    def _next_trading_sessions(
        open_date: datetime, num_days: int, calendar_code: str
    ) -> Optional[datetime]:
        """
        Get the Nth trading session strictly after open_date using exchange_calendars.

        Args:
            open_date: Position open date
            num_days: Number of trading sessions to advance (T+N)
            calendar_code: Calendar code (e.g. "XSHG")

        Returns:
            The Nth next session date, or None if exchange_calendars is unavailable.
        """
        try:
            import pandas as pd
            from exchange_calendars import get_calendar  # noqa: F401 (availability probe)
        except ImportError:
            logger.debug("exchange_calendars not installed; falling back to weekend-skip")
            return None

        try:
            calendar = _get_cached_calendar(calendar_code)
            first = pd.Timestamp(open_date.date()) + pd.Timedelta(days=1)
            horizon = first + pd.Timedelta(days=num_days * 30 + 40)
            sessions = calendar.sessions_in_range(first, horizon)
            nth_session = sessions[num_days - 1]
            return nth_session.date()
        except Exception as e:
            logger.warning(f"Trading calendar lookup failed ({calendar_code}): {e}")
            return None


# Global instance for convenience
_detector = SettlementDetector()

# Cache for exchange_calendars instances (loading a calendar is expensive)
_calendar_cache: Dict = {}


def _get_cached_calendar(calendar_code: str):
    """Get an exchange_calendars calendar instance (cached)."""
    if calendar_code not in _calendar_cache:
        from exchange_calendars import get_calendar
        _calendar_cache[calendar_code] = get_calendar(calendar_code)
    return _calendar_cache[calendar_code]


def init_settlement_detector(config: Optional[Dict] = None) -> None:
    """
    Initialize the global settlement detector with configuration.

    Args:
        config: Settlement configuration dict with:
            - mode: "auto" or "manual"
            - overrides: Dict[str, str] - pair -> settlement type mapping
            - default: Default settlement type ("t0", "t1", "t2")

    Example:
        from bullseye.configuration import Config
        config = Config("config.yaml")
        init_settlement_detector(config.settlement)
    """
    global _detector
    _detector = SettlementDetector(settlement_config=config)


def detect_settlement_rule(pair: str, exchange: Optional[str] = None) -> SettlementRule:
    """Convenience function to detect settlement rule."""
    return _detector.detect_settlement_rule(pair, exchange)


def is_t1_market(pair: str, exchange: Optional[str] = None) -> bool:
    """Convenience function to check if T+1 applies."""
    return _detector.is_t1_market(pair, exchange)


def get_settlement_date(
    open_date: datetime,
    pair: str,
    exchange: Optional[str] = None,
) -> datetime:
    """Convenience function to calculate settlement date."""
    return _detector.get_settlement_date(open_date, pair, exchange)
