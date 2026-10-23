"""
ThsGateway - A-share trading via the THS (同花顺) counter protocol (ths-trade-client).

Wraps `ths_client.TradeClient` (https://github.com/lzy1102/ths_rea) behind the
framework's BaseGateway contract, so a retail account without miniQMT can trade:

    pip install ths-trade-client

    market_type: custom
    custom:
      gateway: "bullseye.gateway.stock.ths_gateway.ThsGateway"
      profile: user_data/local_profile.json   # 账号/股东号/设备指纹, 绝不入库
      datafeed: baostock                      # K线仍走 baostock

Implementation status (read-only first, deliberately):
    ✅ connect / close / query_account / query_position / query_order /
       query_contract / quote pushes
    ⛔ send_order / cancel_order  -> raise NotImplementedError until the two
       blockers are done (see _ORDER_BLOCKERS below). Enabling live trading
       before they are fixed risks duplicate or unstoppable orders.

_ORDER_BLOCKERS
    1. ths-trade-client has no cancel (撤单) yet. Our exits (chandelier, stop,
       time-stop) all need it. As of v0.13.1 the 撤单 command family is known
       (XX02: 0222/0322; 0122/0222/0322 answer "功能的服务，敬请谅解！" from the
       service layer before parsing the body), but the parameters - probably
       `htbh` 合同号 - still need a capture with a cancellable order live.
       The repo ships `ths-capture-orders` for exactly that.
    2. TradeClient auto-retries a failed request once after reconnect. Order
       placement is NOT idempotent, so a retry can double-buy. The live path
       must instead reconcile against 当日委托 before resending.

Requires ths-trade-client >= 0.13.1: v0.13.1 fixed `precheck()` hanging during
trading hours (the 0124 reply comes back as a 0x50 push, not a 0x10 reply) and
started cleaning the GBK reply text (`clean_text`), which is what lets
`extract_counter_no` read 委托编号 instead of falling back to a reconcile. Our
order path calls precheck internally (buy_market / limit_order use it for the
reference price), so 0.13.0 would block an order for the full timeout mid-session.

Field semantics of the counter replies are GBK key=value strings; the parsing
here is defensive (missing/unknown fields degrade to None instead of raising)
because ths-trade-client's own docs note some numeric fields still need to be
confirmed against a funded account.
"""
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

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
    TickData,
    TradeData,
)
from ..base import BaseGateway, GatewayType

try:
    from ths_client import TradeClient

    THS_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    THS_AVAILABLE = False
    TradeClient = None  # type: ignore[assignment]


def _to_float(value: Any) -> float:
    """Counter replies are GBK k=v strings; be tolerant of junk."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _pick(kv: Dict[str, Any], *names: str) -> Any:
    """First present alias from a counter reply (field names vary by template)."""
    for n in names:
        if n in kv and kv[n] not in (None, ""):
            return kv[n]
    return None


def normalize_symbol(symbol: str) -> str:
    """601398.SH / 601398 -> 601398 (ths-trade-client takes bare codes)."""
    return str(symbol or "").split(".")[0].strip()


def market_of(symbol: str) -> str:
    """'2' = 上交所, '1' = 深交所 (per ths-trade-client convention)."""
    code = normalize_symbol(symbol)
    if code.startswith(("60", "68", "51", "58", "11", "5")):
        return "2"
    return "1"


def extract_counter_no(reply: Any) -> str:
    """Pull 委托编号 (counter order number) out of a THS order reply.

    Prefers the structured kv view, falls back to the GBK text. Returns ""
    when nothing matches - the caller must then reconcile instead of trusting
    the submission.
    """
    if not isinstance(reply, dict):
        return ""
    kv = reply.get("kv")
    if isinstance(kv, dict):
        for key in ("wtbh", "entrust_no", "order_no", "ddbh"):
            val = kv.get(key)
            if val not in (None, ""):
                return str(val).strip()
    text = reply.get("text") or ""
    if not isinstance(text, str):
        return ""
    for pattern in (r"wtbh\s*=\s*([0-9]+)", r"委托编号\s*[:：]?\s*([0-9]+)",
                    r"合同编号\s*[:：]?\s*([0-9]+)"):
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return ""


def in_trading_window(now: Optional[datetime] = None) -> bool:
    """A-share continuous auction: 09:30-11:30 / 13:00-15:00, Mon-Fri."""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 570 <= minutes <= 690 or 780 <= minutes <= 900


class ThsGateway(BaseGateway):
    """THS counter gateway.

    Live order placement is implemented but **hard-gated** by
    ``_LIVE_TRADING_ENABLED`` (default False). Flipping it requires cancel
    support (see _ORDER_BLOCKERS) - the placement path is written so that an
    ambiguous result is reconciled against 当日委托 rather than retried, since
    order placement is not idempotent.
    """

    # Master switch. Deliberately off: cancel (撤单) is still missing upstream,
    # so every exit path (stop / chandelier / time-stop) could not be honoured.
    _LIVE_TRADING_ENABLED: bool = False

    def __init__(
        self,
        event_engine: EventEngine,
        gateway_name: str = "THS",
        client: Optional[Any] = None,
    ):
        super().__init__(event_engine, gateway_name)
        self._client = client            # injectable for tests
        self._lock = threading.RLock()  # TradeClient is not thread-safe
        self._profile_path: str = ""
        self._heartbeat: int = 30
        self._quote_cache: Dict[str, Dict[str, float]] = {}
        self._last_tick: Dict[str, float] = {}
        # --- order path state ---
        self._kill_switch_file: str = ""
        self._order_seq: int = 0
        self._confirm_timeout: float = 10.0
        self._poll_interval: float = 0.5
        self._reconcile_grace: float = 3.0   # seconds to wait before resending
        self._enforce_window: bool = True    # local A-share session guard
        self._order_map_store: Dict[str, str] = {}      # client id -> 委托编号
        self._orders: Dict[str, Dict[str, Any]] = {}    # client id -> full record
        self._by_counter: Dict[str, str] = {}           # 委托编号 -> client id
        self._last_status: Dict[str, Status] = {}

    # ==================== Lifecycle ====================

    def connect(
        self,
        profile: str = "",
        heartbeat: int = 30,
        client: Optional[Any] = None,
        kill_switch_file: str = "",
        confirm_timeout: float = 10.0,
        poll_interval: float = 0.5,
        reconcile_grace: float = 3.0,
        enforce_trading_window: bool = True,
        **kwargs,
    ) -> None:
        """
        Login to the counter.

        Required kwargs:
            profile: path to local_profile.json (or THS_PROFILE env var)
        Optional kwargs:
            heartbeat: keepalive seconds (0 disables; default 30)
            client: pre-built TradeClient (tests / reuse)
        """
        if client is not None:
            self._client = client
        if self._client is None:
            if not THS_AVAILABLE:
                raise ImportError(
                    "ths-trade-client is required for ThsGateway: "
                    "pip install ths-trade-client"
                )
            if not profile:
                profile = os.environ.get("THS_PROFILE", "")
            if not profile:
                raise ValueError(
                    "profile is required (local_profile.json with 资金账号/股东号)"
                )
            self._profile_path = profile
            self._client = TradeClient.from_profile(profile, on_push=self._on_push)
        self._kill_switch_file = kill_switch_file
        self._confirm_timeout = float(confirm_timeout)
        self._poll_interval = float(poll_interval)
        self._reconcile_grace = float(reconcile_grace)
        self._enforce_window = bool(enforce_trading_window)

        with self._lock:
            self._client.heartbeat = int(heartbeat)
            # TradeClient auto-retries after reconnect; harmless for queries,
            # unsafe for orders - the live path must override it.
            if hasattr(self._client, "auto_reconnect"):
                self._client.auto_reconnect = True
            self._client.start()

        self._connected = True
        self.gateway_name = self.gateway_name or "THS"
        for contract in self.query_contract() or []:
            self.on_contract(contract)
        account = self.query_account()
        if account is not None:
            self.on_account(account)
        for pos in self.query_position() or []:
            self.on_position(pos)

    def close(self) -> None:
        """Logout (idempotent)."""
        if not self._connected:
            return
        with self._lock:
            try:
                if self._client is not None:
                    self._client.close()
            except Exception as e:  # pragma: no cover - best effort
                self.logger_warning(f"THS logout error: {e}")
        self._connected = False

    @staticmethod
    def logger_warning(msg: str) -> None:
        import logging

        logging.getLogger(__name__).warning(msg)

    @staticmethod
    def logger_info(msg: str) -> None:
        import logging

        logging.getLogger(__name__).info(msg)

    # ==================== Queries (read-only) ====================

    def query_account(self) -> Optional[AccountData]:
        """Cash balance. ths-trade-client returns hd1.0 fields; we take the
        first balance-like field and expose it as `balance`."""
        if self._client is None:
            return None
        with self._lock:
            try:
                reply = self._client.query_balance()
            except Exception as e:
                self.logger_warning(f"THS query_balance failed: {e}")
                return None
        kv = self._as_kv(reply)
        balance = _to_float(_pick(kv, "zjjye", "balance", "ye", "kyje"))
        available = _to_float(_pick(kv, "kqye", "available", "kyjye"))
        if available == 0.0:
            available = balance
        return AccountData(
            accountid=self._account_id(),
            balance=balance,
            frozen=0.0,
            available=available,
        )

    def query_position(self) -> List[PositionData]:
        """Stock positions for both markets (沪+深)."""
        if self._client is None:
            return []
        out: List[PositionData] = []
        for market in ("2", "1"):
            with self._lock:
                try:
                    reply = self._client.query_positions(market=market)
                except Exception as e:
                    self.logger_warning(f"THS query_positions({market}) failed: {e}")
                    continue
            kv = self._as_kv(reply)
            volume = _to_float(_pick(kv, "zqdm_sl", "volume", "sl", "wdbl", "position"))
            if volume <= 0:
                continue
            code = normalize_symbol(str(_pick(kv, "zqdm", "code", "symbol") or ""))
            if not code:
                continue
            price = _to_float(_pick(kv, "zxj", "price", "hq"))
            out.append(
                PositionData(
                    symbol=code,
                    direction=Direction.LONG,
                    volume=volume,
                    available=_to_float(_pick(kv, "kyzq", "available", "tdzq")) or volume,
                    price=price,
                    exchange=market_of(code),
                    gateway_name=self.gateway_name,
                )
            )
        return out

    def query_order(self, req: Optional[Dict[str, Any]] = None) -> Optional[OrderData]:
        """Look up one order by our orderid (mapped to the counter 委托编号).

        Note: ths-trade-client falls back to the bootstrap cache when the
        counter rejects a standalone 委托查询, so the data can be stale by
        minutes; we only publish on actual status change (see _emit_order).
        """
        orderid = (req or {}).get("orderid", "")
        if not orderid or self._client is None:
            return None
        counter_no = self._counter_no(orderid)
        if not counter_no:
            return None
        for market in ("2", "1"):
            with self._lock:
                try:
                    reply = self._client.query_orders(market=market)
                except Exception as e:
                    self.logger_warning(f"THS query_orders({market}) failed: {e}")
                    continue
            row = self._find_row(reply, counter_no)
            if row:
                return self._row_to_order(orderid, row)
        return None

    def query_contract(self) -> List[ContractData]:
        """Contract table is static for A-shares; derive from what we hold."""
        if self._client is None:
            return []
        contracts: List[ContractData] = []
        seen = set()
        for market in ("2", "1"):
            with self._lock:
                try:
                    reply = self._client.query_positions(market=market)
                except Exception:
                    continue
            kv = self._as_kv(reply)
            code = normalize_symbol(str(_pick(kv, "zqdm", "code", "symbol") or ""))
            if not code or code in seen:
                continue
            seen.add(code)
            contracts.append(
                ContractData(
                    symbol=code,
                    name=str(_pick(kv, "zqmc", "name") or code),
                    product_class=ProductClass.EQUITY,
                    exchange=market_of(code),
                    gateway_name=self.gateway_name,
                )
            )
        return contracts

    # ==================== Trading (blocked) ====================

    def send_order(self, req: Dict[str, Any]) -> Optional[str]:
        """Place one order. Returns our client_order_id (never the counter no).

        Safety model (order placement is NOT idempotent):
            1. kill switch / master switch / trading window guards;
            2. dedup: an identical order already submitted by us within
               `dedup_window` is adopted instead of re-sent;
            3. reconcile-before-send: if 当日委托 already holds a matching live
               order for this symbol/side/volume, adopt its 委托编号;
            4. submit with the counter's automatic retry suppressed;
            5. on an ambiguous failure, reconcile first and only resend once
               after `reconcile_grace` seconds.
        """
        if not self._LIVE_TRADING_ENABLED:
            raise NotImplementedError(
                "ThsGateway.send_order is gated off (_LIVE_TRADING_ENABLED=False). "
                "Enable only after ths-trade-client supports cancel (撤单): every "
                "exit path needs it, and an un-cancellable live order is a "
                "position you cannot manage."
            )

        symbol = normalize_symbol(req.get("symbol", ""))
        volume = float(req.get("volume", 0) or 0)
        if not symbol or volume <= 0:
            self.logger_warning(f"THS invalid order request: {req}")
            return None
        direction = req.get("direction", Direction.LONG)
        is_buy = direction == Direction.LONG
        order_type = req.get("order_type", OrderType.MARKET)
        price = float(req.get("price", 0) or 0)

        self._assert_trading_allowed()
        if self._enforce_window and not in_trading_window():
            self.logger_warning(f"THS order rejected locally: outside trading window ({symbol})")
            return None

        orderid = str(req.get("client_order_id") or self._next_client_id())

        # (2) local dedup - same client id seen recently
        if orderid in self._orders:
            return orderid

        # (3) reconcile before sending: adopt a matching live counter order
        adopted = self._find_live_counter_order(symbol, is_buy, volume)
        if adopted:
            self._register(orderid, symbol, is_buy, volume, price, adopted)
            self._publish_pending(orderid, symbol, is_buy, volume, price)
            self.logger_warning(
                f"Adopted existing counter order {adopted} for {symbol} (dedup/reconcile)"
            )
            return orderid

        self._register(orderid, symbol, is_buy, volume, price, "")

        # (4) submit with auto-retry suppressed
        reply, error = self._submit(symbol, is_buy, volume, price, order_type)
        counter_no = extract_counter_no(reply)
        if counter_no:
            self._bind_counter_no(orderid, counter_no)
            self._publish_pending(orderid, symbol, is_buy, volume, price)
            self.logger_info(f"THS order accepted: {orderid} -> 委托编号 {counter_no}")
            return orderid

        # (5) ambiguous: reconcile, then resend at most once
        if error is not None:
            self.logger_warning(f"THS submit ambiguous for {orderid}: {error}")
        time.sleep(min(self._reconcile_grace, 3.0))
        found = self._find_live_counter_order(symbol, is_buy, volume)
        if found:
            self._bind_counter_no(orderid, found)
            self._publish_pending(orderid, symbol, is_buy, volume, price)
            self.logger_info(f"THS order found on reconcile: {orderid} -> {found}")
            return orderid
        if self._orders.get(orderid, {}).get("resent"):
            self.logger_warning(f"THS giving up on {orderid}: resend already attempted")
            return None
        self._orders.setdefault(orderid, {})["resent"] = True
        reply2, error2 = self._submit(symbol, is_buy, volume, price, order_type)
        counter_no = extract_counter_no(reply2)
        if counter_no:
            self._bind_counter_no(orderid, counter_no)
            self._publish_pending(orderid, symbol, is_buy, volume, price)
            return orderid
        self.logger_warning(f"THS submit failed twice for {orderid}: {error2}")
        return None

    def cancel_order(self, req: Dict[str, Any]) -> bool:
        """Blocked: ths-trade-client does not implement 撤单 yet."""
        raise NotImplementedError(
            "ThsGateway.cancel_order is blocked: ths-trade-client has no 撤单; "
            "capture the frame with ths-capture-orders and implement it first."
        )

    # ==================== Order placement machinery ====================

    def _next_client_id(self) -> str:
        self._order_seq += 1
        return f"THS-{int(time.time() * 1000)}-{self._order_seq}"

    def _register(self, orderid: str, symbol: str, is_buy: bool, volume: float,
                  price: float, counter_no: str) -> None:
        self._orders[orderid] = {
            "symbol": symbol, "is_buy": is_buy, "volume": volume, "price": price,
            "counter_no": counter_no, "submitted_at": time.time(), "resent": False,
            "traded": 0.0,
        }
        if counter_no:
            self._bind_counter_no(orderid, counter_no)

    def _bind_counter_no(self, orderid: str, counter_no: str) -> None:
        self._order_map_store[orderid] = counter_no
        self._by_counter[counter_no] = orderid
        self._orders.setdefault(orderid, {})["counter_no"] = counter_no

    def _submit(self, symbol: str, is_buy: bool, volume: float, price: float,
                order_type: Any):
        """One counter call, with the client's auto-retry suppressed.

        TradeClient reconnects and retries a failed request once, which is fine
        for queries and dangerous for orders (a retry can double-buy).
        """
        with self._lock:
            client = self._client
            saved = getattr(client, "auto_reconnect", None)
            if saved is not None:
                try:
                    client.auto_reconnect = False
                except Exception:
                    pass
            try:
                limit = order_type == OrderType.LIMIT and price > 0
                if limit:
                    reply = client.limit_order(symbol, int(volume), price,
                                              is_sell=not is_buy)
                elif is_buy:
                    reply = client.buy_market(symbol, int(volume))
                else:
                    reply = client.sell_market(symbol, int(volume))
                return reply, None
            except Exception as e:  # connection drop, timeout, ...
                return None, e
            finally:
                if saved is not None:
                    try:
                        client.auto_reconnect = saved
                    except Exception:
                        pass

    def _find_live_counter_order(self, symbol: str, is_buy: bool,
                                 volume: float) -> str:
        """Scan 当日委托 for a live order matching this intent (dedup/reconcile)."""
        if self._client is None:
            return ""
        for market in (market_of(symbol), "2", "1"):
            with self._lock:
                try:
                    reply = self._client.query_orders(market=market)
                except Exception:
                    continue
            rows = self._order_rows(reply)
            for row in rows:
                code = normalize_symbol(str(_pick(row, "zqdm", "code") or ""))
                if code != symbol:
                    continue
                side = str(_pick(row, "jybz", "bs") or "b")
                row_buy = side in ("b", "买", "1")
                if row_buy != is_buy:
                    continue
                if abs(_to_float(_pick(row, "wtml", "volume")) - volume) > 1e-6:
                    continue
                if self._status_of(row) in (Status.ALLTRADED, Status.CANCELLED,
                                            Status.REJECTED):
                    continue
                return str(_pick(row, "wtbh", "order_no") or "")
        return ""

    @staticmethod
    def _order_rows(reply: Any) -> List[Dict[str, Any]]:
        """All 委托 rows in a 0326 reply (single kv or a rows list)."""
        if not isinstance(reply, dict):
            return []
        rows = reply.get("rows")
        if isinstance(rows, list) and rows:
            return [r for r in rows if isinstance(r, dict)]
        kv = reply.get("kv")
        return [kv] if isinstance(kv, dict) and kv else []

    def reconcile_orders(self) -> Dict[str, str]:
        """Rebuild order state from 当日委托; returns {counter_no: client_id}."""
        adopted: Dict[str, str] = {}
        if self._client is None:
            return adopted
        for market in ("2", "1"):
            with self._lock:
                try:
                    reply = self._client.query_orders(market=market)
                except Exception:
                    continue
            for row in self._order_rows(reply):
                counter_no = str(_pick(row, "wtbh", "order_no") or "")
                if not counter_no:
                    continue
                known = self._by_counter.get(counter_no)
                if known is None:
                    known = f"THS-EXT-{counter_no}"
                    self._by_counter[counter_no] = known
                    self._order_map_store[known] = counter_no
                    self._orders.setdefault(known, {
                        "symbol": normalize_symbol(str(_pick(row, "zqdm") or "")),
                        "is_buy": str(_pick(row, "jybz", "bs") or "b") in ("b", "买", "1"),
                        "volume": _to_float(_pick(row, "wtml", "volume")),
                        "price": _to_float(_pick(row, "wtjg", "price")),
                        "counter_no": counter_no,
                        "submitted_at": time.time(), "resent": False, "traded": 0.0,
                    })
                adopted[counter_no] = known
        return adopted

    def confirm_order(self, orderid: str, timeout: Optional[float] = None,
                      poll_interval: Optional[float] = None) -> Optional[OrderData]:
        """Poll until terminal (or timeout), publishing status changes and fills."""
        timeout = self._confirm_timeout if timeout is None else timeout
        poll_interval = self._poll_interval if poll_interval is None else poll_interval
        deadline = time.monotonic() + timeout
        last: Optional[OrderData] = None
        while True:
            order = self.query_order({"orderid": orderid})
            if order is not None:
                if self._last_status.get(orderid) != order.status:
                    self._last_status[orderid] = order.status
                    self.on_order(order)
                    rec = self._orders.get(orderid, {})
                    prev = _to_float(rec.get("traded", 0.0))
                    if order.traded > prev:
                        self._orders[orderid]["traded"] = order.traded
                        self.on_trade(_fill_from(order, order.traded - prev))
                    last = order
                if order.status in (Status.ALLTRADED, Status.CANCELLED,
                                    Status.REJECTED):
                    return order
            if time.monotonic() >= deadline:
                return last
            time.sleep(max(0.05, poll_interval))

    # ==================== Quotes ====================

    def _on_push(self, push: Dict[str, Any]) -> None:
        """Counter push (0x50 zlib k=v) → throttled on_tick."""
        kv = push.get("kv") or {}
        code = normalize_symbol(str(kv.get("zqdm", "")))
        if not code:
            return
        last = kv.get("zgj")          # 最高
        price = _to_float(_pick(kv, "zxj", "price"))
        if not price:
            return
        self._quote_cache[code] = {
            "last": price,
            "high": _to_float(kv.get("zgj")),
            "low": _to_float(kv.get("zdj")),
            "open": _to_float(kv.get("open")),
            "volume": _to_float(kv.get("cjl")),
            "amount": _to_float(kv.get("cjje")),
            "ts": time.time(),
        }
        # Throttle: at most one tick per symbol per 0.5s.
        if time.time() - self._last_tick.get(code, 0.0) >= 0.5:
            self._last_tick[code] = time.time()
            self.on_tick(
                TickData(
                    symbol=code,
                    exchange=market_of(code),
                    last_price=price,
                    volume=self._quote_cache[code]["volume"],
                    last_volume=self._quote_cache[code]["volume"],
                    gateway_name=self.gateway_name,
                )
            )

    def get_tick(self, symbol: str) -> Optional[TickData]:
        cached = self._quote_cache.get(normalize_symbol(symbol))
        if not cached:
            return None
        code = normalize_symbol(symbol)
        return TickData(
            symbol=code,
            exchange=market_of(code),
            last_price=cached["last"],
            volume=cached.get("volume", 0.0),
            gateway_name=self.gateway_name,
        )

    # ==================== Helpers ====================

    def _account_id(self) -> str:
        if self._client is None:
            return ""
        try:
            info = self._client.account_info() or {}
            kv = info.get("kv") if isinstance(info, dict) else None
            if kv:
                return str(_pick(kv, "zjzh", "fund_account") or "")
        except Exception:
            pass
        return ""

    def _counter_no(self, orderid: str) -> str:
        """Our orderid -> counter 委托编号."""
        return self._order_map_store.get(orderid, "")

    def _publish_pending(self, orderid: str, symbol: str, is_buy: bool,
                         volume: float, price: float) -> None:
        """Publish the (unconfirmed) NOTTRADED state right after submission."""
        self._emit_order_if_changed(
            OrderData(
                gateway_name=self.gateway_name,
                orderid=orderid,
                symbol=symbol,
                direction=Direction.LONG if is_buy else Direction.SHORT,
                offset=Offset.OPEN,
                type=OrderType.LIMIT if price > 0 else OrderType.MARKET,
                price=price,
                volume=volume,
                traded=0.0,
                status=Status.NOTTRADED,
            )
        )

    def _emit_order_if_changed(self, order: OrderData) -> None:
        if self._last_status.get(order.orderid) == order.status:
            return
        self._last_status[order.orderid] = order.status
        self.on_order(order)

    def _assert_trading_allowed(self) -> None:
        """Kill switch: the marker file disables new orders instantly."""
        if self._kill_switch_file and os.path.exists(self._kill_switch_file):
            raise RuntimeError(
                f"Kill switch engaged ({self._kill_switch_file}); new orders are "
                "disabled. Remove the file to resume."
            )

    @staticmethod
    def _as_kv(reply: Any) -> Dict[str, Any]:
        """Coerce a ths-trade-client reply into a flat key->value dict."""
        if not isinstance(reply, dict):
            return {}
        if isinstance(reply.get("kv"), dict):
            return reply["kv"]
        if isinstance(reply.get("fields"), list):
            out = {}
            for item in reply["fields"]:
                try:
                    tag, a, b = item[0], item[1], item[2]
                except Exception:
                    continue
                out[str(tag)] = f"{a}:{b}"
            return out
        return {}

    def _find_row(self, reply: Any, counter_no: str) -> Dict[str, Any]:
        """Locate one 委托 row inside a 0326 reply (defensive)."""
        kv = self._as_kv(reply)
        wtbh = str(_pick(kv, "wtbh", "order_no", "entrust_no") or "")
        if wtbh and wtbh == counter_no:
            return kv
        rows = (reply or {}).get("rows") or []
        for row in rows:
            if isinstance(row, dict) and str(row.get("wtbh", "")) == counter_no:
                return row
        return {}

    def _row_to_order(self, orderid: str, row: Dict[str, Any]) -> OrderData:
        status = self._status_of(row)
        return OrderData(
            gateway_name=self.gateway_name,
            orderid=orderid,
            symbol=normalize_symbol(str(_pick(row, "zqdm", "code") or "")),
            direction=Direction.LONG
            if str(_pick(row, "jybz", "bs") or "b") in ("b", "买", "1")
            else Direction.SHORT,
            offset=Offset.CLOSE
            if str(_pick(row, "jybz", "bs") or "b") in ("s", "卖", "2")
            else Offset.OPEN,
            type=OrderType.LIMIT if _to_float(_pick(row, "wtjg")) > 0 else OrderType.MARKET,
            price=_to_float(_pick(row, "wtjg", "price")),
            volume=_to_float(_pick(row, "wtml", "volume")),
            traded=_to_float(_pick(row, "cjsl", "traded")),
            status=status,
        )

    @staticmethod
    def _fill_from(order: OrderData, delta: float) -> TradeData:
        return TradeData(
            gateway_name=order.gateway_name,
            tradeid=f"{order.orderid}-{order.traded}",
            orderid=order.orderid,
            symbol=order.symbol,
            direction=order.direction,
            offset=order.offset,
            price=order.price,
            volume=delta,
        )

    @staticmethod
    def _status_of(row: Dict[str, Any]) -> Status:
        raw = str(_pick(row, "wtztdm", "status", "statusflag") or "").strip()
        if raw in ("已成交", "已成", "全部成交", "1"):
            return Status.ALLTRADED
        if raw in ("部成", "部分成交", "2"):
            return Status.PARTTRADED
        if raw in ("已撤", "部撤", "3", "4"):
            return Status.CANCELLED
        if raw in ("废单", "已废", "5"):
            return Status.REJECTED
        return Status.NOTTRADED

    @property
    def gateway_type(self) -> str:
        return GatewayType.STOCK