"""
Gateway Base Module - Abstract base class for all trading gateways

All trading gateways (crypto, stock, futures) must implement this interface.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import logging

from ..trader.eventengine import EventEngine, EventType
from ..trader.object import (
    ContractData, TickData, OrderData, TradeData,
    PositionData, AccountData, KlineData, OrderBookData
)

logger = logging.getLogger(__name__)


class GatewayType:
    """Gateway type constants"""
    CRYPTO = "crypto"
    STOCK = "stock"
    FUTURE = "future"
    OPTION = "option"
    INDEX = "index"


class BaseGateway(ABC):
    """
    Gateway Abstract Base Class

    All trading gateways must implement this interface to provide
    unified trading functionality across different markets.
    """

    def __init__(self, event_engine: EventEngine, gateway_name: str = ""):
        """
        Initialize gateway

        Args:
            event_engine: Event engine for publishing events
            gateway_name: Gateway name identifier
        """
        self.event_engine = event_engine
        self.gateway_name = gateway_name or self.__class__.__name__
        self._connected: bool = False
        self._callbacks: Dict = {}

    # ==================== Abstract Methods (Must Implement) ====================

    @abstractmethod
    def connect(self, **kwargs):
        """
        Connect to exchange/broker

        Args:
            **kwargs: Connection parameters (e.g., userid, password, api_key, etc.)
        """
        pass

    @abstractmethod
    def close(self):
        """Disconnect from exchange/broker"""
        pass

    @abstractmethod
    def send_order(self, req: Dict[str, Any]) -> str:
        """
        Send order

        Args:
            req: Order request containing:
                - symbol: Trading symbol
                - direction: Direction (LONG/SHORT)
                - offset: Offset (OPEN/CLOSE) - for futures
                - order_type: OrderType
                - price: Order price
                - volume: Order volume
                - reference: Strategy reference (optional)

        Returns:
            Order ID string
        """
        pass

    @abstractmethod
    def cancel_order(self, req: Dict[str, Any]) -> bool:
        """
        Cancel order

        Args:
            req: Cancel request containing:
                - orderid: Order ID to cancel
                - symbol: Trading symbol

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    def query_account(self) -> Optional[AccountData]:
        """
        Query account information

        Returns:
            AccountData object or None
        """
        pass

    @abstractmethod
    def query_position(self) -> List[PositionData]:
        """
        Query position information

        Returns:
            List of PositionData objects
        """
        pass

    @abstractmethod
    def query_order(self, req: Dict[str, Any]) -> Optional[OrderData]:
        """
        Query order status

        Args:
            req: Query request containing orderid

        Returns:
            OrderData object or None
        """
        pass

    @abstractmethod
    def query_contract(self) -> List[ContractData]:
        """
        Query available contracts/instruments

        Returns:
            List of ContractData objects
        """
        pass

    # ==================== Optional Methods ====================

    def subscribe_quote(self, symbols: List[str]):
        """
        Subscribe to market data

        Args:
            symbols: List of symbols to subscribe
        """
        pass

    def unsubscribe_quote(self, symbols: List[str]):
        """
        Unsubscribe from market data

        Args:
            symbols: List of symbols to unsubscribe
        """
        pass

    def get_bars(
        self,
        symbol: str,
        interval: str,
        start: Optional[Any] = None,
        end: Optional[Any] = None,
        limit: int = 1000
    ) -> List[KlineData]:
        """
        Get historical K-line data

        Args:
            symbol: Trading symbol
            interval: Timeframe (1m, 5m, 15m, 1h, 4h, 1d, etc.)
            start: Start time (datetime or timestamp)
            end: End time (datetime or timestamp)
            limit: Maximum number of bars

        Returns:
            List of KlineData objects
        """
        return []

    def get_tick(self, symbol: str) -> Optional[TickData]:
        """
        Get latest tick data

        Args:
            symbol: Trading symbol

        Returns:
            TickData object or None
        """
        return None

    def get_order_book(self, symbol: str, limit: int = 20) -> Optional[OrderBookData]:
        """
        Get order book snapshot

        Args:
            symbol: Trading symbol
            limit: Number of price levels per side

        Returns:
            OrderBookData object or None
        """
        return None

    # ==================== Event Publishing ====================

    def on_tick(self, tick: TickData):
        """Publish tick event"""
        tick.gateway_name = self.gateway_name
        self.event_engine.publish(EventType.EVENT_TICK, tick, self.gateway_name)

    def on_order(self, order: OrderData):
        """Publish order event"""
        order.gateway_name = self.gateway_name
        self.event_engine.publish(EventType.EVENT_ORDER, order, self.gateway_name)

    def on_trade(self, trade: TradeData):
        """Publish trade event"""
        trade.gateway_name = self.gateway_name
        self.event_engine.publish(EventType.EVENT_TRADE, trade, self.gateway_name)

    def on_position(self, position: PositionData):
        """Publish position event"""
        position.gateway_name = self.gateway_name
        self.event_engine.publish(EventType.EVENT_POSITION, position, self.gateway_name)

    def on_account(self, account: AccountData):
        """Publish account event"""
        account.gateway_name = self.gateway_name
        self.event_engine.publish(EventType.EVENT_ACCOUNT, account, self.gateway_name)

    def on_contract(self, contract: ContractData):
        """Publish contract event"""
        contract.gateway_name = self.gateway_name
        self.event_engine.publish(EventType.EVENT_CONTRACT, contract, self.gateway_name)

    def on_orderbook(self, orderbook: OrderBookData):
        """Publish order book event"""
        orderbook.gateway_name = self.gateway_name
        self.event_engine.publish(EventType.EVENT_ORDERBOOK, orderbook, self.gateway_name)

    def on_log(self, log: str):
        """Publish log event"""
        self.event_engine.publish(EventType.EVENT_LOG, log, self.gateway_name)

    # ==================== Properties ====================

    @property
    def connected(self) -> bool:
        """Check if gateway is connected"""
        return self._connected

    @property
    def gateway_type(self) -> str:
        """Get gateway type"""
        return GatewayType.CRYPTO  # Default, should be overridden
