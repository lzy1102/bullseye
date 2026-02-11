"""
Market Adapter - Market data adapter for different markets

Converts different market data formats to unified format compatible with Freqtrade.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class MarketType(Enum):
    """Market type enumeration"""
    AUTO = "auto"
    CRYPTO = "crypto"
    STOCK = "stock"
    FUTURE = "future"
    OPTION = "option"


class BaseMarketAdapter(ABC):
    """
    Market adapter base class

    Responsible for converting different market data formats to Freqtrade-compatible format.
    """

    def __init__(self, market_type: MarketType):
        self.market_type = market_type
        self._pair_separator = "/"

    @abstractmethod
    def normalize_pair(self, pair: str) -> str:
        """
        Normalize trading pair to BASE/QUOTE format

        Args:
            pair: Original trading pair

        Returns:
            Normalized trading pair (BASE/QUOTE)
        """
        pass

    @abstractmethod
    def pair_to_symbol(self, pair: str, market_type: Optional[str] = None) -> str:
        """
        Convert Freqtrade format pair to market-specific format

        Args:
            pair: Freqtrade format pair (BASE/QUOTE)
            market_type: Market type (spot/swap/future)

        Returns:
            Market-specific trading pair
        """
        pass

    @abstractmethod
    def get_pair_separator(self) -> str:
        """Get pair separator"""
        pass

    @abstractmethod
    def timeframes(self) -> List[str]:
        """Get supported timeframes"""
        pass

    def validate_pair(self, pair: str) -> bool:
        """Validate trading pair"""
        try:
            normalized = self.normalize_pair(pair)
            return "/" in normalized and len(normalized.split("/")) == 2
        except Exception:
            return False

    def get_base_quote(self, pair: str) -> Tuple[str, str]:
        """
        Get base and quote currencies

        Args:
            pair: Normalized trading pair

        Returns:
            (base, quote) tuple
        """
        parts = pair.split("/")
        if len(parts) == 2:
            return parts[0], parts[1]
        raise ValueError(f"Invalid pair format: {pair}")


class CryptoMarketAdapter(BaseMarketAdapter):
    """Cryptocurrency market adapter"""

    def __init__(self):
        super().__init__(MarketType.CRYPTO)
        self._pair_separator = "/"

    def normalize_pair(self, pair: str) -> str:
        """Normalize crypto trading pair to BASE/QUOTE"""
        # Already in standard format
        if "/" in pair:
            parts = pair.split("/")
            if len(parts) == 2:
                return f"{parts[0].upper()}/{parts[1].upper()}"

        # CCXT format: BTCUSDT -> BTC/USDT
        pair = pair.upper().replace("-", "")
        quotes = ["USDT", "BUSD", "USD", "EUR", "BTC", "ETH", "BNB"]

        for quote in quotes:
            if pair.endswith(quote):
                base = pair[:-len(quote)]
                if base:
                    return f"{base}/{quote}"

        raise ValueError(f"Cannot parse trading pair: {pair}")

    def pair_to_symbol(self, pair: str, market_type: Optional[str] = None) -> str:
        """Convert to CCXT format"""
        pair = self.normalize_pair(pair)
        base, quote = self.get_base_quote(pair)

        if market_type == "swap":
            return f"{base}/{quote}:{quote}"
        elif market_type == "future":
            return f"{base}/{quote}:YYMMDD"
        else:
            return f"{base}/{quote}"

    def get_pair_separator(self) -> str:
        return "/"

    def timeframes(self) -> List[str]:
        return [
            "1m", "3m", "5m", "15m", "30m",
            "1h", "2h", "4h", "6h", "8h", "12h",
            "1d", "3d", "1w", "1M"
        ]


class StockMarketAdapter(BaseMarketAdapter):
    """Stock market adapter (Chinese A-share)"""

    def __init__(self):
        super().__init__(MarketType.STOCK)
        self._pair_separator = "."

    def normalize_pair(self, pair: str) -> str:
        """
        Normalize stock code to CODE/EXCHANGE format

        Input: 000001.SZ, 000001, sz000001
        Output: 000001/SZ
        """
        pair = pair.upper().strip()

        if "/" in pair:
            code, exchange = pair.split("/")
            return f"{code}/{exchange}"

        if "." in pair:
            code, exchange = pair.split(".")
            return f"{code}/{exchange}"

        if len(pair) == 6 and pair.isdigit():
            if pair[0] in ["6", "8", "9"]:
                return f"{pair}/SH"  # Shanghai
            elif pair[0] in ["0", "2", "3"]:
                return f"{pair}/SZ"  # Shenzhen

        raise ValueError(f"Cannot parse stock code: {pair}")

    def pair_to_symbol(self, pair: str, market_type: Optional[str] = None) -> str:
        """Convert to broker format (CODE.EXCHANGE)"""
        pair = self.normalize_pair(pair)
        code, exchange = self.get_base_quote(pair)
        return f"{code}.{exchange}"

    def get_pair_separator(self) -> str:
        return "."

    def timeframes(self) -> List[str]:
        return ["1m", "5m", "15m", "30m", "1h", "1d", "1w", "1M"]

    def get_name(self, pair: str) -> str:
        """Get stock name"""
        code, _ = self.get_base_quote(self.normalize_pair(pair))
        stock_names = {
            "000001": "平安银行",
            "000002": "万科A",
            "600000": "浦发银行",
            "600036": "招商银行",
        }
        return stock_names.get(code, code)


class FutureMarketAdapter(BaseMarketAdapter):
    """Futures market adapter (Chinese futures)"""

    def __init__(self):
        super().__init__(MarketType.FUTURE)
        self._pair_separator = ""

    def normalize_pair(self, contract: str) -> str:
        """
        Normalize futures contract to PRODUCT/EXPIRY/EXCHANGE format

        Input: AU2506, au2506, AU2506@SHFE
        Output: AU/2506/SHFE
        """
        contract = contract.upper().strip()

        if "/" in contract:
            return contract

        exchange = ""
        if "@" in contract:
            contract, exchange = contract.split("@")

        # Parse: AU2506 -> AU + 2506
        if len(contract) >= 6:
            for i in range(1, 3):
                product = contract[:i]
                if product.isalpha():
                    expiry = contract[i:]
                    if expiry.isdigit() and len(expiry) >= 4:
                        if not exchange:
                            exchange = self._infer_exchange(product)
                        return f"{product}/{expiry}/{exchange}"

        raise ValueError(f"Cannot parse futures contract: {contract}")

    def _infer_exchange(self, product: str) -> str:
        """Infer exchange from product"""
        exchange_map = {
            "AU": "SHFE", "CU": "SHFE", "AL": "SHFE", "ZN": "SHFE",
            "RB": "SHFE", "HC": "SHFE", "BU": "SHFE", "RU": "SHFE",
            "A": "DCE", "M": "DCE", "Y": "DCE", "P": "DCE", "C": "DCE",
            "MA": "CZCE", "SR": "CZCE", "CF": "CZCE", "TA": "CZCE",
        }
        return exchange_map.get(product, "UNKNOWN")

    def pair_to_symbol(self, pair: str, market_type: Optional[str] = None) -> str:
        """Convert to exchange format (PRODUCTEXPIRY)"""
        pair = self.normalize_pair(pair)
        parts = pair.split("/")
        if len(parts) == 3:
            product, expiry, _ = parts
            return f"{product}{expiry}"
        return pair

    def get_pair_separator(self) -> str:
        return ""

    def timeframes(self) -> List[str]:
        return ["1m", "5m", "15m", "30m", "1h", "1d"]

    def get_product_name(self, product: str) -> str:
        """Get product name"""
        product_names = {
            "AU": "黄金", "CU": "铜", "AL": "铝", "ZN": "锌",
            "RB": "螺纹钢", "HC": "热卷", "RU": "橡胶",
            "A": "豆一", "M": "豆粕", "Y": "豆油", "P": "棕榈油",
            "MA": "甲醇", "SR": "白糖", "CF": "棉花",
        }
        return product_names.get(product, product)


class MarketAdapterFactory:
    """Market adapter factory"""

    _adapters: Dict[MarketType, BaseMarketAdapter] = {
        MarketType.CRYPTO: CryptoMarketAdapter(),
        MarketType.STOCK: StockMarketAdapter(),
        MarketType.FUTURE: FutureMarketAdapter(),
    }

    @classmethod
    def get_adapter(cls, market_type: MarketType) -> BaseMarketAdapter:
        """Get market adapter by type"""
        if market_type not in cls._adapters:
            raise ValueError(f"Unsupported market type: {market_type}")
        return cls._adapters[market_type]

    @classmethod
    def auto_detect(cls, pair: str) -> BaseMarketAdapter:
        """
        Auto-detect market type from pair format

        Args:
            pair: Trading pair

        Returns:
            Corresponding market adapter
        """
        # Stock format: 000001.SZ or 6-digit code
        if "." in pair or (len(pair) == 6 and pair.isdigit()):
            return cls._adapters[MarketType.STOCK]

        # Crypto format: BTC/USDT
        if "/" in pair:
            parts = pair.split("/")
            if len(parts) == 2:
                return cls._adapters[MarketType.CRYPTO]

        # Future format: AU2506
        if len(pair) >= 6:
            for i in range(1, 3):
                if pair[:i].isalpha() and pair[i:].isdigit():
                    return cls._adapters[MarketType.FUTURE]

        # Default to crypto
        return cls._adapters[MarketType.CRYPTO]
