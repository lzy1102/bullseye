"""
Test RPC modules
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from bullseye.rpc.telegram import TelegramRPC, TelegramConfig, TelegramBot
from bullseye.rpc.webhook import WebhookRPC, WebhookConfig, WebhookClient


class TestTelegramRPC:
    """Test suite for Telegram RPC."""
    
    def test_telegram_config_initialization(self):
        """Test TelegramConfig initialization."""
        config = TelegramConfig(
            enabled=True,
            token='test_token',
            chat_id='test_chat_id',
            notification_settings={
                'status': 'on',
                'warning': 'on',
                'startup': 'on',
                'entry': 'on',
                'exit': 'on',
            }
        )
        
        assert config.enabled is True
        assert config.token == 'test_token'
        assert config.chat_id == 'test_chat_id'
        assert config.notification_settings['entry'] == 'on'
    
    def test_telegram_bot_disabled(self):
        """Test TelegramBot when disabled."""
        config = TelegramConfig(enabled=False, token='', chat_id='')
        bot = TelegramBot(config)
        
        assert bot._initialized is False
    
    def test_telegram_bot_send_message(self):
        """Test TelegramBot message sending (mock)."""
        config = TelegramConfig(
            enabled=True,
            token='test_token',
            chat_id='test_chat_id',
            notification_settings={'entry': 'on', 'exit': 'on'}
        )
        bot = TelegramBot(config)
        
        assert bot.send_message('Test message') is True
    
    def test_telegram_bot_notify_entry(self):
        """Test TelegramBot entry notification."""
        config = TelegramConfig(enabled=True, token='test_token', chat_id='test_chat_id')
        bot = TelegramBot(config)
        
        trade = {
            'pair': 'BTC/USDT',
            'amount': 0.1,
            'open_rate': 100,
            'entry_tag': 'test_signal'
        }
        
        assert bot.notify_entry(trade) is True
    
    def test_telegram_bot_notify_exit(self):
        """Test TelegramBot exit notification."""
        config = TelegramConfig(enabled=True, token='test_token', chat_id='test_chat_id')
        bot = TelegramBot(config)
        
        trade = {
            'pair': 'BTC/USDT',
            'profit': 10.5,
            'profit_percent': 10.5,
            'exit_tag': 'roi'
        }
        
        assert bot.notify_exit(trade, 10.5, 10.5) is True
    
    def test_telegram_bot_notify_startup(self):
        """Test TelegramBot startup notification."""
        config = TelegramConfig(enabled=True, token='test_token', chat_id='test_chat_id')
        bot = TelegramBot(config)
        
        assert bot.notify_startup('1.0.0', 'dry') is True


class TestWebhookRPC:
    """Test suite for Webhook RPC."""
    
    def test_webhook_config_initialization(self):
        """Test WebhookConfig initialization."""
        config = WebhookConfig(
            enabled=True,
            url='https://example.com/webhook',
            format='json',
            retry_count=3,
            timeout=10
        )
        
        assert config.enabled is True
        assert config.url == 'https://example.com/webhook'
        assert config.format == 'json'
        assert config.retry_count == 3
    
    def test_webhook_client_send(self):
        """Test WebhookClient send operation (mock)."""
        config = WebhookConfig(
            enabled=True,
            url='https://example.com/webhook',
            format='json'
        )
        client = WebhookClient(config)
        
        event = 'test_event'
        data = {'test': 'data'}
        
        assert client.send(event, data) is True
    
    def test_webhook_rpc_startup(self):
        """Test WebhookRPC startup notification."""
        config = WebhookConfig(enabled=True, url='https://example.com/webhook')
        rpc = WebhookRPC(config)
        
        assert rpc.startup('1.0.0', 'dry') is True
    
    def test_webhook_rpc_entry(self):
        """Test WebhookRPC entry notification."""
        config = WebhookConfig(enabled=True, url='https://example.com/webhook')
        rpc = WebhookRPC(config)
        
        trade = {'pair': 'BTC/USDT', 'amount': 0.1}
        
        assert rpc.entry(trade) is True
    
    def test_webhook_rpc_exit(self):
        """Test WebhookRPC exit notification."""
        config = WebhookConfig(enabled=True, url='https://example.com/webhook')
        rpc = WebhookRPC(config)
        
        trade = {'pair': 'BTC/USDT', 'profit': 10.5}
        
        assert rpc.exit(trade, 10.5, 10.5) is True
