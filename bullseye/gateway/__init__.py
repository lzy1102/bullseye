"""
Gateway Module - Trading gateway interfaces

This module provides unified trading interface for different markets:
- Crypto gateways (based on CCXT)
- Stock gateways (Chinese A-share)
- Futures gateways (Chinese futures)

All gateways implement the BaseGateway interface for unified access.
"""

from .base import BaseGateway, GatewayType

# Crypto gateways
from .crypto import CcxtGateway

# Stock gateways
from .stock import MiniQmtGateway, XtpGateway

# Futures gateways
from .future import CtpGateway

__all__ = [
    "BaseGateway",
    "GatewayType",
    "CcxtGateway",
    "MiniQmtGateway",
    "XtpGateway",
    "CtpGateway",
]
