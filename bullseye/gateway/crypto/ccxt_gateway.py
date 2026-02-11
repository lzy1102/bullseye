"""
CCXT Gateway - Cryptocurrency trading gateway using CCXT library

Supports all CCXT-compatible exchanges: Binance, OKX, Bybit, Gate.io, etc.
"""
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import logging

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False

from ..base import BaseGateway, GatewayType
from ...trader.eventengine import EventType
from ...trader.object import (
    ContractData, TickData, OrderData, TradeData,
    PositionData, AccountData, KlineData,
    OrderType, Direction, Status, ProductClass
)

logger = logging.getLogger(__name__)


class CcxtGateway(BaseGateway):
    """
    CCXT Cryptocurrency Gateway

    Supports all CCXT-compatible cryptocurrency exchanges.
    Provides unified interface for spot, margin, and futures trading.
    """

    def __init__(self, event_engine, exchange_name: str = "binance"):
        """
        Initialize CCXT gateway

        Args:
            event_engine: Event engine
            exchange_name: CCXT exchange name (binance, okx, bybit, etc.)
        """
        super().__init__(event_engine, exchange_name)
        self._exchange = None
        self._exchange_name = exchange_name.lower()
        self._polling_interval: float = 1.0

    def connect(
        self,
        api_key: str = "",
        secret: str = "",
        passphrase: str = "",
        sandbox: bool = False,
        options: Dict = None
    ):
        """
        Connect to exchange

        Args:
            api_key: API key
            secret: API secret
            passphrase: API passphrase (for some exchanges like OKX)
            sandbox: Use sandbox/testnet
            options: Additional CCXT options
        """
        if not CCXT_AVAILABLE:
            raise ImportError("Please install ccxt: pip install ccxt")

        try:
            exchange_class = getattr(ccxt, self._exchange_name)

            config = {
                'apiKey': api_key,
                'secret': secret,
                'enableRateLimit': True,
            }

            if passphrase:
                config['password'] = passphrase

            if sandbox:
                config['sandbox'] = True

            if options:
                config['options'] = options

            self._exchange = exchange_class(config)
            self._exchange.load_markets()

            self._connected = True
            self.event_engine.publish(EventType.EVENT_GATEWAY_CONNECT, None, self.gateway_name)
            logger.info(f"{self.gateway_name} connected successfully")

        except Exception as e:
            logger.error(f"{self.gateway_name} connection failed: {e}", exc_info=True)
            raise

    def close(self):
        """Close connection"""
        if self._exchange:
            self._exchange.close()
        self._connected = False
        self.event_engine.publish(EventType.EVENT_GATEWAY_DISCONNECT, None, self.gateway_name)
        logger.info(f"{self.gateway_name} disconnected")

    def send_order(self, req: Dict[str, Any]) -> str:
        """
        Send order

        Args:
            req: Order request
                - symbol: Trading pair (e.g., BTC/USDT)
                - direction: Direction (LONG/SHORT)
                - order_type: OrderType
                - price: Price
                - volume: Volume
        """
        side = "buy" if req["direction"] == Direction.LONG else "sell"

        try:
            if req["order_type"] == OrderType.MARKET:
                order = self._exchange.create_market_order(
                    req["symbol"], side, req["volume"]
                )
            else:
                order = self._exchange.create_limit_order(
                    req["symbol"], side, req["volume"], req["price"]
                )

            orderid = str(order.get("id", ""))
            logger.info(f"Order sent: {orderid} on {self.gateway_name}")

            # Publish order event
            order_data = self._to_order_data(order)
            self.on_order(order_data)

            return orderid

        except Exception as e:
            logger.error(f"Failed to send order: {e}", exc_info=True)
            return ""

    def cancel_order(self, req: Dict[str, Any]) -> bool:
        """Cancel order"""
        try:
            self._exchange.cancel_order(req["orderid"], req.get("symbol", ""))
            logger.info(f"Order cancelled: {req['orderid']}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return False

    def query_account(self) -> Optional[AccountData]:
        """Query account"""
        try:
            balance = self._exchange.fetch_balance()

            # Get USDT balance (or first available currency)
            currency = "USDT"
            if currency not in balance:
                currency = list(balance.keys())[0]

            currency_balance = balance.get(currency, {})

            account = AccountData(
                gateway_name=self.gateway_name,
                accountid=self._exchange.api_key or "",
                balance=currency_balance.get("total", 0.0),
                available=currency_balance.get("free", 0.0),
                frozen=currency_balance.get("used", 0.0),
                currency=currency
            )

            self.on_account(account)
            return account

        except Exception as e:
            logger.error(f"Failed to query account: {e}")
            return None

    def query_position(self) -> List[PositionData]:
        """Query positions (for futures/margin)"""
        try:
            if not hasattr(self._exchange, 'fetch_positions'):
                return []

            positions = self._exchange.fetch_positions()
            result = []

            for pos in positions:
                if float(pos.get("contracts", 0)) == 0:
                    continue

                position = PositionData(
                    gateway_name=self.gateway_name,
                    symbol=pos.get("symbol", ""),
                    exchange=self.gateway_name,
                    direction=Direction.LONG if pos.get("side") == "long" else Direction.SHORT,
                    volume=float(pos.get("contracts", 0)),
                    price=float(pos.get("entryPrice", 0.0)),
                    pnl=float(pos.get("unrealizedPnl", 0.0)),
                    available=float(pos.get("contracts", 0))
                )

                result.append(position)

            for pos in result:
                self.on_position(pos)

            return result

        except Exception as e:
            logger.error(f"Failed to query positions: {e}")
            return []

    def query_order(self, req: Dict[str, Any]) -> Optional[OrderData]:
        """Query order"""
        try:
            order = self._exchange.fetch_order(req["orderid"], req.get("symbol", ""))
            return self._to_order_data(order)
        except Exception as e:
            logger.error(f"Failed to query order: {e}")
            return None

    def query_contract(self) -> List[ContractData]:
        """Query contracts"""
        try:
            markets = self._exchange.load_markets()
            result = []

            for symbol, market in markets.items():
                if not market.get("active", True):
                    continue

                contract = ContractData(
                    gateway_name=self.gateway_name,
                    symbol=symbol,
                    exchange=self.gateway_name,
                    name=market.get("name", symbol),
                    pricetick=market.get("precision", {}).get("price", 0.0),
                    min_volume=market.get("limits", {}).get("amount", {}).get("min", 0.0),
                    max_volume=market.get("limits", {}).get("amount", {}).get("max", 0.0),
                    leverage=market.get("limits", {}).get("leverage", {}).get("max", 1)
                )

                # Set product class
                market_type = market.get("type", "")
                if market_type == "spot":
                    contract.product_class = ProductClass.SPOT
                elif market_type == "swap":
                    contract.product_class = ProductClass.SWAP
                elif market_type == "future":
                    contract.product_class = ProductClass.FUTURES

                result.append(contract)

            for contract in result:
                self.on_contract(contract)

            return result

        except Exception as e:
            logger.error(f"Failed to query contracts: {e}")
            return []

    def subscribe_quote(self, symbols: List[str]):
        """Subscribe to quotes (via polling)"""
        pass

    def get_bars(
        self,
        symbol: str,
        interval: str,
        start: Optional[Any] = None,
        end: Optional[Any] = None,
        limit: int = 1000
    ) -> List[KlineData]:
        """Get historical K-line data"""
        try:
            timeframe = self._to_ccxt_timeframe(interval)
            since = int(start.timestamp() * 1000) if start else None

            ohlcv = self._exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            result = []

            for candle in ohlcv:
                kline = KlineData(
                    gateway_name=self.gateway_name,
                    symbol=symbol,
                    exchange=self.gateway_name,
                    datetime=datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc),
                    interval=interval,
                    open_price=candle[1],
                    high_price=candle[2],
                    low_price=candle[3],
                    close_price=candle[4],
                    volume=candle[5]
                )
                result.append(kline)

            return result

        except Exception as e:
            logger.error(f"Failed to get bars: {e}")
            return []

    def get_tick(self, symbol: str) -> Optional[TickData]:
        """Get latest tick"""
        try:
            ticker = self._exchange.fetch_ticker(symbol)

            tick = TickData(
                gateway_name=self.gateway_name,
                symbol=symbol,
                exchange=self.gateway_name,
                datetime=datetime.now(timezone.utc),
                last_price=ticker.get("last", 0.0),
                bid_price_1=ticker.get("bid", 0.0),
                bid_volume_1=ticker.get("bidVolume", 0.0),
                ask_price_1=ticker.get("ask", 0.0),
                ask_volume_1=ticker.get("askVolume", 0.0),
                volume=ticker.get("baseVolume", 0.0),
                turnover=ticker.get("quoteVolume", 0.0)
            )

            return tick

        except Exception as e:
            logger.error(f"Failed to get tick: {e}")
            return None

    # ==================== Helper Methods ====================

    def _to_order_data(self, order: Dict) -> OrderData:
        """Convert CCXT order to OrderData"""
        side = order.get("side", "")
        direction = Direction.LONG if side == "buy" else Direction.SHORT

        order_type = order.get("type", "")
        if order_type == "market":
            type_ = OrderType.MARKET
        else:
            type_ = OrderType.LIMIT

        status_str = order.get("status", "")
        if status_str == "closed":
            status = Status.ALLTRADED
        elif status_str == "open":
            status = Status.NOTTRADED
        elif status_str == "canceled":
            status = Status.CANCELLED
        else:
            status = Status.NOTTRADED

        return OrderData(
            gateway_name=self.gateway_name,
            orderid=str(order.get("id", "")),
            symbol=order.get("symbol", ""),
            exchange=self.gateway_name,
            type=type_,
            direction=direction,
            price=order.get("price", 0.0),
            volume=order.get("amount", 0.0),
            traded=order.get("filled", 0.0),
            status=status
        )

    @staticmethod
    def _to_ccxt_timeframe(interval: str) -> str:
        """Convert interval to CCXT timeframe"""
        mapping = {
            "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h", "12h": "12h",
            "1d": "1d", "3d": "3d", "1w": "1w", "1M": "1M"
        }
        return mapping.get(interval, "1h")

    @property
    def gateway_type(self) -> str:
        return GatewayType.CRYPTO
