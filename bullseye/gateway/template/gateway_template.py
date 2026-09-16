"""
Template Gateway - Reference implementation for personal order bridges.

This gateway talks to a local HTTP "bridge" service (e.g. an Android
automation tool exposing REST endpoints) instead of a formal broker API.

Bridge service contract:
    GET  /health                        -> {"status": "ok"}
    POST /order                         -> {"order_id": "..."}
         body: {client_order_id, symbol, side, offset, type, price, volume}
    GET  /order/{order_id}              -> {"status", "filled", "avg_price"}
         status: pending|submitted|partial|filled|cancelled|rejected
    POST /order/{order_id}/cancel       -> {"ok": true}
    GET  /orders?status=open            -> [{"order_id", "status", ...}]
    GET  /account                       -> {"account_id", "balance", "available", "frozen"}
    GET  /positions                     -> [{"symbol", "direction", "volume", "avg_price"}]
    GET  /contracts                     -> [{"symbol", "name", "exchange"}]

Reliability features required by the framework standard:
- client_order_id round-trip: the bridge must echo it back so orders can be
  reconciled across restarts.
- Polling confirmation: an order is only considered accepted/partially or
  fully filled after the bridge REPORTS it (never trust the initial POST).
- Kill switch: a marker file disables new orders instantly.
- Reconciliation: sync open orders against the bridge to repair local state.

See docs/gateway-development.md for the full integration standard.
"""
import time
import logging
from typing import Any, Dict, List, Optional

from ..base import BaseGateway, GatewayType
from ...trader.eventengine import EventEngine
from ...trader.object import (
    AccountData,
    ContractData,
    Direction,
    Offset,
    OrderData,
    OrderType,
    PositionData,
    ProductClass,
    Status,
)

logger = logging.getLogger(__name__)


# Bridge status string -> bullseye Status
_STATUS_MAP = {
    "pending": Status.NOTTRADED,
    "submitted": Status.NOTTRADED,
    "partial": Status.PARTTRADED,
    "parttraded": Status.PARTTRADED,
    "filled": Status.ALLTRADED,
    "alltraded": Status.ALLTRADED,
    "cancelled": Status.CANCELLED,
    "canceled": Status.CANCELLED,
    "rejected": Status.REJECTED,
}


class HttpTransport:
    """Thin HTTP transport (stdlib-friendly: uses requests if available)."""

    def __init__(self, base_url: str, token: str = "", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, body: Optional[Dict] = None) -> Any:
        try:
            import requests
        except ImportError as e:
            raise ImportError(
                "requests is required for TemplateGateway: pip install requests"
            ) from e

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        url = f"{self.base_url}{path}"
        resp = requests.request(method, url, json=body, headers=headers, timeout=self.timeout)
        if resp.status_code >= 400:
            raise ConnectionError(f"Bridge error {resp.status_code} for {method} {path}: {resp.text[:200]}")
        if not resp.content:
            return {}
        return resp.json()


class TemplateGateway(BaseGateway):
    """Reference gateway for a local HTTP order-bridge service."""

    def __init__(
        self,
        event_engine: EventEngine,
        gateway_name: str = "Template",
        transport: Optional[Any] = None,
    ):
        super().__init__(event_engine, gateway_name)
        self._transport = transport  # injectable for tests
        self._kill_switch_file: str = ""
        self._poll_interval: float = 0.5
        self._confirm_timeout: float = 10.0
        self._order_seq: int = 0
        self._last_reported_filled: Dict[str, float] = {}
        self._last_status: Dict[str, Status] = {}

    # ==================== Lifecycle ====================

    def connect(self, **kwargs) -> None:
        """
        Connect to the bridge.

        Required kwargs:
            base_url: Bridge base URL (e.g. http://127.0.0.1:8000)
        Optional kwargs:
            token: Bearer token for the bridge
            kill_switch_file: Marker file that disables new orders
            confirm_timeout: Seconds to wait for order confirmation (default 10)
            poll_interval: Seconds between status polls (default 0.5)
        """
        base_url = kwargs.get("base_url", "")
        if not base_url and self._transport is None:
            raise ValueError("base_url is required to connect")

        if self._transport is None:
            self._transport = HttpTransport(
                base_url=base_url,
                token=kwargs.get("token", ""),
                timeout=float(kwargs.get("http_timeout", 10.0)),
            )

        self._kill_switch_file = kwargs.get("kill_switch_file", "")
        self._confirm_timeout = float(kwargs.get("confirm_timeout", 10.0))
        self._poll_interval = float(kwargs.get("poll_interval", 0.5))

        health = self._transport.request("GET", "/health")
        if isinstance(health, dict) and health.get("status") not in ("ok", "healthy", None):
            raise ConnectionError(f"Bridge unhealthy: {health}")

        self._connected = True
        logger.info(f"Connected to order bridge at {base_url or 'injected transport'}")

    def close(self) -> None:
        """Disconnect (idempotent)."""
        if self._connected:
            self._connected = False
            logger.info("Order bridge gateway closed")

    # ==================== Trading (required) ====================

    def send_order(self, req: Dict[str, Any]) -> Optional[str]:
        """
        Submit an order to the bridge. Returns the bridge order id or None.

        The framework-visible order id is generated here and echoed to the
        bridge as client_order_id for reconciliation.
        """
        try:
            self._assert_trading_allowed()
        except RuntimeError as e:
            logger.error(f"send_order blocked: {e}")
            return None

        symbol = req.get("symbol", "")
        if not symbol or float(req.get("volume", 0) or 0) <= 0:
            logger.error(f"Invalid order request: {req}")
            return None

        self._order_seq += 1
        orderid = f"{self.gateway_name}-{int(time.time() * 1000)}-{self._order_seq}"
        direction = req.get("direction", Direction.LONG)
        offset = req.get("offset", Offset.OPEN)
        order_type = req.get("order_type", OrderType.MARKET)

        body = {
            "client_order_id": orderid,
            "symbol": symbol,
            "side": "buy" if direction == Direction.LONG else "sell",
            "offset": getattr(offset, "value", str(offset)),
            "type": getattr(order_type, "value", str(order_type)),
            "price": float(req.get("price", 0) or 0),
            "volume": float(req.get("volume", 0) or 0),
        }

        try:
            resp = self._transport.request("POST", "/order", body=body)
        except Exception as e:
            logger.error(f"Bridge rejected order submission: {e}")
            return None

        bridge_id = (resp or {}).get("order_id")
        if not bridge_id:
            logger.error(f"Bridge did not return an order_id: {resp}")
            return None

        # Publish the initial (unconfirmed) state; confirmation follows
        self._publish_order(
            orderid=orderid,
            symbol=symbol,
            direction=direction,
            offset=offset,
            order_type=order_type,
            price=body["price"],
            volume=body["volume"],
            status=Status.NOTTRADED,
        )
        logger.info(f"Order submitted to bridge: {orderid} (bridge_id={bridge_id})")
        return orderid

    def cancel_order(self, req: Dict[str, Any]) -> bool:
        """Cancel an order. Cancelling is always allowed (safety)."""
        orderid = req.get("orderid", "")
        if not orderid:
            return False
        try:
            resp = self._transport.request("POST", f"/order/{orderid}/cancel")
            ok = bool((resp or {}).get("ok", True))
            if ok:
                logger.info(f"Cancel requested for {orderid}")
            return ok
        except Exception as e:
            logger.error(f"Cancel failed for {orderid}: {e}")
            return False

    def query_order(self, req: Dict[str, Any]) -> Optional[OrderData]:
        """Read the current order state from the bridge (no event publishing)."""
        orderid = req.get("orderid", "")
        if not orderid:
            return None
        try:
            raw = self._transport.request("GET", f"/order/{orderid}")
        except Exception as e:
            logger.warning(f"query_order failed for {orderid}: {e}")
            return None
        return self._raw_to_order(orderid, raw or {})

    # ==================== Confirmation (framework standard) ====================

    def confirm_order(
        self,
        orderid: str,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
    ) -> Optional[OrderData]:
        """
        Poll the bridge until the order reaches a terminal status (or timeout),
        publishing on_order on status changes and on_trade on new fills.

        Returns the final OrderData (possibly still NOTTRADED on timeout).
        """
        timeout = self._confirm_timeout if timeout is None else timeout
        poll_interval = self._poll_interval if poll_interval is None else poll_interval
        deadline = time.monotonic() + timeout
        last: Optional[OrderData] = None
        last_status: Optional[Status] = None
        last_filled = 0.0

        while True:
            order = self.query_order({"orderid": orderid})
            if order is not None:
                last = order
                if order.status != last_status:
                    last_status = order.status
                    self._emit_order_if_changed(order)
                    logger.info(f"Order {orderid} status -> {order.status.value}")

                if order.traded > last_filled:
                    delta = order.traded - last_filled
                    self._publish_fill(order, delta)
                    last_filled = order.traded

                if order.status in (Status.ALLTRADED, Status.CANCELLED, Status.REJECTED):
                    return order

            if time.monotonic() >= deadline:
                logger.warning(
                    f"Order {orderid} not confirmed within {timeout}s "
                    f"(last status: {last.status.value if last else 'unknown'})"
                )
                return last

            time.sleep(max(0.01, poll_interval))

    def reconcile_open_orders(self) -> int:
        """
        Pull open orders from the bridge and publish their current state.

        Call at startup and periodically; the bridge is the source of truth.
        Returns the number of orders synced.
        """
        try:
            raw_orders = self._transport.request("GET", "/orders?status=open")
        except Exception as e:
            logger.error(f"Reconciliation failed to fetch open orders: {e}")
            return 0

        count = 0
        for raw in raw_orders or []:
            orderid = raw.get("client_order_id") or raw.get("order_id", "")
            if not orderid:
                continue
            order = self._raw_to_order(orderid, raw)
            self._emit_order_if_changed(order)
            if order.traded:
                self._publish_fill(order, order.traded)
            count += 1
        if count:
            logger.info(f"Reconciled {count} open order(s) from the bridge")
        return count

    # ==================== Queries (required) ====================

    def query_account(self) -> Optional[AccountData]:
        try:
            raw = self._transport.request("GET", "/account") or {}
        except Exception as e:
            logger.warning(f"query_account failed: {e}")
            return None
        return AccountData(
            gateway_name=self.gateway_name,
            accountid=str(raw.get("account_id", "")),
            balance=float(raw.get("balance", 0) or 0),
            available=float(raw.get("available", 0) or 0),
            frozen=float(raw.get("frozen", 0) or 0),
        )

    def query_position(self) -> List[PositionData]:
        try:
            raw_list = self._transport.request("GET", "/positions") or []
        except Exception as e:
            logger.warning(f"query_position failed: {e}")
            return []

        positions = []
        for raw in raw_list:
            direction = (
                Direction.SHORT
                if str(raw.get("direction", "long")).lower() == "short"
                else Direction.LONG
            )
            positions.append(
                PositionData(
                    gateway_name=self.gateway_name,
                    symbol=str(raw.get("symbol", "")),
                    direction=direction,
                    volume=float(raw.get("volume", 0) or 0),
                    price=float(raw.get("avg_price", 0) or 0),
                    available=float(raw.get("available", raw.get("volume", 0)) or 0),
                )
            )
        return positions

    def query_contract(self) -> List[ContractData]:
        try:
            raw_list = self._transport.request("GET", "/contracts") or []
        except Exception as e:
            logger.warning(f"query_contract failed: {e}")
            return []

        contracts = []
        for raw in raw_list:
            contracts.append(
                ContractData(
                    gateway_name=self.gateway_name,
                    symbol=str(raw.get("symbol", "")),
                    name=str(raw.get("name", "")),
                    exchange=str(raw.get("exchange", "")),
                    product_class=ProductClass.EQUITY,
                )
            )
        return contracts

    # ==================== Internals ====================

    def _assert_trading_allowed(self) -> None:
        """Kill switch: presence of the marker file blocks new orders."""
        import os

        if self._kill_switch_file and os.path.exists(self._kill_switch_file):
            raise RuntimeError(
                f"Kill switch engaged ({self._kill_switch_file}); "
                "new orders are disabled. Remove the file to resume."
            )

    def _raw_to_order(self, orderid: str, raw: Dict[str, Any]) -> OrderData:
        status = _STATUS_MAP.get(str(raw.get("status", "")).lower(), Status.NOTTRADED)
        return OrderData(
            gateway_name=self.gateway_name,
            orderid=orderid,
            symbol=str(raw.get("symbol", "")),
            direction=Direction.LONG if raw.get("side") == "buy" else Direction.SHORT,
            offset=Offset.OPEN,
            type=OrderType.LIMIT if str(raw.get("type", "market")).lower() == "limit" else OrderType.MARKET,
            price=float(raw.get("price", raw.get("avg_price", 0)) or 0),
            volume=float(raw.get("volume", 0) or 0),
            traded=float(raw.get("filled", 0) or 0),
            status=status,
        )

    def _emit_order_if_changed(self, order: OrderData) -> None:
        """Publish an order event only when its status actually changed."""
        if self._last_status.get(order.orderid) == order.status:
            return
        self._last_status[order.orderid] = order.status
        self.on_order(order)

    def _publish_order(
        self,
        orderid: str,
        symbol: str,
        direction: Direction,
        offset: Offset,
        order_type: OrderType,
        price: float,
        volume: float,
        status: Status,
    ) -> None:
        self._emit_order_if_changed(
            OrderData(
                gateway_name=self.gateway_name,
                orderid=orderid,
                symbol=symbol,
                direction=direction,
                offset=offset,
                type=order_type,
                price=price,
                volume=volume,
                traded=0.0,
                status=status,
            )
        )

    def _publish_fill(self, order: OrderData, delta: float) -> None:
        from ...trader.object import TradeData

        self.on_trade(
            TradeData(
                gateway_name=self.gateway_name,
                tradeid=f"{order.orderid}-{order.traded}",
                orderid=order.orderid,
                symbol=order.symbol,
                direction=order.direction,
                offset=order.offset,
                price=order.price,
                volume=delta,
            )
        )

    @property
    def gateway_type(self) -> str:
        return GatewayType.STOCK
