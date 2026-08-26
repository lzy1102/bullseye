"""
Main Engine - Core trading engine
Manages all gateways and routes events
"""
from typing import Dict, List, Optional, Type, Any, TYPE_CHECKING
import logging

from .eventengine import EventEngine, EventType
from .object import (
    ContractData, TickData, OrderData, TradeData,
    PositionData, AccountData
)

if TYPE_CHECKING:
    from bullseye.gateway.base import BaseGateway

logger = logging.getLogger(__name__)


class MainEngine:
    """
    Main Engine

    Responsible for:
    1. Managing all gateways
    2. Routing events to appropriate handlers
    3. Providing unified trading interface
    """

    def __init__(self, event_engine: Optional[EventEngine] = None):
        """Initialize main engine"""
        self.event_engine = event_engine or EventEngine()
        self.event_engine.start()

        self._gateways: Dict[str, "BaseGateway"] = {}
        self._contracts: Dict[str, ContractData] = {}
        self._ticks: Dict[str, TickData] = {}
        self._orders: Dict[str, OrderData] = {}
        self._trades: Dict[str, TradeData] = {}
        self._positions: Dict[str, PositionData] = {}
        self._accounts: Dict[str, AccountData] = {}

        self._gateway_classes: Dict[str, Type["BaseGateway"]] = {}

        # Register event handlers
        self._register_event_handlers()

    def _register_event_handlers(self):
        """Register event handlers"""
        self.event_engine.subscribe(EventType.EVENT_CONTRACT, self._on_contract)
        self.event_engine.subscribe(EventType.EVENT_TICK, self._on_tick)
        self.event_engine.subscribe(EventType.EVENT_ORDER, self._on_order)
        self.event_engine.subscribe(EventType.EVENT_TRADE, self._on_trade)
        self.event_engine.subscribe(EventType.EVENT_POSITION, self._on_position)
        self.event_engine.subscribe(EventType.EVENT_ACCOUNT, self._on_account)

    def add_gateway_class(self, gateway_class: Type["BaseGateway"], gateway_name: str):
        """
        Add gateway class

        Args:
            gateway_class: Gateway class
            gateway_name: Gateway name
        """
        self._gateway_classes[gateway_name] = gateway_class
        logger.info(f"Added gateway class: {gateway_name}")

    def connect(self, gateway_name: str, setting: Dict[str, Any]) -> bool:
        """
        Connect to gateway

        Args:
            gateway_name: Gateway name
            setting: Connection parameters

        Returns:
            True if successful, False otherwise
        """
        if gateway_name in self._gateways:
            logger.warning(f"Gateway {gateway_name} already connected")
            return True

        gateway_class = self._gateway_classes.get(gateway_name)
        if gateway_class is None:
            logger.error(f"Gateway class not found: {gateway_name}")
            return False

        try:
            gateway = gateway_class(self.event_engine)
            gateway.connect(**setting)
            self._gateways[gateway_name] = gateway
            logger.info(f"Connected to gateway: {gateway_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect {gateway_name}: {e}", exc_info=True)
            return False

    def close(self, gateway_name: str):
        """
        Close gateway connection

        Args:
            gateway_name: Gateway name
        """
        if gateway_name in self._gateways:
            self._gateways[gateway_name].close()
            del self._gateways[gateway_name]
            logger.info(f"Closed gateway: {gateway_name}")

    def send_order(self, req: Dict[str, Any], gateway_name: str) -> Optional[str]:
        """
        Send order

        Args:
            req: Order request
            gateway_name: Gateway name

        Returns:
            Order ID if successful, None otherwise
        """
        gateway = self._gateways.get(gateway_name)
        if gateway is None:
            logger.error(f"Gateway not found: {gateway_name}")
            return None

        try:
            orderid = gateway.send_order(req)
            logger.info(f"Order sent: {orderid} via {gateway_name}")
            return orderid
        except Exception as e:
            logger.error(f"Failed to send order: {e}", exc_info=True)
            return None

    def cancel_order(self, req: Dict[str, Any], gateway_name: str) -> bool:
        """
        Cancel order

        Args:
            req: Cancel request
            gateway_name: Gateway name

        Returns:
            True if successful, False otherwise
        """
        gateway = self._gateways.get(gateway_name)
        if gateway is None:
            logger.error(f"Gateway not found: {gateway_name}")
            return False

        try:
            result = gateway.cancel_order(req)
            logger.info(f"Order cancelled: {req.get('orderid')} via {gateway_name}")
            return result
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}", exc_info=True)
            return False

    def get_contracts(self, gateway_name: str = "") -> List[ContractData]:
        """
        Get contracts

        Args:
            gateway_name: Gateway name, empty for all

        Returns:
            List of contracts
        """
        if gateway_name:
            return [c for c in self._contracts.values() if c.gateway_name == gateway_name]
        return list(self._contracts.values())

    def get_ticks(self, symbol: str = "") -> Dict[str, TickData]:
        """
        Get tick cache

        Args:
            symbol: Symbol filter

        Returns:
            Dictionary of ticks
        """
        if symbol:
            return {k: v for k, v in self._ticks.items() if k.startswith(symbol)}
        return self._ticks.copy()

    def get_orders(self, gateway_name: str = "") -> Dict[str, OrderData]:
        """
        Get order cache

        Args:
            gateway_name: Gateway name filter

        Returns:
            Dictionary of orders
        """
        if gateway_name:
            return {k: v for k, v in self._orders.items() if v.gateway_name == gateway_name}
        return self._orders.copy()

    def get_positions(self, gateway_name: str = "") -> Dict[str, PositionData]:
        """
        Get position cache

        Args:
            gateway_name: Gateway name filter

        Returns:
            Dictionary of positions
        """
        if gateway_name:
            return {k: v for k, v in self._positions.items() if v.gateway_name == gateway_name}
        return self._positions.copy()

    def get_accounts(self, gateway_name: str = "") -> Dict[str, AccountData]:
        """
        Get account cache

        Args:
            gateway_name: Gateway name filter

        Returns:
            Dictionary of accounts
        """
        if gateway_name:
            return {k: v for k, v in self._accounts.items() if v.gateway_name == gateway_name}
        return self._accounts.copy()

    # ==================== Event Handlers ====================

    def _on_contract(self, event):
        """Handle contract event"""
        contract = event.data
        if contract:
            self._contracts[contract.symbol] = contract

    def _on_tick(self, event):
        """Handle tick event"""
        tick = event.data
        if tick:
            self._ticks[tick.symbol] = tick

    def _on_order(self, event):
        """Handle order event"""
        order = event.data
        if order:
            self._orders[order.orderid] = order

    def _on_trade(self, event):
        """Handle trade event"""
        trade = event.data
        if trade:
            self._trades[trade.tradeid] = trade

    def _on_position(self, event):
        """Handle position event"""
        position = event.data
        if position:
            key = f"{position.gateway_name}.{position.symbol}.{position.direction.value if position.direction else ''}"
            self._positions[key] = position

    def _on_account(self, event):
        """Handle account event"""
        account = event.data
        if account:
            self._accounts[account.accountid] = account

    def stop(self):
        """Stop engine"""
        self.event_engine.stop()
        logger.info("Main engine stopped")

    @property
    def gateways(self) -> List[str]:
        """Get list of connected gateway names"""
        return list(self._gateways.keys())

    @property
    def is_active(self) -> bool:
        """Check if event engine is active"""
        return self.event_engine.is_active
