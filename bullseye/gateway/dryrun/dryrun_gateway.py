"""
DryRun Gateway - Simulated trading gateway for paper trading.

This gateway simulates order execution without connecting to a real exchange.
It uses a real gateway (like CCXT) for fetching market data but simulates
all order operations.
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from bullseye.gateway.base import BaseGateway
from bullseye.trader.eventengine import EventEngine
from bullseye.trader.object.account import AccountData
from bullseye.trader.object.contract import ContractData
from bullseye.trader.object.kline import KlineData
from bullseye.trader.object.order import OrderData, OrderType, Direction, Status
from bullseye.trader.object.position import PositionData
from bullseye.trader.object.tick import TickData
from bullseye.trader.object.orderbook import OrderBookData
from bullseye.trader.object.trade import TradeData

logger = logging.getLogger(__name__)


class DryRunGateway(BaseGateway):
    """
    DryRun Gateway for paper trading.

    This gateway simulates all trading operations while optionally
    using a real gateway for market data. Perfect for testing
    strategies without risking real money.

    Features:
    - Simulated order execution (instant fill for market orders)
    - Virtual account balance tracking
    - Real market data from underlying gateway
    - Trade history logging
    """

    def __init__(
        self,
        event_engine: EventEngine,
        real_gateway: Optional[BaseGateway] = None,
        initial_balance: float = 1000.0,
        stake_currency: str = "USDT",
    ):
        """
        Initialize the DryRun Gateway.

        Args:
            event_engine: Event engine for publishing events
            real_gateway: Optional real gateway for fetching market data
            initial_balance: Starting balance for simulation
            stake_currency: Currency for balance (e.g., USDT)
        """
        super().__init__(event_engine, "DRYRUN")

        self._real_gateway = real_gateway
        self._initial_balance = initial_balance
        self._stake_currency = stake_currency

        # Virtual account state
        self._balance = initial_balance
        self._available = initial_balance
        self._frozen = 0.0  # Amount locked in pending orders

        # Virtual positions: symbol -> PositionData
        self._positions: Dict[str, PositionData] = {}

        # Order tracking
        self._orders: Dict[str, OrderData] = {}
        self._trades: List[TradeData] = []
        self._trade_count = 0

        # Connection state
        self._connected = False

        # Current prices cache: symbol -> price
        self._current_prices: Dict[str, float] = {}

    # ==================== Connection ====================

    def connect(self, **kwargs) -> bool:
        """
        Simulate connection.

        In dry-run mode, this just initializes the virtual account.
        """
        self._connected = True
        self.on_log(f"DryRun Gateway connected. Initial balance: {self._balance} {self._stake_currency}")
        logger.info(f"DryRun Gateway started with balance: {self._balance}")

        # Publish initial account state
        self._publish_account()

        return True

    def close(self) -> None:
        """Close the gateway."""
        self._connected = False
        self.on_log("DryRun Gateway disconnected")
        logger.info("DryRun Gateway closed")

    # ==================== Order Operations ====================

    def send_order(self, req: Dict[str, Any]) -> Optional[str]:
        """
        Send a simulated order.

        In dry-run mode, market orders are filled immediately at current price,
        and limit orders are tracked but never filled (simplified simulation).

        Args:
            req: Order request dictionary with keys:
                - symbol: Trading pair
                - direction: Direction.LONG or Direction.SHORT
                - order_type: OrderType.MARKET or OrderType.LIMIT
                - volume: Order amount
                - price: Limit price (for limit orders)

        Returns:
            Order ID if successful, None otherwise
        """
        if not self._connected:
            self.on_log("Gateway not connected")
            return None

        # Generate order ID
        order_id = f"dry_{uuid.uuid4().hex[:8]}"

        symbol = req.get("symbol", "")
        direction = req.get("direction", Direction.LONG)
        order_type = req.get("order_type", OrderType.MARKET)
        volume = req.get("volume", 0)
        price = req.get("price", 0)

        # Get current price for market orders
        if order_type == OrderType.MARKET:
            current_price = self._current_prices.get(symbol, price)
            if current_price <= 0:
                self.on_log(f"No price available for {symbol}")
                return None
            price = current_price

        # Create order
        order = OrderData(
            gateway_name=self.gateway_name,
            orderid=order_id,
            symbol=symbol,
            exchange="DRYRUN",
            type=order_type,
            direction=direction,
            price=price,
            volume=volume,
            traded=0,
            status=Status.NOTTRADED,
            datetime=datetime.now(),
        )

        # Store order
        self._orders[order_id] = order

        # For market orders, simulate immediate fill
        if order_type == OrderType.MARKET:
            self._fill_order(order, price)
        else:
            # For limit orders, just publish the order event
            self.on_order(order)

        return order_id

    def cancel_order(self, req: Dict[str, Any]) -> bool:
        """
        Cancel a pending order.

        Args:
            req: Request with order_id

        Returns:
            True if cancelled successfully
        """
        order_id = req.get("order_id", "")
        order = self._orders.get(order_id)

        if not order:
            return False

        if order.status in [Status.ALLTRADED, Status.CANCELLED]:
            return False

        # Cancel the order
        order.status = Status.CANCELLED
        self.on_order(order)

        # Release frozen amount if any
        if order.frozen > 0:
            self._frozen -= order.frozen
            self._available += order.frozen
            self._publish_account()

        return True

    def _fill_order(self, order: OrderData, fill_price: float) -> None:
        """
        Fill an order (simulate execution).

        Args:
            order: Order to fill
            fill_price: Execution price
        """
        # Calculate trade value
        trade_value = order.volume * fill_price
        fee = trade_value * 0.001  # 0.1% fee

        # Update order status
        order.traded = order.volume
        order.status = Status.ALLTRADED

        # Update balance based on direction
        if order.direction == Direction.LONG:
            # Buying - deduct from balance
            total_cost = trade_value + fee
            self._balance -= total_cost
            self._available -= total_cost

            # Update position
            self._update_position(
                symbol=order.symbol,
                direction=Direction.LONG,
                volume=order.volume,
                price=fill_price,
            )
        else:
            # Selling - add to balance
            total_value = trade_value - fee
            self._balance += total_value
            self._available += total_value

            # Update position
            self._update_position(
                symbol=order.symbol,
                direction=Direction.SHORT,
                volume=order.volume,
                price=fill_price,
            )

        # Create trade record
        self._trade_count += 1
        trade = TradeData(
            gateway_name=self.gateway_name,
            tradeid=f"dry_trade_{self._trade_count}",
            orderid=order.orderid,
            symbol=order.symbol,
            exchange="DRYRUN",
            direction=order.direction,
            price=fill_price,
            volume=order.volume,
            datetime=datetime.now(),
            commission=fee,
        )
        self._trades.append(trade)

        # Publish events
        self.on_order(order)
        self.on_trade(trade)
        self._publish_account()
        self._publish_position(order.symbol)

        logger.info(
            f"DryRun order filled: {order.symbol} {order.direction.value} "
            f"{order.volume}@{fill_price}, fee={fee:.4f}"
        )

    def _update_position(
        self,
        symbol: str,
        direction: Direction,
        volume: float,
        price: float,
    ) -> None:
        """Update virtual position."""
        if symbol not in self._positions:
            self._positions[symbol] = PositionData(
                gateway_name=self.gateway_name,
                symbol=symbol,
                exchange="DRYRUN",
                direction=direction,
                volume=0,
                price=0,
                pnl=0,
                available=0,
            )

        pos = self._positions[symbol]

        if direction == Direction.LONG:
            # Calculate new average price
            total_volume = pos.volume + volume
            if total_volume > 0:
                pos.price = (pos.price * pos.volume + price * volume) / total_volume
            pos.volume = total_volume
            pos.available = pos.volume
        else:
            # Selling reduces position
            pos.volume = max(0, pos.volume - volume)
            pos.available = pos.volume

        # Remove if position is closed
        if pos.volume <= 0:
            del self._positions[symbol]

    # ==================== Query Operations ====================

    def query_account(self) -> AccountData:
        """Query virtual account."""
        account = AccountData(
            gateway_name=self.gateway_name,
            accountid="DRYRUN_ACCOUNT",
            balance=self._balance,
            available=self._available,
            frozen=self._frozen,
            currency=self._stake_currency,
        )
        self.on_account(account)
        return account

    def query_position(self) -> List[PositionData]:
        """Query virtual positions."""
        positions = list(self._positions.values())
        for pos in positions:
            self.on_position(pos)
        return positions

    def query_order(self, req: Dict[str, Any]) -> List[OrderData]:
        """Query orders."""
        return list(self._orders.values())

    def query_contract(self) -> List[ContractData]:
        """Query contracts (not implemented for dry-run)."""
        return []

    # ==================== Market Data ====================

    def subscribe_quote(self, symbols: List[str]) -> None:
        """
        Subscribe to market data.

        For dry-run, this delegates to the real gateway if available.
        """
        if self._real_gateway:
            self._real_gateway.subscribe_quote(symbols)

    def unsubscribe_quote(self, symbols: List[str]) -> None:
        """Unsubscribe from market data."""
        if self._real_gateway:
            self._real_gateway.unsubscribe_quote(symbols)

    def get_bars(
        self,
        symbol: str,
        interval: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[KlineData]:
        """
        Get historical K-line data.

        Delegates to real gateway for actual data.
        """
        if self._real_gateway:
            klines = self._real_gateway.get_bars(
                symbol=symbol,
                interval=interval,
                start=start,
                end=end,
                limit=limit,
            )

            # Update current price cache
            if klines:
                self._current_prices[symbol] = klines[-1].close_price

            return klines

        return []

    def get_tick(self, symbol: str) -> Optional[TickData]:
        """
        Get current tick data.

        Delegates to real gateway if available.
        """
        if self._real_gateway:
            tick = self._real_gateway.get_tick(symbol)
            if tick:
                self._current_prices[symbol] = tick.last_price
            return tick

        return None

    def get_order_book(self, symbol: str, limit: int = 20) -> Optional[OrderBookData]:
        """
        Get order book snapshot.

        Delegates to real gateway if available.
        """
        if self._real_gateway:
            return self._real_gateway.get_order_book(symbol, limit)

        return None

    # ==================== Event Publishing ====================

    def _publish_account(self) -> None:
        """Publish account update event."""
        account = AccountData(
            gateway_name=self.gateway_name,
            accountid="DRYRUN_ACCOUNT",
            balance=self._balance,
            available=self._available,
            frozen=self._frozen,
            currency=self._stake_currency,
        )
        self.on_account(account)

    def _publish_position(self, symbol: str) -> None:
        """Publish position update event."""
        if symbol in self._positions:
            self.on_position(self._positions[symbol])

    # ==================== Utility ====================

    def get_balance(self) -> float:
        """Get current balance."""
        return self._balance

    def get_available(self) -> float:
        """Get available balance."""
        return self._available

    def get_trade_history(self) -> List[TradeData]:
        """Get all simulated trades."""
        return self._trades.copy()

    def update_current_price(self, symbol: str, price: float) -> None:
        """
        Update current price for a symbol.

        This should be called when new market data is received.

        Args:
            symbol: Trading pair
            price: Current price
        """
        self._current_prices[symbol] = price

    def reset(self, initial_balance: Optional[float] = None) -> None:
        """
        Reset the gateway to initial state.

        Args:
            initial_balance: New initial balance (optional)
        """
        self._balance = initial_balance or self._initial_balance
        self._available = self._balance
        self._frozen = 0.0
        self._positions.clear()
        self._orders.clear()
        self._trades.clear()
        self._trade_count = 0
        self._current_prices.clear()

        self._publish_account()
        logger.info(f"DryRun Gateway reset with balance: {self._balance}")
