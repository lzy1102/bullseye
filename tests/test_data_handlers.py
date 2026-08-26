"""
Test data format handlers
"""
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from bullseye.data.history import (
    FeatherDataHandler,
    JSONDataHandler,
    ParquetDataHandler,
)


class TestDataHandlers:
    """Test suite for data format handlers."""

    def test_feather_handler_init(self, tmp_path):
        """Test FeatherDataHandler initialization."""
        handler = FeatherDataHandler(data_dir=str(tmp_path))
        assert handler.data_dir == tmp_path
        assert tmp_path.exists()

    def test_json_handler_init(self, tmp_path):
        """Test JSONDataHandler initialization."""
        handler = JSONDataHandler(data_dir=str(tmp_path))
        assert handler.data_dir == tmp_path
        assert tmp_path.exists()

    def test_parquet_handler_init(self, tmp_path):
        """Test ParquetDataHandler initialization."""
        handler = ParquetDataHandler(data_dir=str(tmp_path))
        assert handler.data_dir == tmp_path
        assert tmp_path.exists()

    def test_feather_store_and_retrieve(self, tmp_path):
        """Test Feather store and retrieve operations."""
        handler = FeatherDataHandler(data_dir=str(tmp_path))

        df = pd.DataFrame({
            'open': [1, 2, 3],
            'high': [2, 3, 4],
            'low': [1, 2, 3],
            'close': [1.5, 2.5, 3.5],
            'volume': [100, 200, 300],
        })

        pair = 'BTC/USDT'
        timeframe = '5m'

        handler.ohlcv_store(pair, timeframe, df)

        retrieved_df = handler.ohlcv_get(pair, timeframe)
        assert retrieved_df is not None
        pd.testing.assert_frame_equal(df, retrieved_df)

        assert handler.ohlcv_exists(pair, timeframe)

    def test_json_store_and_retrieve(self, tmp_path):
        """Test JSON store and retrieve operations."""
        handler = JSONDataHandler(data_dir=str(tmp_path))

        df = pd.DataFrame({
            'open': [1, 2, 3],
            'high': [2, 3, 4],
            'low': [1, 2, 3],
            'close': [1.5, 2.5, 3.5],
            'volume': [100, 200, 300],
        })

        pair = 'ETH/USDT'
        timeframe = '1h'

        handler.ohlcv_store(pair, timeframe, df)

        retrieved_df = handler.ohlcv_get(pair, timeframe)
        assert retrieved_df is not None
        pd.testing.assert_frame_equal(df, retrieved_df)

        assert handler.ohlcv_exists(pair, timeframe)

    def test_parquet_store_and_retrieve(self, tmp_path):
        """Test Parquet store and retrieve operations."""
        handler = ParquetDataHandler(data_dir=str(tmp_path))

        df = pd.DataFrame({
            'open': [1, 2, 3],
            'high': [2, 3, 4],
            'low': [1, 2, 3],
            'close': [1.5, 2.5, 3.5],
            'volume': [100, 200, 300],
        })

        pair = 'BNB/USDT'
        timeframe = '4h'

        handler.ohlcv_store(pair, timeframe, df)

        retrieved_df = handler.ohlcv_get(pair, timeframe)
        assert retrieved_df is not None
        pd.testing.assert_frame_equal(df, retrieved_df)

        assert handler.ohlcv_exists(pair, timeframe)

    def test_trades_store_and_retrieve(self, tmp_path):
        """Test trades store and retrieve operations."""
        handler = FeatherDataHandler(data_dir=str(tmp_path))

        df = pd.DataFrame({
            'trade_id': [1, 2, 3],
            'pair': ['BTC/USDT', 'ETH/USDT', 'BNB/USDT'],
            'profit': [10.5, -5.2, 25.3],
        'status': ['closed', 'closed', 'closed'],
        'entry_tag': ['signal1', 'signal2', 'signal3'],
        'exit_tag': ['roi', 'roi', 'roi'],
        'open_date': pd.date_range(start='2024-01-01', periods=3, freq='D').tolist(),
            'close_date': pd.date_range(start='2024-01-01', periods=3, freq='D').tolist(),
        'open_rate': [100, 200, 300],
            'close_rate': [110, 210, 310],
        'amount': [0.1, 0.2, 0.3],
        'profit_percent': [10.5, -2.6, 8.4],
        'exit_reason': ['roi', 'roi', 'roi'],
            'exit_type': ['roi', 'roi', 'roi'],
        'open_date': pd.date_range(start='2024-01-01', periods=3, freq='D').tolist(),
            'close_date': pd.date_range(start='2024-01-01', periods=3, freq='D').tolist(),
        'open_rate': [100, 200, 300],
        'close_rate': [110, 210, 310],
        'amount': [0.1, 0.2, 0.3],
        'profit_percent': [10.5, -2.6, 8.4],
        'exit_reason': ['roi', 'roi', 'roi'],
        'exit_type': ['roi', 'roi', 'roi'],
    })

        for pair in ['BTC/USDT', 'ETH/USDT', 'BNB/USDT']:
            handler.trades_store(pair, df[df['pair'] == pair])
            retrieved_df = handler.trades_get(pair)
            assert retrieved_df is not None
            pd.testing.assert_frame_equal(df[df['pair'] == pair], retrieved_df)
            assert handler.trades_exists(pair)
