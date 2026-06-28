"""
CTP Gateway - Chinese futures market gateway using openctp-ctp

Full implementation connecting to CTP protocol (综合交易平台).
Compatible with SimNow simulation environment for testing.

Dependencies:
    pip install openctp-ctp==6.7.11.*

Architecture:
    CtpGateway(BaseGateway)
    ├── _MdSpi(mdapi.CThostFtdcMdSpi) → 行情回调 → on_tick()
    └── _TdSpi(tdapi.CThostFtdcTraderSpi) → 交易回调 → on_order/on_trade/...
"""
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...trader.eventengine import EventEngine, EventType
from ...trader.object import (
    AccountData,
    ContractData,
    Direction,
    KlineData,
    Offset,
    OrderBookData,
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
    from openctp_ctp import thostmduserapi as mdapi
    from openctp_ctp import thosttraderapi as tdapi

    CTP_AVAILABLE = True
except ImportError:
    CTP_AVAILABLE = False

import logging

logger = logging.getLogger(__name__)

# =========================================================================
# CTP → Bullseye enum mappings
# =========================================================================

# Exchange
EXCHANGE_CTP2VT: Dict[str, str] = {
    "CFFEX": "CFFEX",
    "SHFE": "SHFE",
    "CZCE": "CZCE",
    "DCE": "DCE",
    "INE": "INE",
    "GFEX": "GFEX",
}

# Direction
DIRECTION_VT2CTP: Dict[Direction, str] = {
    Direction.LONG: "0",
    Direction.SHORT: "1",
}
DIRECTION_CTP2VT: Dict[str, Direction] = {v: k for k, v in DIRECTION_VT2CTP.items()}

# Offset (开平)
OFFSET_VT2CTP: Dict[Offset, str] = {
    Offset.OPEN: "0",
    Offset.CLOSE: "3",
    Offset.CLOSETODAY: "1",
    Offset.CLOSEYESTERDAY: "2",
}
OFFSET_CTP2VT: Dict[str, Offset] = {v: k for k, v in OFFSET_VT2CTP.items()}

# Order type
ORDERTYPE_VT2CTP: Dict[OrderType, str] = {
    OrderType.LIMIT: "2",
    OrderType.MARKET: "1",
}
ORDERTYPE_CTP2VT: Dict[str, OrderType] = {v: k for k, v in ORDERTYPE_VT2CTP.items()}

# Order status
STATUS_CTP2VT: Dict[str, Status] = {
    "0": Status.NOTTRADED,
    "1": Status.PARTTRADED,
    "2": Status.ALLTRADED,
    "3": Status.CANCELLED,
    "4": Status.CANCELLED,
    "5": Status.REJECTED,
    "z": Status.NOTTRADED,
}

# Product class
PRODUCT_CTP2VT: Dict[str, ProductClass] = {
    "1": ProductClass.FUTURES,
    "2": ProductClass.OPTIONS,
    "3": ProductClass.OPTIONS,
    "4": ProductClass.FUTURES,
}

CHINA_TZ_STR = "Asia/Shanghai"


# =========================================================================
# CtpGateway
# =========================================================================


class CtpGateway(BaseGateway):
    """CTP Futures Trading Gateway.

    Connects to CTP protocol via openctp-ctp (SWIG Python wrapper).
    Supports both real trading and SimNow simulation.

    Usage:
        gw = CtpGateway(event_engine)
        gw.connect(
            user_id="your_id",
            password="your_pwd",
            broker_id="9999",
            td_address="tcp://180.168.146.187:10130",
            md_address="tcp://180.168.146.187:10131",
            auth_code="",
            app_id="",
        )
    """

    def __init__(self, event_engine: EventEngine) -> None:
        super().__init__(event_engine, "CTP")
        self._md_api = None
        self._td_api = None
        self._md_spi: Optional["_MdSpi"] = None
        self._td_spi: Optional["_TdSpi"] = None

        # Config
        self._user_id: str = ""
        self._password: str = ""
        self._broker_id: str = ""
        self._auth_code: str = ""
        self._app_id: str = ""

        # State
        self._md_login: bool = False
        self._td_login: bool = False
        self._subscribed_symbols: List[str] = []

    # =====================================================================
    # BaseGateway abstract methods
    # =====================================================================

    def connect(self, **kwargs) -> None:
        """Connect to CTP broker.

        Required kwargs:
            user_id: Investor ID
            password: Password
            broker_id: Broker ID (SimNow: "9999")
            td_address: Trading server address (e.g. tcp://180.168.146.187:10130)
            md_address: Market data server address (e.g. tcp://180.168.146.187:10131)
        Optional kwargs:
            auth_code: Auth code for real trading
            app_id: Application ID
            con_dir: Connection flow directory (default: ./ctp_con)
        """
        if not CTP_AVAILABLE:
            raise ImportError(
                "openctp-ctp is required. Install with: "
                "pip install openctp-ctp==6.7.11.* "
                "-i https://pypi.tuna.tsinghua.edu.cn/simple"
            )

        self._user_id = str(kwargs.get("user_id", ""))
        self._password = str(kwargs.get("password", ""))
        self._broker_id = str(kwargs.get("broker_id", "9999"))
        self._auth_code = str(kwargs.get("auth_code", ""))
        self._app_id = str(kwargs.get("app_id", ""))

        td_addr = self._ensure_protocol(kwargs.get("td_address", ""))
        md_addr = self._ensure_protocol(kwargs.get("md_address", ""))

        con_dir = str(kwargs.get("con_dir", "./ctp_con"))
        Path(con_dir).mkdir(parents=True, exist_ok=True)

        # --- Market data API ---
        md_flow_path = str(Path(con_dir) / "Md").encode()
        self._md_api = mdapi.CThostFtdcMdApi.CreateFtdcMdApi(md_flow_path)
        self._md_spi = _MdSpi(self)
        self._md_spi.api = self._md_api
        self._md_api.RegisterSpi(self._md_spi)
        self._md_api.RegisterFront(md_addr.encode())
        self._md_api.Init()

        # --- Trader API ---
        td_flow_path = str(Path(con_dir) / "Td").encode()
        self._td_api = tdapi.CThostFtdcTraderApi.CreateFtdcTraderApi(td_flow_path)
        self._td_spi = _TdSpi(self)
        self._td_spi.api = self._td_api
        self._td_api.RegisterSpi(self._td_spi)
        self._td_api.RegisterFront(td_addr.encode())
        self._td_api.SubscribePrivateTopic(0)
        self._td_api.SubscribePublicTopic(0)
        self._td_api.Init()

        self._connected = True
        self.event_engine.publish(
            EventType.EVENT_GATEWAY_CONNECT, None, self.gateway_name
        )
        self.on_log(f"CTP connecting to {td_addr} / {md_addr} ...")
        logger.info("CTP gateway initiated: user=%s broker=%s", self._user_id, self._broker_id)

    def close(self) -> None:
        """Disconnect from CTP broker."""
        if self._md_api:
            self._md_api.Release()
            self._md_api = None
        if self._td_api:
            self._td_api.Release()
            self._td_api = None
        self._connected = False
        self._md_login = False
        self._td_login = False
        self.event_engine.publish(
            EventType.EVENT_GATEWAY_DISCONNECT, None, self.gateway_name
        )
        self.on_log("CTP disconnected")

    def send_order(self, req: Dict[str, Any]) -> str:
        """Send order to CTP.

        req keys: symbol, direction, offset, order_type, price, volume, reference
        Returns: vt_orderid string
        """
        if not self._td_spi or not self._td_api:
            self.on_log("CTP trader not ready")
            return ""

        field = tdapi.CThostFtdcInputOrderField()
        field.BrokerID = self._broker_id.encode()
        field.InvestorID = self._user_id.encode()
        field.UserID = self._user_id.encode()
        field.InstrumentID = str(req["symbol"]).encode()
        field.ExchangeID = str(req.get("exchange", "")).encode()
        field.LimitPrice = float(req.get("price", 0))
        field.VolumeTotalOriginal = int(req.get("volume", 0))
        field.MinVolume = 1
        field.IsAutoSuspend = 0
        field.UserForceClose = 0

        # Direction
        direction_enum = req.get("direction", Direction.LONG)
        field.Direction = DIRECTION_VT2CTP.get(direction_enum, "0").encode()

        # Offset (open / close)
        offset_enum = req.get("offset", Offset.OPEN)
        field.CombOffsetFlag = OFFSET_VT2CTP.get(offset_enum, "0").encode()

        # Order type
        order_type_val = req.get("order_type", OrderType.LIMIT)
        field.OrderPriceType = ORDERTYPE_VT2CTP.get(order_type_val, "2").encode()

        # Other required fields
        field.CombHedgeFlag = b"1"       # Speculation
        field.ContingentCondition = b"1"  # Immediately
        field.ForceCloseReason = b"0"     # Not force close
        field.TimeCondition = b"3"        # GFD
        field.VolumeCondition = b"2"      # AV
        field.OrderRef = str(self._td_spi._order_ref).encode()

        n = self._td_api.ReqOrderInsert(field, 0)
        if n != 0:
            self.on_log(f"CTP ReqOrderInsert failed: error_code={n}")
            return ""

        order_ref = self._td_spi._order_ref
        vt_orderid = f"{self._td_spi._front_id}_{self._td_spi._session_id}_{order_ref}"
        self._td_spi._order_ref += 1
        return vt_orderid

    def cancel_order(self, req: Dict[str, Any]) -> bool:
        """Cancel an order on CTP.

        req keys: orderid (format: frontid_sessionid_orderref), symbol
        """
        if not self._td_spi or not self._td_api:
            return False

        try:
            front_id, session_id, order_ref = str(req["orderid"]).split("_")
        except ValueError:
            self.on_log(f"Invalid orderid format: {req.get('orderid')}")
            return False

        field = tdapi.CThostFtdcInputOrderActionField()
        field.BrokerID = self._broker_id.encode()
        field.InvestorID = self._user_id.encode()
        field.UserID = self._user_id.encode()
        field.OrderRef = order_ref.encode()
        field.FrontID = int(front_id)
        field.SessionID = int(session_id)
        field.ActionFlag = b"0"          # Delete
        field.InstrumentID = str(req.get("symbol", "")).encode()
        field.ExchangeID = str(req.get("exchange", "")).encode()
        field.LimitPrice = 0
        field.VolumeChange = 0

        n = self._td_api.ReqOrderAction(field, 0)
        return n == 0

    def query_account(self) -> Optional[AccountData]:
        """Query account info (async – returns cached if available)."""
        if not self._td_spi or not self._td_api:
            return None
        # Request async query; result arrives via OnRspQryTradingAccount callback
        ctp_req = tdapi.CThostFtdcQryTradingAccountField()
        ctp_req.BrokerID = self._broker_id.encode()
        ctp_req.InvestorID = self._user_id.encode()
        self._td_api.ReqQryTradingAccount(ctp_req, 0)
        return self._td_spi._cached_account

    def query_position(self) -> List[PositionData]:
        """Query positions (async – returns cached if available)."""
        if not self._td_spi or not self._td_api:
            return []
        ctp_req = tdapi.CThostFtdcQryInvestorPositionField()
        ctp_req.BrokerID = self._broker_id.encode()
        ctp_req.InvestorID = self._user_id.encode()
        self._td_api.ReqQryInvestorPosition(ctp_req, 0)
        return list(self._td_spi._cached_positions.values())

    def query_order(self, req: Dict[str, Any]) -> Optional[OrderData]:
        """Query a specific order."""
        if not self._td_spi:
            return None
        try:
            _, _, order_ref = str(req["orderid"]).split("_")
        except (ValueError, KeyError):
            return None
        return self._td_spi._orders.get(order_ref)

    def query_contract(self) -> List[ContractData]:
        """Query contracts (async – returns cached if available)."""
        if not self._td_spi or not self._td_api:
            return []
        # Request query; results arrive via OnRspQryInstrument callbacks
        self._td_api.ReqQryInstrument({}, 0)
        return list(self._td_spi._contracts.values())

    # =====================================================================
    # Optional methods
    # =====================================================================

    def subscribe_quote(self, symbols: List[str]) -> None:
        """Subscribe to real-time market data."""
        self._subscribed_symbols = list(symbols)
        if self._md_api and self._md_spi and self._md_spi._login_success:
            encoded = [s.encode() for s in symbols]
            self._md_api.SubscribeMarketData(encoded, len(encoded))
            self.on_log(f"Subscribed to {len(symbols)} symbols")

    def unsubscribe_quote(self, symbols: List[str]) -> None:
        """Unsubscribe from market data."""
        if self._md_api:
            encoded = [s.encode() for s in symbols]
            self._md_api.UnSubscribeMarketData(encoded, len(encoded))

    # =====================================================================
    # Helpers
    # =====================================================================

    @staticmethod
    def _ensure_protocol(address: str) -> str:
        """Add tcp:// prefix if no protocol specified."""
        if not address:
            return ""
        for prefix in ("tcp://", "ssl://", "socks://"):
            if address.startswith(prefix):
                return address
        return "tcp://" + address

    @property
    def gateway_type(self) -> str:
        return GatewayType.FUTURE


# =========================================================================
# MdSpi – Market Data callback handler
# =========================================================================


class _MdSpi(mdapi.CThostFtdcMdSpi if CTP_AVAILABLE else object):
    """CTP Market Data SPI – bridges CTP callbacks to Bullseye events."""

    def __init__(self, gateway: CtpGateway) -> None:
        if CTP_AVAILABLE:
            mdapi.CThostFtdcMdSpi.__init__(self)
        self.gw: CtpGateway = gateway
        self.api = None  # type: ignore[assignment]
        self._login_success: bool = False

    def OnFrontConnected(self) -> None:
        """Connection established → auto login."""
        self.gw.on_log("CTP market data connected")
        req = mdapi.CThostFtdcReqUserLoginField()
        req.BrokerID = self.gw._broker_id.encode()
        req.UserID = self.gw._user_id.encode()
        req.Password = self.gw._password.encode()
        self.api.ReqUserLogin(req, 0)

    def OnFrontDisconnected(self, nReason: int) -> None:
        """Connection lost."""
        self._login_success = False
        self.gw.on_log(f"CTP market data disconnected (reason={nReason})")

    def OnRspUserLogin(
        self,
        pRspUserLogin,
        pRspInfo,
        nRequestID: int,
        bIsLast: bool,
    ) -> None:
        """Login response."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.gw.on_log(
                f"CTP market data login failed: [{pRspInfo.ErrorID}] "
                f"{pRspInfo.ErrorMsg.decode('gbk')}"
            )
            return

        self._login_success = True
        self.gw._md_login = True
        self.gw.on_log(f"CTP market data login success (trading_day={pRspUserLogin.TradingDay})")

        # Re-subscribe previously cached symbols
        if self.gw._subscribed_symbols:
            encoded = [s.encode() for s in self.gw._subscribed_symbols]
            self.api.SubscribeMarketData(encoded, len(encoded))

    def OnRspSubMarketData(
        self,
        pSpecificInstrument,
        pRspInfo,
        nRequestID: int,
        bIsLast: bool,
    ) -> None:
        """Subscription response."""
        if pRspInfo and pRspInfo.ErrorID != 0:
            symbol = pSpecificInstrument.InstrumentID.decode()
            self.gw.on_log(
                f"Subscribe failed for {symbol}: "
                f"[{pRspInfo.ErrorID}] {pRspInfo.ErrorMsg.decode('gbk')}"
            )

    def OnRspUnSubMarketData(
        self,
        pSpecificInstrument,
        pRspInfo,
        nRequestID: int,
        bIsLast: bool,
    ) -> None:
        """Unsubscription response."""
        pass

    def OnRtnDepthMarketData(self, pDepthMarketData) -> None:
        """Real-time tick data pushed from exchange."""
        if not pDepthMarketData:
            return

        symbol = pDepthMarketData.InstrumentID.decode()
        if not symbol:
            return

        tick = TickData(
            gateway_name=self.gw.gateway_name,
            symbol=symbol,
            exchange=EXCHANGE_CTP2VT.get(
                getattr(pDepthMarketData, "ExchangeID", "").decode() if hasattr(pDepthMarketData, "ExchangeID") else "",
                "",
            ),
            last_price=pDepthMarketData.LastPrice,
            volume=pDepthMarketData.Volume,
            turnover=pDepthMarketData.Turnover,
            open_interest=pDepthMarketData.OpenInterest,
            open_price=pDepthMarketData.OpenPrice,
            high_price=pDepthMarketData.HighestPrice,
            low_price=pDepthMarketData.LowestPrice,
            pre_close=pDepthMarketData.PreClosePrice,
            bid_price_1=pDepthMarketData.BidPrice1,
            bid_volume_1=pDepthMarketData.BidVolume1,
            ask_price_1=pDepthMarketData.AskPrice1,
            ask_volume_1=pDepthMarketData.AskVolume1,
            datetime=_parse_ctp_datetime(
                getattr(pDepthMarketData, "ActionDay", ""),
                pDepthMarketData.UpdateTime,
                pDepthMarketData.UpdateMillisec,
            ),
            product_class="futures",
        )
        self.gw.on_tick(tick)

    def OnRspError(self, pRspInfo, nRequestID: int, bIsLast: bool) -> None:
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.gw.on_log(
                f"CTP md error: [{pRspInfo.ErrorID}] "
                f"{pRspInfo.ErrorMsg.decode('gbk')}"
            )


# =========================================================================
# TdSpi – Trading callback handler
# =========================================================================


class _TdSpi(tdapi.CThostFtdcTraderSpi if CTP_AVAILABLE else object):
    """CTP Trading SPI – bridges CTP callbacks to Bullseye events."""

    def __init__(self, gateway: CtpGateway) -> None:
        if CTP_AVAILABLE:
            tdapi.CThostFtdcTraderSpi.__init__(self)
        self.gw: CtpGateway = gateway
        self.api = None  # type: ignore[assignment]
        self._front_id: int = 0
        self._session_id: int = 0
        self._order_ref: int = 0
        self._req_id: int = 0

        # Caches
        self._orders: Dict[str, OrderData] = {}
        self._cached_account: Optional[AccountData] = None
        self._cached_positions: Dict[str, PositionData] = {}
        self._contracts: Dict[str, ContractData] = {}

    # =========================================================================
    # Connection flow
    # =========================================================================

    def OnFrontConnected(self) -> None:
        """Connection established → authenticate or login."""
        self.gw.on_log("CTP trader connected")
        if self.gw._auth_code:
            self._authenticate()
        else:
            self._login()

    def OnFrontDisconnected(self, nReason: int) -> None:
        """Connection lost."""
        self.gw._td_login = False
        self.gw.on_log(f"CTP trader disconnected (reason={nReason})")

    def _authenticate(self) -> None:
        req = tdapi.CThostFtdcReqAuthenticateField()
        req.BrokerID = self.gw._broker_id.encode()
        req.UserID = self.gw._user_id.encode()
        req.AuthCode = self.gw._auth_code.encode()
        req.AppID = self.gw._app_id.encode()
        self.api.ReqAuthenticate(req, 0)

    def _login(self) -> None:
        req = tdapi.CThostFtdcReqUserLoginField()
        req.BrokerID = self.gw._broker_id.encode()
        req.UserID = self.gw._user_id.encode()
        req.Password = self.gw._password.encode()
        self.api.ReqUserLogin(req, 0)

    def OnRspAuthenticate(
        self, pRspAuthenticateField, pRspInfo, nRequestID: int, bIsLast: bool
    ) -> None:
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.gw.on_log(
                f"CTP auth failed: [{pRspInfo.ErrorID}] "
                f"{pRspInfo.ErrorMsg.decode('gbk')}"
            )
            return
        self.gw.on_log("CTP authentication success")
        self._login()

    def OnRspUserLogin(
        self, pRspUserLogin, pRspInfo, nRequestID: int, bIsLast: bool
    ) -> None:
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.gw.on_log(
                f"CTP login failed: [{pRspInfo.ErrorID}] "
                f"{pRspInfo.ErrorMsg.decode('gbk')}"
            )
            return

        self._front_id = pRspUserLogin.FrontID
        self._session_id = pRspUserLogin.SessionID
        self.gw._td_login = True
        self.gw.on_log(
            f"CTP login success (trading_day={pRspUserLogin.TradingDay}, "
            f"front={self._front_id}, session={self._session_id})"
        )

        # Confirm settlement → triggers contract query
        req = tdapi.CThostFtdcSettlementInfoConfirmField()
        req.BrokerID = self.gw._broker_id.encode()
        req.InvestorID = self.gw._user_id.encode()
        self._req_id += 1
        self.api.ReqSettlementInfoConfirm(req, self._req_id)

    def OnRspSettlementInfoConfirm(
        self, pSettlementInfoConfirm, pRspInfo, nRequestID: int, bIsLast: bool
    ) -> None:
        """After settlement confirm → query instruments."""
        self.gw.on_log("CTP settlement confirmed, querying instruments...")
        self._req_id += 1
        self.api.ReqQryInstrument({}, self._req_id)

    # =========================================================================
    # Instrument / Contract
    # =========================================================================

    def OnRspQryInstrument(
        self, pInstrument, pRspInfo, nRequestID: int, bIsLast: bool
    ) -> None:
        if not pInstrument or not pInstrument.InstrumentID:
            return

        symbol = pInstrument.InstrumentID.decode()
        exchange = pInstrument.ExchangeID.decode() if pInstrument.ExchangeID else ""
        product_class = PRODUCT_CTP2VT.get(
            pInstrument.ProductClass.decode() if pInstrument.ProductClass else "1",
            ProductClass.FUTURES,
        )

        contract = ContractData(
            gateway_name=self.gw.gateway_name,
            symbol=symbol,
            exchange=EXCHANGE_CTP2VT.get(exchange, exchange),
            name=pInstrument.InstrumentName.decode() if pInstrument.InstrumentName else symbol,
            product_class=product_class,
            size=pInstrument.VolumeMultiple,
            pricetick=pInstrument.PriceTick,
            min_volume=pInstrument.MinLimitOrderVolume,
            max_volume=pInstrument.MaxLimitOrderVolume,
        )

        self._contracts[symbol] = contract
        self.gw.on_contract(contract)

        if bIsLast:
            self.gw.on_log(f"CTP instrument query complete: {len(self._contracts)} contracts")

    # =========================================================================
    # Order
    # =========================================================================

    def OnRtnOrder(self, pOrder) -> None:
        if not pOrder or not pOrder.InstrumentID:
            return

        order_ref = pOrder.OrderRef.decode() if pOrder.OrderRef else ""
        symbol = pOrder.InstrumentID.decode()

        # Determine orderid
        front_id = pOrder.FrontID
        session_id = pOrder.SessionID
        orderid = f"{front_id}_{session_id}_{order_ref}"

        status = STATUS_CTP2VT.get(
            pOrder.OrderStatus.decode() if pOrder.OrderStatus else "z",
            Status.NOTTRADED,
        )

        # Check for rejected insert
        order_status_str = pOrder.OrderStatus.decode() if pOrder.OrderStatus else ""
        submit_status = getattr(pOrder, "OrderSubmitStatus", b"")
        submit_status_str = submit_status.decode() if submit_status else ""
        if order_status_str == "3" and submit_status_str == "4":
            status = Status.REJECTED

        order_type = ORDERTYPE_CTP2VT.get(
            pOrder.OrderPriceType.decode() if pOrder.OrderPriceType else "2",
            OrderType.LIMIT,
        )

        direction = DIRECTION_CTP2VT.get(
            pOrder.Direction.decode() if pOrder.Direction else "",
        )
        offset = OFFSET_CTP2VT.get(
            pOrder.CombOffsetFlag.decode() if pOrder.CombOffsetFlag else "",
        )

        order = self._orders.get(order_ref)
        if not order:
            order = OrderData(
                gateway_name=self.gw.gateway_name,
                orderid=orderid,
                symbol=symbol,
                exchange=EXCHANGE_CTP2VT.get(
                    pOrder.ExchangeID.decode() if pOrder.ExchangeID else "", "",
                ),
                type=order_type,
                direction=direction,
                offset=offset,
                price=pOrder.LimitPrice,
                volume=pOrder.VolumeTotalOriginal,
                traded=pOrder.VolumeTraded,
                status=status,
                datetime=_parse_ctp_datetime(
                    pOrder.InsertDate, pOrder.InsertTime, 0
                ),
            )
            self._orders[order_ref] = order
        else:
            order.traded = pOrder.VolumeTraded
            order.status = status

        self.gw.on_order(order)

    def OnRspOrderInsert(
        self, pInputOrder, pRspInfo, nRequestID: int, bIsLast: bool
    ) -> None:
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.gw.on_log(
                f"CTP order insert failed: [{pRspInfo.ErrorID}] "
                f"{pRspInfo.ErrorMsg.decode('gbk')}"
            )

    # =========================================================================
    # Trade
    # =========================================================================

    def OnRtnTrade(self, pTrade) -> None:
        if not pTrade or not pTrade.InstrumentID:
            return

        order_ref = pTrade.OrderRef.decode() if pTrade.OrderRef else ""
        orderid = f"{pTrade.FrontID}_{pTrade.SessionID}_{order_ref}"

        trade = TradeData(
            gateway_name=self.gw.gateway_name,
            tradeid=pTrade.TradeID.decode() if pTrade.TradeID else "",
            orderid=orderid,
            symbol=pTrade.InstrumentID.decode(),
            exchange=EXCHANGE_CTP2VT.get(
                pTrade.ExchangeID.decode() if pTrade.ExchangeID else "", "",
            ),
            direction=DIRECTION_CTP2VT.get(
                pTrade.Direction.decode() if pTrade.Direction else "",
            ),
            offset=OFFSET_CTP2VT.get(
                pTrade.OffsetFlag.decode() if pTrade.OffsetFlag else "",
            ),
            price=pTrade.Price,
            volume=pTrade.Volume,
            datetime=_parse_ctp_datetime(
                pTrade.TradeDate, pTrade.TradeTime, 0
            ),
        )
        self.gw.on_trade(trade)

    # =========================================================================
    # Account
    # =========================================================================

    def OnRspQryTradingAccount(
        self, pTradingAccount, pRspInfo, nRequestID: int, bIsLast: bool
    ) -> None:
        if not pTradingAccount or not pTradingAccount.AccountID:
            return

        account = AccountData(
            gateway_name=self.gw.gateway_name,
            accountid=pTradingAccount.AccountID.decode(),
            balance=pTradingAccount.Balance,
            available=pTradingAccount.Available,
            frozen=(
                pTradingAccount.FrozenMargin
                + pTradingAccount.FrozenCash
                + pTradingAccount.FrozenCommission
            ),
            margin=pTradingAccount.CurrMargin,
            currency="CNY",
            risk_ratio=(
                pTradingAccount.CurrMargin / pTradingAccount.Balance
                if pTradingAccount.Balance
                else 0
            ),
        )
        self._cached_account = account
        self.gw.on_account(account)

    # =========================================================================
    # Position
    # =========================================================================

    def OnRspQryInvestorPosition(
        self, pInvestorPosition, pRspInfo, nRequestID: int, bIsLast: bool
    ) -> None:
        if not pInvestorPosition or not pInvestorPosition.InstrumentID:
            return

        symbol = pInvestorPosition.InstrumentID.decode()
        posi_direction = (
            pInvestorPosition.PosiDirection.decode()
            if pInvestorPosition.PosiDirection
            else ""
        )
        direction = DIRECTION_CTP2VT.get(posi_direction)

        # Accumulate positions by symbol + direction key
        key = f"{symbol}_{posi_direction}"
        pos = self._cached_positions.get(key)
        if not pos:
            contract = self._contracts.get(symbol)
            size = contract.size if contract else 1.0
            pos = PositionData(
                gateway_name=self.gw.gateway_name,
                symbol=symbol,
                exchange=EXCHANGE_CTP2VT.get(
                    pInvestorPosition.ExchangeID.decode()
                    if pInvestorPosition.ExchangeID
                    else "",
                    "",
                ),
                direction=direction,
                volume=0.0,
                yd_volume=0.0,
                price=0.0,
                pnl=0.0,
            )
            self._cached_positions[key] = pos

        # Accumulate
        position = pInvestorPosition.Position
        pos.volume += position
        pos.pnl += pInvestorPosition.PositionProfit

        # Yesterday position
        today_pos = pInvestorPosition.TodayPosition
        if today_pos == position:
            pos.yd_volume += 0
        else:
            pos.yd_volume += position - today_pos

        # Average price
        if pos.volume > 0:
            contract = self._contracts.get(symbol)
            size = contract.size if contract else 1.0
            existing_cost = pos.price * pos.volume * size
            existing_cost += pInvestorPosition.PositionCost
            pos.price = existing_cost / (pos.volume * size)

        # Frozen
        if direction == Direction.LONG:
            pos.available = pos.volume - (
                pInvestorPosition.ShortFrozen if pInvestorPosition.ShortFrozen else 0
            )
        else:
            pos.available = pos.volume - (
                pInvestorPosition.LongFrozen if pInvestorPosition.LongFrozen else 0
            )

        if bIsLast:
            for p in self._cached_positions.values():
                self.gw.on_position(p)
            self._cached_positions.clear()

    # =========================================================================
    # Order action (cancel) response
    # =========================================================================

    def OnRspOrderAction(
        self, pInputOrderAction, pRspInfo, nRequestID: int, bIsLast: bool
    ) -> None:
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.gw.on_log(
                f"CTP cancel failed: [{pRspInfo.ErrorID}] "
                f"{pRspInfo.ErrorMsg.decode('gbk')}"
            )

    def OnRspError(self, pRspInfo, nRequestID: int, bIsLast: bool) -> None:
        if pRspInfo and pRspInfo.ErrorID != 0:
            self.gw.on_log(
                f"CTP td error: [{pRspInfo.ErrorID}] "
                f"{pRspInfo.ErrorMsg.decode('gbk')}"
            )


# =========================================================================
# Utility functions
# =========================================================================


def _parse_ctp_datetime(
    date_str: bytes, time_str: bytes, millisec: int
) -> Optional[datetime]:
    """Parse CTP's date+time format into a datetime object.

    CTP format: ActionDay/TradeDate = "20240628", UpdateTime = "14:30:05"
    """
    d = date_str.decode().strip() if isinstance(date_str, bytes) else str(date_str)
    t = time_str.decode().strip() if isinstance(time_str, bytes) else str(time_str)
    if not d or not t:
        return None
    try:
        ts = f"{d} {t}.{millisec:03d}"
        return datetime.strptime(ts, "%Y%m%d %H:%M:%S.%f")
    except ValueError:
        try:
            return datetime.strptime(f"{d} {t}", "%Y%m%d %H:%M:%S")
        except ValueError:
            return None
