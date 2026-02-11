"""
Crypto Gateways - Cryptocurrency exchange gateways using CCXT

Supports all CCXT-compatible exchanges including:
- Binance
- OKX
- Bybit
- Gate.io
- And 100+ more exchanges
"""

from .ccxt_gateway import CcxtGateway

__all__ = ["CcxtGateway"]
