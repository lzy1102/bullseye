"""
Test configuration module
"""
import sys
from pathlib import Path
import tempfile
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from bullseye.configuration import Config


class TestConfiguration:
    """Test suite for Configuration module."""

    def test_config_defaults(self):
        """Test configuration with default values."""
        config = Config()

        assert config.get('max_open_trades') == 3
        assert config.get('stake_currency') == 'USDT'
        assert config.get('stake_amount') == 100
        assert config.get('dry_run') is True
        assert config.get('market_type') == 'auto'

    def test_config_market_type_crypto(self):
        """Test crypto market type configuration."""
        config = Config()
        config.set('market_type', 'crypto')

        assert config.get('market_type') == 'crypto'

    def test_config_market_type_stock(self):
        """Test stock market type configuration."""
        config = Config()
        config.set('market_type', 'stock')

        assert config.get('market_type') == 'stock'

    def test_config_market_type_future(self):
        """Test future market type configuration."""
        config = Config()
        config.set('market_type', 'future')

        assert config.get('market_type') == 'future'

    def test_config_telegram_enabled(self):
        """Test Telegram configuration."""
        config = Config()
        config.set('telegram', {
            'enabled': True,
            'token': 'test_token',
            'chat_id': 'test_chat_id'
        })

        assert config.get('telegram.enabled') is True
        assert config.get('telegram.token') == 'test_token'
        assert config.get('telegram.chat_id') == 'test_chat_id'

    def test_config_api_server_enabled(self):
        """Test API server configuration."""
        config = Config()
        config.set('api_server', {
            'enabled': True,
            'listen_ip': '127.0.0.1',
            'listen_port': 8080
        })

        assert config.get('api_server.enabled') is True
        assert config.get('api_server.listen_ip') == '127.0.0.1'
        assert config.get('api_server.listen_port') == 8080

    def test_config_webhook_enabled(self):
        """Test Webhook configuration."""
        config = Config()
        config.set('webhook', {
            'enabled': True,
            'url': 'https://example.com/webhook',
            'format': 'json',
            'retry_count': 3
        })

        assert config.get('webhook.enabled') is True
        assert config.get('webhook.url') == 'https://example.com/webhook'
        assert config.get('webhook.format') == 'json'
        assert config.get('webhook.retry_count') == 3

    def test_config_from_yaml_file(self):
        """Test loading configuration from a YAML file."""
        config_data = {
            'max_open_trades': 5,
            'stake_currency': 'USDT',
            'stake_amount': 200,
            'dry_run': True,
            'strategy': 'SampleStrategy',
            'exchange': {
                'name': 'binance',
            },
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            yaml.dump(config_data, f)
            config_path = f.name

        try:
            config = Config(config_path)

            assert config.get('max_open_trades') == 5
            assert config.get('stake_currency') == 'USDT'
            assert config.get('stake_amount') == 200
            assert config.get('dry_run') is True
            assert config.get('strategy') == 'SampleStrategy'
            assert config.exchange_name == 'binance'
        finally:
            Path(config_path).unlink(missing_ok=True)

    def test_config_set_and_get(self):
        """Test setting and getting configuration values."""
        config = Config()

        config.set('custom_key', 'custom_value')
        assert config.get('custom_key') == 'custom_value'

        config.set('nested.key', 'nested_value')
        assert config.get('nested.key') == 'nested_value'

    def test_config_get_with_default(self):
        """Test getting non-existent key with default value."""
        config = Config()

        assert config.get('nonexistent_key') is None
        assert config.get('nonexistent_key', 'default') == 'default'

    def test_config_properties(self):
        """Test configuration property shortcuts."""
        config = Config()

        assert config.dry_run is True
        assert config.dry_run_wallet == 1000
        assert config.stake_currency == 'USDT'
        assert config.market_type == 'auto'
        assert config.exchange_name == 'binance'
