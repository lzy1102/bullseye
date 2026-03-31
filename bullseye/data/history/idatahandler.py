"""
Abstract Data Handler Interface

Defines the interface for data format handlers.
"""
from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd


class IDataHandler(ABC):
    """
    Abstract interface for data format handlers.
    
    All data format handlers must implement this interface.
    """
    
    @abstractmethod
    def ohlcv_get(self, pair: str, timeframe: str) -> Optional[pd.DataFrame]:
        """
        Get OHLCV data for a pair and timeframe.
        
        Args:
            pair: Trading pair (e.g., 'BTC/USDT')
            timeframe: Timeframe (e.g., '5m', '1h')
            
        Returns:
            DataFrame with OHLCV data or None if not found
        """
        pass
    
    @abstractmethod
    def ohlcv_store(self, pair: str, timeframe: str, data: pd.DataFrame) -> None:
        """
        Store OHLCV data for a pair and timeframe.
        
        Args:
            pair: Trading pair
            timeframe: Timeframe
            data: DataFrame with OHLCV data
        """
        pass
    
    @abstractmethod
    def trades_get(self, pair: str) -> Optional[pd.DataFrame]:
        """
        Get trade data for a pair.
        
        Args:
            pair: Trading pair
            
        Returns:
            DataFrame with trade data or None if not found
        """
        pass
    
    @abstractmethod
    def trades_store(self, pair: str, data: pd.DataFrame) -> None:
        """
        Store trade data for a pair.
        
        Args:
            pair: Trading pair
            data: DataFrame with trade data
        """
        pass
    
    def ohlcv_exists(self, pair: str, timeframe: str) -> bool:
        """
        Check if OHLCV data exists for a pair and timeframe.
        
        Args:
            pair: Trading pair
            timeframe: Timeframe
            
        Returns:
            True if data exists, False otherwise
        """
        return self.ohlcv_get(pair, timeframe) is not None
    
    def trades_exists(self, pair: str) -> bool:
        """
        Check if trade data exists for a pair.
        
        Args:
            pair: Trading pair
            
        Returns:
            True if data exists, False otherwise
        """
        return self.trades_get(pair) is not None
