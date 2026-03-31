"""
Bot module - Core trading bot for Bullseye.

Provides the main trading bot class and strategy runner.
"""

from .bot import BullseyeBot
from .strategy_runner import StrategyRunner

__all__ = ["BullseyeBot", "StrategyRunner"]
