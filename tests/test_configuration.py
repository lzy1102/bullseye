"""
Test configuration module
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bullseye.configuration import Config


class TestConfiguration:
    """Test suite for Configuration module."""
    
    def test_config_loading(self, sample_config_file):
        """Test configuration loading from file."""
        config = Config(sample_config_file)
        
        assert config.get('max_open_trades') == 5
        assert config.get('stake_currency') == 'USDT'
        assert config.get('stake_amount') == 100
        assert config.get('dry_run') is True
        assert config.get('strategy') == 'SampleStrategy'
    
    def test_config_defaults(self):
        """Test configuration with default values."""
        config = Config()
        
        assert config.get('max_open_trades') == 5
        assert config.get('stake_currency') == 'USDT'
        assert config.get('stake_amount') == 'unlimited'
        assert config.get('dry_run') is True
        assert config.get('market_type') == 'auto'
    
    def test_config_market_type_crypto(self):
        """Test crypto market type configuration."""
        config = Config()
        config_dict = {'market_type': 'crypto'}
        
        assert config.get('market_type') == 'crypto'
    
    def test_config_market_type_stock(self):
        """Test stock market type configuration."""
        config = Config()
        config_dict = {'market_type': 'stock'}
        
        assert config.get('market_type') == 'stock'
    
    def test_config_market_type_future(self):
        """Test future market type configuration."""
        config = Config()
        config_dict = {'market_type': 'future'}
        
        assert config.get('market_type') == 'future'
    
    def test_config_telegram_enabled(self):
        """Test Telegram configuration."""
        config = Config()
        config_dict = {
            'telegram': {
                'enabled': True,
                'token': 'test_token',
                'chat_id': 'test_chat_id'
            }
        }
        
        assert config.get('telegram.enabled') is True
        assert config.get('telegram.token') == 'test_token'
        assert config.get('telegram.chat_id') == 'test_chat_id'
    
    def test_config_api_server_enabled(self):
        """Test API server configuration."""
        config = Config()
        config_dict = {
            'api_server': {
                'enabled': True,
                'listen_ip': '127.0.0.1',
                'listen_port': 8080
            }
        }
        
        assert config.get('api_server.enabled') is True
        assert config.get('api_server.listen_ip') == '127.0.0.1'
        assert config.get('api_server.listen_port') == 8080
    
    def test_config_webhook_enabled(self):
        """Test Webhook configuration."""
        config = Config()
        config_dict = {
            'webhook': {
                'enabled': True,
                'url': 'https://example.com/webhook',
                'format': 'json',
                'retry_count': 3
            }
        }
        
        assert config.get('webhook.enabled') is True
        assert config.get('webhook.url') == 'https://example.com/webhook'
        assert config.get('webhook.format') == 'json'
        assert config.get('webhook.retry_count') == 3
