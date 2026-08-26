"""
Bullseye Exception Hierarchy

Provides a structured exception hierarchy for the Bullseye framework,
making it easier to handle specific error cases and provide meaningful
error messages to users.
"""


class BullseyeError(Exception):
    """Base exception for all Bullseye errors."""

    def __init__(self, message: str = "", details: str = ""):
        self.message = message
        self.details = details
        super().__init__(message)


class ConfigurationError(BullseyeError):
    """Raised when there is a configuration error."""

    def __init__(self, message: str = "Configuration error", details: str = ""):
        super().__init__(message, details)


class StrategyError(BullseyeError):
    """Raised when there is a strategy-related error."""

    def __init__(self, message: str = "Strategy error", details: str = ""):
        super().__init__(message, details)


class StrategyLoadError(StrategyError):
    """Raised when a strategy cannot be loaded."""

    def __init__(self, strategy_name: str, reason: str = ""):
        msg = f"Failed to load strategy '{strategy_name}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.strategy_name = strategy_name


class StrategyValidationError(StrategyError):
    """Raised when a strategy fails validation."""

    def __init__(self, strategy_name: str, errors: list = None):
        errors = errors or []
        msg = f"Strategy '{strategy_name}' validation failed"
        if errors:
            msg += f": {'; '.join(str(e) for e in errors)}"
        super().__init__(msg)
        self.strategy_name = strategy_name
        self.validation_errors = errors


class DataError(BullseyeError):
    """Raised when there is a data-related error."""

    def __init__(self, message: str = "Data error", details: str = ""):
        super().__init__(message, details)


class DataNotFoundError(DataError):
    """Raised when requested data is not found."""

    def __init__(self, pair: str, timeframe: str = "", timerange: str = ""):
        msg = f"Data not found for '{pair}'"
        if timeframe:
            msg += f" ({timeframe})"
        if timerange:
            msg += f" [{timerange}]"
        super().__init__(msg)
        self.pair = pair
        self.timeframe = timeframe
        self.timerange = timerange


class DataFormatError(DataError):
    """Raised when data format is invalid."""

    def __init__(self, message: str = "Invalid data format", details: str = ""):
        super().__init__(message, details)


class GatewayError(BullseyeError):
    """Raised when there is a gateway/exchange error."""

    def __init__(self, message: str = "Gateway error", details: str = ""):
        super().__init__(message, details)


class GatewayConnectionError(GatewayError):
    """Raised when a gateway cannot connect to the exchange."""

    def __init__(self, exchange: str, reason: str = ""):
        msg = f"Failed to connect to '{exchange}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.exchange = exchange


class GatewayAuthenticationError(GatewayError):
    """Raised when authentication with the exchange fails."""

    def __init__(self, exchange: str, reason: str = ""):
        msg = f"Authentication failed for '{exchange}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.exchange = exchange


class GatewayRateLimitError(GatewayError):
    """Raised when the exchange rate limit is exceeded."""

    def __init__(self, exchange: str, retry_after: int = 0):
        msg = f"Rate limit exceeded for '{exchange}'"
        if retry_after > 0:
            msg += f" (retry after {retry_after}s)"
        super().__init__(msg)
        self.exchange = exchange
        self.retry_after = retry_after


class OrderError(BullseyeError):
    """Raised when there is an order-related error."""

    def __init__(self, message: str = "Order error", details: str = ""):
        super().__init__(message, details)


class InsufficientFundsError(OrderError):
    """Raised when there are insufficient funds for an order."""

    def __init__(self, required: float = 0, available: float = 0, currency: str = ""):
        msg = "Insufficient funds"
        if currency:
            msg += f" ({currency})"
        msg += f": required {required}, available {available}"
        super().__init__(msg)
        self.required = required
        self.available = available
        self.currency = currency


class OrderExecutionError(OrderError):
    """Raised when an order fails to execute."""

    def __init__(self, order_id: str = "", reason: str = ""):
        msg = "Order execution failed"
        if order_id:
            msg += f" (order: {order_id})"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.order_id = order_id


class PositionError(BullseyeError):
    """Raised when there is a position-related error."""

    def __init__(self, message: str = "Position error", details: str = ""):
        super().__init__(message, details)


class BacktestError(BullseyeError):
    """Raised when there is a backtesting error."""

    def __init__(self, message: str = "Backtest error", details: str = ""):
        super().__init__(message, details)


class HyperoptError(BullseyeError):
    """Raised when there is a hyperopt error."""

    def __init__(self, message: str = "Hyperopt error", details: str = ""):
        super().__init__(message, details)


class WalletError(BullseyeError):
    """Raised when there is a wallet-related error."""

    def __init__(self, message: str = "Wallet error", details: str = ""):
        super().__init__(message, details)


class PersistenceError(BullseyeError):
    """Raised when there is a database/persistence error."""

    def __init__(self, message: str = "Persistence error", details: str = ""):
        super().__init__(message, details)
