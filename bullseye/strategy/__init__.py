"""
Strategy Module - Freqtrade Compatible Strategy Interface

This module provides a 100% compatible implementation of Freqtrade's strategy interface.
All your existing Freqtrade strategies can be used directly without modification.

Key Components:
- IStrategy: Base strategy class (Freqtrade v3 compatible)
- @informative: Decorator for multi-timeframe analysis
- merge_informative_pair(): Helper for merging timeframes
- Hyperoptable Parameters: IntParameter, DecimalParameter, BooleanParameter, CategoricalParameter
"""

from .interface import (
    IStrategy,
    informative,
    merge_informative_pair,
    timeframe_to_minutes,
    timeframe_to_next_date,
    timeframe_to_prev_date,
    stoploss_from_open,
    stoploss_from_absolute,
    BooleanParameter,
    IntParameter,
    DecimalParameter,
    RealParameter,
    CategoricalParameter,
    RunMode,
)

__all__ = [
    # Core interface
    "IStrategy",
    # Decorators and helpers
    "informative",
    "merge_informative_pair",
    "timeframe_to_minutes",
    "timeframe_to_next_date",
    "timeframe_to_prev_date",
    "stoploss_from_open",
    "stoploss_from_absolute",
    # Hyperoptable parameters
    "BooleanParameter",
    "IntParameter",
    "DecimalParameter",
    "RealParameter",
    "CategoricalParameter",
    # Enums
    "RunMode",
]
