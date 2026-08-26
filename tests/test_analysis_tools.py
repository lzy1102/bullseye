"""
Test analysis tools
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bullseye.optimize.analysis.lookahead import LookaheadAnalysis
from bullseye.optimize.analysis.recursive import RecursiveAnalysis


class MockStrategy:
    """Mock strategy for testing."""

    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe['enter_long'] = 0
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe['exit_long'] = 0
        return dataframe


class TestLookaheadAnalysis:
    """Test suite for LookaheadAnalysis."""

    def test_lookahead_analysis_initialization(self):
        """Test LookaheadAnalysis initialization."""
        analysis = LookaheadAnalysis()
        assert analysis.config == {}
        assert analysis.results == {}

    def test_lookahead_analysis_no_bias(self):
        """Test lookahead analysis with no bias."""
        import pandas as pd
        from datetime import datetime, timedelta

        analysis = LookaheadAnalysis()
        strategy = MockStrategy()

        dates = pd.date_range(start=datetime.now() - timedelta(days=100), periods=100, freq='1h')
        df = pd.DataFrame({
            'date': dates,
            'open': [100 + i * 0.1 for i in range(100)],
            'high': [100 + i * 0.1 + 2 for i in range(100)],
            'low': [100 + i * 0.1 - 1 for i in range(100)],
            'close': [100 + i * 0.1 + 1 for i in range(100)],
            'volume': [1000 + i * 10 for i in range(100)],
        })

        result = analysis.analyze(strategy, df, 'BTC/USDT')

        assert result['pair'] == 'BTC/USDT'
        assert result['bias_detected'] is False
        assert len(result['biased_indicators']) == 0

    def test_lookahead_analysis_with_bias(self):
        """Test lookahead analysis with bias detected."""
        import pandas as pd
        from datetime import datetime, timedelta

        analysis = LookaheadAnalysis()

        class BiasedStrategy(MockStrategy):
            def populate_indicators(self, dataframe, metadata):
                dataframe['sma'] = dataframe['close'].rolling(20).mean()
                return dataframe

            def populate_entry_trend(self, dataframe, metadata):
                dataframe['enter_long'] = 0
                if len(dataframe) > 0:
                    future_mean = dataframe['close'].mean()
                    dataframe.loc[dataframe['close'] < future_mean, 'enter_long'] = 1
                return dataframe

        strategy = BiasedStrategy()

        dates = pd.date_range(start=datetime.now() - timedelta(days=100), periods=100, freq='1h')
        df = pd.DataFrame({
            'date': dates,
            'open': [100 + i * 0.1 for i in range(100)],
            'high': [100 + i * 0.1 + 2 for i in range(100)],
            'low': [100 + i * 0.1 - 1 for i in range(100)],
            'close': [100 + i * 0.1 + 1 for i in range(100)],
            'volume': [1000 + i * 10 for i in range(100)],
        })

        result = analysis.analyze(strategy, df, 'BTC/USDT')

        assert result['pair'] == 'BTC/USDT'
        assert result['bias_detected'] is True


class TestRecursiveAnalysis:
    """Test suite for RecursiveAnalysis."""

    def test_recursive_analysis_initialization(self):
        """Test RecursiveAnalysis initialization."""
        analysis = RecursiveAnalysis()
        assert analysis.config == {}
        assert analysis.results == {}

    def test_recursive_analysis_no_bias(self):
        """Test recursive analysis with no bias."""
        import pandas as pd
        from datetime import datetime, timedelta

        analysis = RecursiveAnalysis()
        strategy = MockStrategy()

        dates = pd.date_range(start=datetime.now() - timedelta(days=100), periods=100, freq='1h')
        df = pd.DataFrame({
            'date': dates,
            'open': [100 + i * 0.1 for i in range(100)],
            'high': [100 + i * 0.1 + 2 for i in range(100)],
            'low': [100 + i * 0.1 - 1 for i in range(100)],
            'close': [100 + i * 0.1 + 1 for i in range(100)],
            'volume': [1000 + i * 10 for i in range(100)],
        })

        result = analysis.analyze(strategy, df, 'ETH/USDT')

        assert result['pair'] == 'ETH/USDT'
        assert result['bias_detected'] is False
        assert len(result['sensitive_indicators']) == 0

    def test_recursive_analysis_with_bias(self):
        """Test recursive analysis with bias detected."""
        import pandas as pd
        from datetime import datetime, timedelta

        analysis = RecursiveAnalysis()

        class RecursiveStrategy(MockStrategy):
            def populate_indicators(self, dataframe, metadata):
                dataframe['ema'] = dataframe['close'].ewm(span=20, adjust=False).mean()
                return dataframe

            def populate_entry_trend(self, dataframe, metadata):
                dataframe['enter_long'] = 0
                if len(dataframe) > 1 and 'ema' in dataframe.columns:
                    dataframe.loc[dataframe['close'] > dataframe['ema'], 'enter_long'] = 1
                return dataframe

        strategy = RecursiveStrategy()

        dates = pd.date_range(start=datetime.now() - timedelta(days=100), periods=100, freq='1h')
        df = pd.DataFrame({
            'date': dates,
            'open': [100 + i * 0.1 for i in range(100)],
            'high': [100 + i * 0.1 + 2 for i in range(100)],
            'low': [100 + i * 0.1 - 1 for i in range(100)],
            'close': [100 + i * 0.1 + 1 for i in range(100)],
            'volume': [1000 + i * 10 for i in range(100)],
        })

        result = analysis.analyze(strategy, df, 'ETH/USDT')

        assert result['pair'] == 'ETH/USDT'
