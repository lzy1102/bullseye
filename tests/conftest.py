"""
Test configuration for Bullseye
"""
import pytest
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

@pytest.fixture
def sample_config():
    """Fixture providing sample configuration for testing."""
    return {
        'max_open_trades': 5,
        'stake_currency': 'USDT',
        'stake_amount': 100,
        'dry_run': True,
        'market_type': 'auto',
        'exchange': {
            'name': 'binance',
            'sandbox': True
        },
        'strategy': 'SampleStrategy',
        'timeframe': '5m',
    }


@pytest.fixture
def sample_config_file(tmp_path, sample_config):
    """Fixture providing a sample config YAML file path."""
    config_path = tmp_path / 'config.yaml'
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(sample_config, f)
    return str(config_path)


@pytest.fixture
def sample_dataframe():
    """Fixture providing sample OHLCV data for testing."""
    import pandas as pd
    from datetime import datetime, timedelta

    dates = pd.date_range(start=datetime.now() - timedelta(days=100), periods=100, freq='1h')

    return pd.DataFrame({
        'date': dates,
        'open': [100 + i * 0.1 for i in range(100)],
        'high': [100 + i * 0.1 + 2 for i in range(100)],
        'low': [100 + i * 0.1 - 1 for i in range(100)],
        'close': [100 + i * 0.1 + 1 for i in range(100)],
        'volume': [1000 + i * 10 for i in range(100)],
    })
