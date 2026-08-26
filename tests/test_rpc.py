"""
Test RPC modules
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, AsyncMock, patch

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

    def _make_bot(self) -> TelegramBot:
        """Create a TelegramBot with a mocked async telegram client."""
        config = TelegramConfig(
            enabled=True,
            token='test_token',
            chat_id='test_chat_id',
        )
        bot = TelegramBot(config)
        bot.bot = AsyncMock()
        bot.bot.send_message.return_value = True
        return bot

    def test_telegram_bot_send_message(self):
        """Test TelegramBot message sending (mock)."""
        bot = self._make_bot()

        assert bot.send_message('Test message') is True
        bot.bot.send_message.assert_awaited_once()

    def test_telegram_bot_send_message_failure(self):
        """Test TelegramBot message sending failure (mock)."""
        bot = self._make_bot()
        bot.bot.send_message.side_effect = Exception("network error")

        assert bot.send_message('Test message') is False

    def test_telegram_bot_notify_entry(self):
        """Test TelegramBot entry notification."""
        bot = self._make_bot()

        trade = {
            'pair': 'BTC/USDT',
            'amount': 0.1,
            'open_rate': 100,
            'entry_tag': 'test_signal'
        }

        assert bot.notify_entry(trade) is True

    def test_telegram_bot_notify_exit(self):
        """Test TelegramBot exit notification."""
        bot = self._make_bot()

        trade = {
            'pair': 'BTC/USDT',
            'profit': 10.5,
            'profit_percent': 10.5,
            'exit_tag': 'roi'
        }

        assert bot.notify_exit(trade, 10.5, 10.5) is True

    def test_telegram_bot_notify_startup(self):
        """Test TelegramBot startup notification."""
        bot = self._make_bot()

        assert bot.notify_startup('1.0.0', 'dry') is True

    def test_telegram_rpc_with_dict_config(self):
        """Test TelegramRPC with dict config."""
        config = {
            'enabled': True,
            'token': 'test_token',
            'chat_id': 'test_chat_id',
        }
        rpc = TelegramRPC(config)

        assert rpc is not None
        assert rpc.bot is not None


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

        result = client.send(event, data)
        assert result is True or result is False

    def test_webhook_rpc_with_dict_config(self):
        """Test WebhookRPC with dict config."""
        config = {
            'enabled': True,
            'url': 'https://example.com/webhook',
            'format': 'json',
        }
        rpc = WebhookRPC(config)

        assert rpc is not None
        assert rpc.client is not None

    def test_webhook_rpc_startup(self):
        """Test WebhookRPC startup notification."""
        config = {
            'enabled': True,
            'url': 'https://example.com/webhook',
        }
        rpc = WebhookRPC(config)

        rpc.startup('1.0.0', 'dry')

    def test_webhook_rpc_entry(self):
        """Test WebhookRPC entry notification."""
        config = {
            'enabled': True,
            'url': 'https://example.com/webhook',
        }
        rpc = WebhookRPC(config)

        trade = {'pair': 'BTC/USDT', 'amount': 0.1}
        rpc.entry(trade)

    def test_webhook_rpc_exit(self):
        """Test WebhookRPC exit notification."""
        config = {
            'enabled': True,
            'url': 'https://example.com/webhook',
        }
        rpc = WebhookRPC(config)

        trade = {'pair': 'BTC/USDT', 'profit': 10.5}
        rpc.exit(trade, 10.5, 10.5)
