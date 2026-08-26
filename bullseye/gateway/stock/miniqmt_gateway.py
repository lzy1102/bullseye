"""
MiniQMT Gateway - A-share stock trading gateway via xtquant / miniQMT

Connects to 迅投 miniQMT client for Chinese A-share market trading.
Supports data subscription (tick/K-line) and trading (order/cancel/query).

Dependencies:
    pip install xtquant

Requirements:
    - Windows with miniQMT client running (or xqshare remote on Linux/Mac)
    - miniQMT account with trading permissions

Architecture:
    MiniQmtGateway(BaseGateway)
    ├── _TraderCb(XtQuantTraderCallback) → 交易回调 → on_order/on_trade/...
    └── _on_tick() → xtdata callback → on_tick()
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from ...trader.eventengine import EventEngine, EventType
from ...trader.object import (
    AccountData,
    ContractData,
    Direction,
    KlineData,
    OrderData,
    OrderType,
    PositionData,
    ProductClass,
    Status,
    TickData,
    TradeData,
)
from ..base import BaseGateway, GatewayType

try:
    from xtquant import xtconstant, xtdata
    from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
    from xtquant.xttype import StockAccount

    XTQUANT_AVAILABLE = True
except ImportError:
    XTQUANT_AVAILABLE = False

import logging

logger = logging.getLogger(__name__)

# =========================================================================
# xtquant → Bullseye enumeration mappings
# (initialized only when xtquant is available)
# =========================================================================

# Order type
_PRICE_TYPE_MAP: Dict[int, OrderType] = {}
_PRICE_TYPE_REVERSE: Dict[OrderType, int] = {}

# Direction
_DIRECTION_MAP: Dict[int, Direction] = {}
_DIRECTION_REVERSE: Dict[Direction, int] = {}

# Order status (constant values from xtquant documentation)
_STATUS_MAP: Dict[int, Status] = {
    48: Status.NOTTRADED,
    49: Status.NOTTRADED,
    50: Status.ALLTRADED,
    51: Status.PARTTRADED,
    52: Status.CANCELLED,
    53: Status.CANCELLED,
    54: Status.REJECTED,
    55: Status.CANCELLED,
}

# Exchange mapping (xtquant market code → exchange string)
_EXCHANGE_MAP: Dict[int, str] = {
    1: "SSE",
    2: "SZSE",
    3: "BSE",
}

# Product type mapping (xtquant → ProductClass)
_PRODUCT_MAP: Dict[int, ProductClass] = {
    0: ProductClass.EQUITY,
    1: ProductClass.INDEX,
    2: ProductClass.EQUITY,
    3: ProductClass.EQUITY,
    4: ProductClass.OPTIONS,
    5: ProductClass.EQUITY,
    6: ProductClass.EQUITY,
}

if XTQUANT_AVAILABLE:
    _PRICE_TYPE_MAP.update({
        xtconstant.FIX_PRICE: OrderType.LIMIT,
        xtconstant.LATEST_PRICE: OrderType.MARKET,
        7: OrderType.MARKET,
        8: OrderType.LIMIT,
    })
    _PRICE_TYPE_REVERSE.update({
        OrderType.LIMIT: xtconstant.FIX_PRICE,
        OrderType.MARKET: xtconstant.LATEST_PRICE,
    })
    _DIRECTION_MAP.update({
        xtconstant.STOCK_BUY: Direction.LONG,
        xtconstant.STOCK_SELL: Direction.SHORT,
    })
    _DIRECTION_REVERSE = {v: k for k, v in _DIRECTION_MAP.items()}


# =========================================================================
# MiniQmtGateway
# =========================================================================


class MiniQmtGateway(BaseGateway):
    """A-share Stock Trading Gateway via miniQMT / xtquant.

    Requires miniQMT client running (Windows) or xqshare remote.

    Usage:
        gw = MiniQmtGateway(event_engine)
        gw.connect(
            qmt_path=r"D:\\QMT\\userdata_mini",
            session_id=123456,
            account_id="8881234567",
        )
        gw.subscribe_quote(["000001.SZ", "600000.SH"])
        gw.send_order({"symbol": "000001.SZ", "direction": Direction.LONG, ...})
    """

    def __init__(self, event_engine: EventEngine) -> None:
        super().__init__(event_engine, "MiniQMT")
        self._trader: Optional["XtQuantTrader"] = None
        self._account: Optional["StockAccount"] = None
        self._account_id: str = ""
        self._trader_cb: Optional["_TraderCb"] = None

    # =====================================================================
    # BaseGateway abstract methods
    # =====================================================================

    def connect(self, **kwargs) -> None:
        """Connect to miniQMT client.

        Required kwargs:
            qmt_path: Path to miniQMT userdata_mini directory
            session_id: Session ID (integer)
            account_id: Trading account ID string
        """
        if not XTQUANT_AVAILABLE:
            raise ImportError(
                "xtquant is required. Install with: pip install xtquant.\n"
                "Note: miniQMT client must be running on Windows (or xqshare remote)."
            )

        qmt_path = str(kwargs.get("qmt_path", ""))
        session_id = int(kwargs.get("session_id", 0))
        self._account_id = str(kwargs.get("account_id", ""))

        if not qmt_path or not session_id or not self._account_id:
            raise ValueError("qmt_path, session_id, and account_id are required")

        # Create trader
        self._trader = XtQuantTrader(qmt_path, session_id)
        self._trader_cb = _TraderCb(self)
        self._trader.register_callback(self._trader_cb)
        self._trader.start()

        # Connect
        result = self._trader.connect()
        if result != 0:
            self.on_log(f"MiniQMT connect failed: code={result}")
            return

        # Subscribe to account callbacks
        self._account = StockAccount(self._account_id, "STOCK")
        sub_result = self._trader.subscribe(self._account)
        if sub_result != 0:
            self.on_log(f"MiniQMT subscribe failed: code={sub_result}")
            return

        self._connected = True
        self.event_engine.publish(
            EventType.EVENT_GATEWAY_CONNECT, None, self.gateway_name
        )
        self.on_log(f"MiniQMT connected (account={self._account_id})")
        logger.info("MiniQMT connected: path=%s session=%d account=%s",
                     qmt_path, session_id, self._account_id)

    def close(self) -> None:
        """Disconnect from miniQMT."""
        if self._trader:
            try:
                self._trader.stop()
            except Exception:
                pass
            self._trader = None
        self._connected = False
        self.event_engine.publish(
            EventType.EVENT_GATEWAY_DISCONNECT, None, self.gateway_name
        )
        self.on_log("MiniQMT disconnected")

    def send_order(self, req: Dict[str, Any]) -> str:
        """Send stock order via miniQMT.

        req keys: symbol, direction, volume, order_type, price, reference, remark
        Returns: order_id string
        """
        if not self._trader or not self._account:
            self.on_log("MiniQMT trader not connected")
            return ""

        symbol = str(req["symbol"])
        direction = req.get("direction", Direction.LONG)
        volume = int(req.get("volume", 100))
        order_type = req.get("order_type", OrderType.LIMIT)
        price = float(req.get("price", 0.0))
        strategy_name = str(req.get("reference", "Bullseye"))
        remark = str(req.get("remark", ""))

        xt_direction = _DIRECTION_REVERSE.get(direction, xtconstant.STOCK_BUY)
        xt_price_type = _PRICE_TYPE_REVERSE.get(order_type, xtconstant.FIX_PRICE)

        try:
            order_id = self._trader.order_stock(
                self._account,
                symbol,
                xt_direction,
                volume,
                xt_price_type,
                price,
                strategy_name,
                remark,
            )
            if order_id < 0:
                self.on_log(f"MiniQMT order failed: error_code={order_id}")
                return ""
            self.on_log(f"MiniQMT order sent: id={order_id} {symbol}")
            return str(order_id)
        except Exception as e:
            self.on_log(f"MiniQMT order exception: {e}")
            logger.exception("MiniQMT send_order failed")
            return ""

    def cancel_order(self, req: Dict[str, Any]) -> bool:
        """Cancel an order.

        req keys: orderid (integer order ID), account_id (optional)
        """
        if not self._trader or not self._account:
            return False

        try:
            order_id = int(req["orderid"])
            result = self._trader.cancel_order_stock(self._account, order_id)
            if result != 0:
                self.on_log(f"MiniQMT cancel failed: error_code={result}")
                return False
            self.on_log(f"MiniQMT cancel sent: order_id={order_id}")
            return True
        except Exception as e:
            self.on_log(f"MiniQMT cancel exception: {e}")
            return False

    def query_account(self) -> Optional[AccountData]:
        """Query account asset info."""
        if not self._trader or not self._account:
            return None
        try:
            asset = self._trader.query_stock_asset(self._account)
            if not asset:
                return None
            return AccountData(
                gateway_name=self.gateway_name,
                accountid=str(asset.account_id),
                balance=asset.total_asset,
                available=asset.cash,
                frozen=asset.total_asset - asset.cash,
                currency="CNY",
            )
        except Exception as e:
            self.on_log(f"MiniQMT query_account failed: {e}")
            return None

    def query_position(self) -> List[PositionData]:
        """Query stock positions."""
        if not self._trader or not self._account:
            return []
        try:
            xt_positions = self._trader.query_stock_positions(self._account)
            result = []
            for pos in xt_positions:
                result.append(PositionData(
                    gateway_name=self.gateway_name,
                    symbol=pos.stock_code,
                    exchange=_EXCHANGE_MAP.get(getattr(pos, "market", 0), ""),
                    direction=Direction.LONG,
                    volume=pos.volume,
                    price=pos.avg_price,
                    pnl=pos.profit,
                    available=pos.can_use_volume,
                ))
            return result
        except Exception as e:
            self.on_log(f"MiniQMT query_position failed: {e}")
            return []

    def query_order(self, req: Dict[str, Any]) -> Optional[OrderData]:
        """Query a specific order by its ID."""
        if not self._trader or not self._account:
            return None
        try:
            order_id = int(req["orderid"])
            xt_order = self._trader.query_stock_order(self._account, order_id)
            if not xt_order:
                return None
            return _to_order_data(xt_order, self.gateway_name)
        except Exception as e:
            self.on_log(f"MiniQMT query_order failed: {e}")
            return None

    def query_contract(self) -> List[ContractData]:
        """Query available stock instruments.

        Returns A-share stock list via xtdata.
        """
        if not XTQUANT_AVAILABLE:
            return []
        try:
            stocks = xtdata.get_stock_list_in_sector("沪深A股")
            result = []
            for code in stocks:
                # Determine exchange from code suffix
                if code.endswith(".SH"):
                    exchange = "SSE"
                elif code.endswith(".SZ"):
                    exchange = "SZSE"
                elif code.endswith(".BJ"):
                    exchange = "BSE"
                else:
                    exchange = ""
                result.append(ContractData(
                    gateway_name=self.gateway_name,
                    symbol=code,
                    exchange=exchange,
                    name=code,
                    product_class=ProductClass.EQUITY,
                    size=1.0,
                    pricetick=0.01,
                    min_volume=100,
                ))
            return result
        except Exception as e:
            self.on_log(f"MiniQMT query_contract failed: {e}")
            return []

    # =====================================================================
    # Optional methods
    # =====================================================================

    def subscribe_quote(self, symbols: List[str]) -> None:
        """Subscribe to real-time tick data for given symbols."""
        if not XTQUANT_AVAILABLE:
            self.on_log("xtquant not available – cannot subscribe")
            return

        for sym in symbols:
            try:
                xtdata.subscribe_quote(
                    sym,
                    period="tick",
                    count=-1,
                    callback=_make_tick_callback(self),
                )
            except Exception as e:
                self.on_log(f"Failed to subscribe {sym}: {e}")

        self.on_log(f"Subscribed to {len(symbols)} symbols via xtdata")

    def get_bars(
        self,
        symbol: str,
        interval: str,
        start: Any = None,
        end: Any = None,
        limit: int = 1000,
    ) -> List[KlineData]:
        """Get historical K-line data via xtdata."""
        if not XTQUANT_AVAILABLE:
            return []

        try:
            df = xtdata.get_market_data(
                field_list=["open", "high", "low", "close", "volume", "amount"],
                stock_list=[symbol],
                period=interval,
                count=limit,
            )
            if df is None or df.empty:
                return []

            result = []
            for idx in df.index:
                row = df.loc[idx, symbol] if isinstance(df.columns, pd.MultiIndex) else df.loc[idx]
                k = KlineData(
                    gateway_name=self.gateway_name,
                    symbol=symbol,
                    interval=interval,
                    datetime=idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx,
                    open_price=float(row["open"]),
                    high_price=float(row["high"]),
                    low_price=float(row["low"]),
                    close_price=float(row["close"]),
                    volume=float(row["volume"]),
                )
                result.append(k)
            return result
        except Exception as e:
            self.on_log(f"MiniQMT get_bars failed: {e}")
            return []

    @property
    def gateway_type(self) -> str:
        return GatewayType.STOCK


# =========================================================================
# TraderCallback – bridges xtquant callbacks to Bullseye events
# =========================================================================


class _TraderCb(XtQuantTraderCallback if XTQUANT_AVAILABLE else object):
    """Callback handler for xtquant trader events."""

    def __init__(self, gateway: "MiniQmtGateway") -> None:
        if XTQUANT_AVAILABLE:
            XtQuantTraderCallback.__init__(self)
        self.gw: "MiniQmtGateway" = gateway

    def on_stock_order(self, order) -> None:
        """Order status update."""
        data = _to_order_data(order, self.gw.gateway_name)
        self.gw.on_order(data)

    def on_stock_trade(self, trade) -> None:
        """Trade fill notification."""
        data = TradeData(
            gateway_name=self.gw.gateway_name,
            tradeid=str(trade.trade_id),
            orderid=str(trade.order_sysid),
            symbol=trade.stock_code,
            exchange=_EXCHANGE_MAP.get(getattr(trade, "market", 0), ""),
            direction=_DIRECTION_MAP.get(trade.order_type),
            price=trade.traded_price,
            volume=trade.traded_volume,
            datetime=datetime.fromtimestamp(trade.traded_time)
            if hasattr(trade, "traded_time") and trade.traded_time
            else datetime.now(),
        )
        self.gw.on_trade(data)

    def on_stock_position(self, position) -> None:
        """Position update (infrequent in miniQMT)."""
        data = PositionData(
            gateway_name=self.gw.gateway_name,
            symbol=position.stock_code,
            exchange=_EXCHANGE_MAP.get(getattr(position, "market", 0), ""),
            direction=Direction.LONG,
            volume=position.volume,
            price=position.avg_price,
            pnl=position.profit,
            available=position.can_use_volume,
        )
        self.gw.on_position(data)

    def on_stock_asset(self, asset) -> None:
        """Account asset update."""
        data = AccountData(
            gateway_name=self.gw.gateway_name,
            accountid=str(asset.account_id),
            balance=asset.total_asset,
            available=asset.cash,
            frozen=asset.total_asset - asset.cash,
            currency="CNY",
        )
        self.gw.on_account(data)

    def on_order_error(self, order_error) -> None:
        """Order placement error."""
        self.gw.on_log(
            f"Order error: id={order_error.order_id} "
            f"[{order_error.error_id}] {order_error.error_msg}"
        )

    def on_cancel_error(self, cancel_error) -> None:
        """Cancel order error."""
        self.gw.on_log(
            f"Cancel error: id={cancel_error.order_id} "
            f"[{cancel_error.error_id}] {cancel_error.error_msg}"
        )

    def on_account_status(self, status) -> None:
        """Account connection status change."""
        pass


# =========================================================================
# Tick callback factory
# =========================================================================


def _make_tick_callback(gateway: "MiniQmtGateway"):
    """Create a closure-based tick callback for xtdata.subscribe_quote."""

    def on_tick(data: dict) -> None:
        """xtdata tick callback – data is {code: tick_dict}."""
        for code, tick in data.items():
            tick_data = TickData(
                gateway_name=gateway.gateway_name,
                symbol=code,
                exchange=_exchange_from_code(code),
                last_price=tick.get("lastPrice", 0.0),
                volume=tick.get("volume", 0.0),
                turnover=tick.get("amount", 0.0),
                open_price=tick.get("open", 0.0),
                high_price=tick.get("high", 0.0),
                low_price=tick.get("low", 0.0),
                pre_close=tick.get("preClose", 0.0),
                bid_price_1=_safe_list_get(tick.get("bidPrice", []), 0, 0.0),
                ask_price_1=_safe_list_get(tick.get("askPrice", []), 0, 0.0),
                bid_volume_1=_safe_list_get(tick.get("bidVol", []), 0, 0.0),
                ask_volume_1=_safe_list_get(tick.get("askVol", []), 0, 0.0),
                datetime=datetime.fromtimestamp(tick.get("time", 0) / 1000)
                if tick.get("time") else datetime.now(),
            )
            gateway.on_tick(tick_data)

    return on_tick


# =========================================================================
# Conversion helpers
# =========================================================================


def _to_order_data(order, gateway_name: str) -> OrderData:
    """Convert xtquant order object to Bullseye OrderData."""
    return OrderData(
        gateway_name=gateway_name,
        orderid=str(order.order_sysid),
        symbol=order.stock_code,
        exchange=_EXCHANGE_MAP.get(getattr(order, "market", 0), ""),
        type=_PRICE_TYPE_MAP.get(order.price_type, OrderType.LIMIT),
        direction=_DIRECTION_MAP.get(order.order_type),
        price=order.price,
        volume=order.order_volume,
        traded=order.traded_volume,
        status=_STATUS_MAP.get(order.order_status, Status.NOTTRADED),
        datetime=datetime.fromtimestamp(order.order_time)
        if hasattr(order, "order_time") and order.order_time
        else None,
    )


def _exchange_from_code(code: str) -> str:
    """Determine exchange from stock code suffix."""
    if code.endswith(".SH"):
        return "SSE"
    elif code.endswith(".SZ"):
        return "SZSE"
    elif code.endswith(".BJ"):
        return "BSE"
    return ""


def _safe_list_get(lst, idx: int, default=0.0):
    """Safely get element from list."""
    if lst and len(lst) > idx:
        return float(lst[idx])
    return default
