"""
Trader Module - Core trading engine and event system

This module contains the core trading infrastructure:
- EventEngine: Event-driven system for handling all events
- MainEngine: Main trading engine managing all gateways
- Object: Data structures for trading (tick, kline, order, trade, position, account, contract)
"""

from .eventengine import EventEngine, Event, EventType
from .engine import MainEngine
from .object import (
    TickData,
    KlineData,
    OrderData,
    OrderType,
    Direction,
    Offset,
    Status,
    TradeData,
    PositionData,
    AccountData,
    ContractData,
    ProductClass,
    OptionType,
)

__all__ = [
    # Event system
    "EventEngine",
    "Event",
    "EventType",
    # Main engine
    "MainEngine",
    # Data objects
    "TickData",
    "KlineData",
    "OrderData",
    "OrderType",
    "Direction",
    "Offset",
    "Status",
    "TradeData",
    "PositionData",
    "AccountData",
    "ContractData",
    "ProductClass",
    "OptionType",
]
