"""
Backtesting Engine for Bullseye

Provides vectorized and iterative backtesting capabilities
compatible with Freqtrade strategies.
"""
from .engine import BacktestEngine
from .result import BacktestResult

__all__ = ['BacktestEngine', 'BacktestResult']
