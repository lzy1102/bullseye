"""
Persistence Module - Database models and connection management

This module provides SQLAlchemy ORM models compatible with Freqtrade database schema.
"""

from .models import (
    Base,
    Trade,
    Order,
    PairLock,
    IndexRecord,
    BacktestResult,
)

__all__ = [
    "Base",
    "Trade",
    "Order",
    "PairLock",
    "IndexRecord",
    "BacktestResult",
]
