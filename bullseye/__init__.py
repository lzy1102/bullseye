"""
Bullseye - Quantitative Trading Framework

A Freqtrade-compatible quantitative trading framework supporting
crypto, stock, and futures markets.

Key Features:
- 100% Freqtrade strategy compatibility
- Multi-market trading (crypto, stock, futures)
- Event-driven architecture
- Unified data format
- Flexible database support (SQLite, PostgreSQL, MySQL)
"""

__version__ = "0.1.0"
__author__ = "Bullseye Contributors"
__license__ = "MIT"

from .trader import MainEngine, EventEngine, Event, EventType
from .strategy import IStrategy
from .gateway import BaseGateway, CcxtGateway, CtpGateway, MiniQmtGateway
from .persistence import Base, Trade, Order, PairLock

__all__ = [
    # Version info
    "__version__",
    # Core
    "MainEngine",
    "EventEngine",
    "Event",
    "EventType",
    # Strategy
    "IStrategy",
    # Gateway
    "BaseGateway",
    "CcxtGateway",
    "CtpGateway",
    "MiniQmtGateway",
    # Persistence
    "Base",
    "Trade",
    "Order",
    "PairLock",
]
