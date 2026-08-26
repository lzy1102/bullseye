"""
Integration tests for Bullseye
"""
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestIntegration:
    """Integration tests for Bullseye framework."""

    def test_full_workflow(self, tmp_path):
        """Test full workflow from config to trading."""
        from bullseye.configuration import Config

        config_data = {
            'max_open_trades': 5,
            'stake_currency': 'USDT',
            'stake_amount': 100,
            'dry_run': True,
            'strategy': 'SampleStrategy',
            'exchange': {'name': 'binance'},
        }

        config_path = tmp_path / 'config.yaml'
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f)

        config = Config(str(config_path))

        assert config.get('max_open_trades') == 5
        assert config.get('stake_currency') == 'USDT'
        assert config.get('strategy') == 'SampleStrategy'

        from bullseye.trader.exit_logic import ExitLogic
        from bullseye.data.history import FeatherDataHandler

        exit_logic = ExitLogic(config={'exit_timeout': 3600})
        data_handler = FeatherDataHandler(data_dir=str(tmp_path / 'data'))

        assert exit_logic is not None
        assert data_handler is not None

    def test_data_handler_integration(self, tmp_path):
        """Test data handler integration with CLI."""
        from bullseye.data.history import FeatherDataHandler

        handler = FeatherDataHandler(data_dir=str(tmp_path / 'data'))

        import pandas as pd
        df = pd.DataFrame({
            'open': [1, 2, 3],
            'high': [2, 3, 4],
            'low': [1, 2, 3],
            'close': [1.5, 2.5, 3.5],
            'volume': [100, 200, 300],
        })

        handler.ohlcv_store('BTC/USDT', '5m', df)

        assert handler.ohlcv_exists('BTC/USDT', '5m')

        retrieved_df = handler.ohlcv_get('BTC/USDT', '5m')
        assert retrieved_df is not None

        pd.testing.assert_frame_equal(df, retrieved_df)

    def test_rpc_integration(self):
        """Test RPC integration."""
        from bullseye.rpc.telegram import TelegramRPC
        from bullseye.rpc.webhook import WebhookRPC

        telegram_config = {
            'enabled': True,
            'token': 'test_token',
            'chat_id': 'test_chat_id'
        }
        telegram_rpc = TelegramRPC(telegram_config)

        assert telegram_rpc is not None
        assert telegram_rpc.bot is not None

        webhook_config = {
            'enabled': True,
            'url': 'https://example.com/webhook',
            'format': 'json'
        }
        webhook_rpc = WebhookRPC(webhook_config)

        assert webhook_rpc is not None
        assert webhook_rpc.client is not None

    def test_api_server_integration(self):
        """Test API server integration."""
        from bullseye.rpc.api_server import create_app
        from fastapi.testclient import TestClient

        config = {
            'max_open_trades': 5,
            'stake_currency': 'USDT',
            'stake_amount': 100,
            'dry_run': True,
            'strategy': 'TestStrategy'
        }

        app = create_app(config)
        client = TestClient(app)

        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data['name'] == 'Bullseye API'
