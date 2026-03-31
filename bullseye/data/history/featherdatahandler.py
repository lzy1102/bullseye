"""
Feather Data Handler

Handles data storage and retrieval in Feather format.
"""
import pandas as pd
from pathlib import Path
from typing import Optional

from .idatahandler import IDataHandler


class FeatherDataHandler(IDataHandler):
    """
    Data handler for Feather format.
    
    Feather is a fast, efficient format for storing tabular data.
    """
    
    def __init__(self, data_dir: str = "user_data/data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_ohlcv_path(self, pair: str, timeframe: str) -> Path:
        """Get the file path for OHLCV data."""
        filename = f"{pair.replace('/', '_')}-{timeframe}.feather"
        return self.data_dir / filename
    
    def _get_trades_path(self, pair: str) -> Path:
        """Get the file path for trade data."""
        filename = f"{pair.replace('/', '_')}-trades.feather"
        return self.data_dir / filename
    
    def ohlcv_get(self, pair: str, timeframe: str) -> Optional[pd.DataFrame]:
        """
        Get OHLCV data from Feather file.
        
        Args:
            pair: Trading pair
            timeframe: Timeframe
            
        Returns:
            DataFrame with OHLCV data or None
        """
        filepath = self._get_ohlcv_path(pair, timeframe)
        
        if not filepath.exists():
            return None
        
        try:
            return pd.read_feather(filepath)
        except Exception as e:
            print(f"Error reading Feather file {filepath}: {e}")
            return None
    
    def ohlcv_store(self, pair: str, timeframe: str, data: pd.DataFrame) -> None:
        """
        Store OHLCV data to Feather file.
        
        Args:
            pair: Trading pair
            timeframe: Timeframe
            data: DataFrame with OHLCV data
        """
        filepath = self._get_ohlcv_path(pair, timeframe)
        
        try:
            data.to_feather(filepath)
        except Exception as e:
            print(f"Error writing Feather file {filepath}: {e}")
    
    def trades_get(self, pair: str) -> Optional[pd.DataFrame]:
        """
        Get trade data from Feather file.
        
        Args:
            pair: Trading pair
            
        Returns:
            DataFrame with trade data or None
        """
        filepath = self._get_trades_path(pair)
        
        if not filepath.exists():
            return None
        
        try:
            return pd.read_feather(filepath)
        except Exception as e:
            print(f"Error reading Feather file {filepath}: {e}")
            return None
    
    def trades_store(self, pair: str, data: pd.DataFrame) -> None:
        """
        Store trade data to Feather file.
        
        Args:
            pair: Trading pair
            data: DataFrame with trade data
        """
        filepath = self._get_trades_path(pair)
        
        try:
            data.to_feather(filepath)
        except Exception as e:
            print(f"Error writing Feather file {filepath}: {e}")
