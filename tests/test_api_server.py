"""
Test API Server module
"""
import pytest
from unittest.mock import Mock, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bullseye.rpc.api_server import create_app, BotStatus, Balance, Trade, TradeRequest


class MockBot:
    """Mock bot for testing."""

    def __init__(self):
        self.state = 'running'
        self.mode = 'dry'
        self.version = '1.0.0'
        self.trades = []

    def uptime_seconds(self):
        return 3600

    def get_balances(self):
        return [
            {'currency': 'USDT', 'total': 1000, 'free': 800, 'used': 200}
        ]

    def get_profit(self):
        return {'total_profit': 105.5, 'total_profit_percent': 10.55}

    def get_performance(self):
        return {
            'win_rate': 65.0,
            'profit_factor': 2.1,
            'sharpe_ratio': 1.5,
            'sortino_ratio': 2.0,
            'calmar_ratio': 1.8,
            'max_drawdown': -5.2
        }

    def get_trades(self, status=None, limit=50):
        return self.trades[:limit]

    def get_trade(self, trade_id):
        for trade in self.trades:
            if trade['id'] == trade_id:
                return trade
        return None

    def create_trade(self, pair, side, amount, price=None, tag=None):
        trade = {
            'id': len(self.trades) + 1,
            'pair': pair,
            'side': side,
            'amount': amount,
            'open_rate': price or 100,
            'status': 'open',
            'open_date': '2024-01-01 00:00:00',
            'entry_tag': tag
        }
        self.trades.append(trade)
        return trade

    def sell_trade(self, trade_id):
        for i, trade in enumerate(self.trades):
            if trade['id'] == trade_id:
                self.trades[i]['status'] = 'closed'
                self.trades[i]['close_rate'] = 110
                self.trades[i]['close_date'] = '2024-01-01 01:00:00'
                self.trades[i]['profit'] = 10
                self.trades[i]['profit_percent'] = 10
                self.trades[i]['exit_tag'] = 'roi'
                return trade
        return None

    def cancel_trade(self, trade_id):
        for i, trade in enumerate(self.trades):
            if trade['id'] == trade_id:
                self.trades[i]['status'] = 'cancelled'
                return trade
        return None

    def get_pairlist(self):
        return ['BTC/USDT', 'ETH/USDT', 'BNB/USDT']

    def start_backtest(self, strategy, timerange=None, timeframe=None):
        return {'backtest_id': 1, 'status': 'started'}

    def get_backtest_result(self, backtest_id):
        return {
            'backtest_id': backtest_id,
            'status': 'completed',
            'metrics': {
                'total_profit': 105.5,
                'total_profit_percent': 10.55,
                'total_trades': 100,
                'win_rate': 65.0
            }
        }

    def stop_backtest(self, backtest_id):
        return {'message': 'Backtest stopped'}

    def get_logs(self, limit=100):
        return [
            {'timestamp': '2024-01-01 00:00:00', 'level': 'INFO', 'message': 'Test log'}
        ]

    def get_chart_data(self, pair, timeframe='5m', limit=100):
        return {
            'pair': pair,
            'timeframe': timeframe,
            'data': [
                {'timestamp': '2024-01-01 00:00:00', 'open': 100, 'high': 102, 'low': 99, 'close': 101, 'volume': 1000}
            ]
        }


AUTH_HEADERS = {"Authorization": "Bearer test_token"}


class TestAPIServer:
    """Test suite for API Server."""

    def test_create_app(self):
        """Test FastAPI app creation."""
        config = {
            'max_open_trades': 5,
            'stake_currency': 'USDT',
            'stake_amount': 100,
            'dry_run': True,
            'strategy': 'TestStrategy'
        }

        app = create_app(config)
        assert app is not None
        assert app.state.config == config

    def test_root_endpoint(self):
        """Test root endpoint."""
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data['name'] == 'Bullseye API'
        assert data['version'] == '1.0.0'

    def test_get_status_endpoint(self):
        """Test /api/v1/status endpoint."""
        from fastapi.testclient import TestClient

        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot

        client = TestClient(app)
        response = client.get("/api/v1/status", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data['state'] == 'running'
        assert data['mode'] == 'dry'

    def test_get_balance_endpoint(self):
        """Test /api/v1/balance endpoint."""
        from fastapi.testclient import TestClient

        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot

        client = TestClient(app)
        response = client.get("/api/v1/balance", headers=AUTH_HEADERS)

        assert response.status_code == 200
        balances = response.json()
        assert len(balances) == 1
        assert balances[0]['currency'] == 'USDT'

    def test_get_profit_endpoint(self):
        """Test /api/v1/profit endpoint."""
        from fastapi.testclient import TestClient

        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot

        client = TestClient(app)
        response = client.get("/api/v1/profit", headers=AUTH_HEADERS)

        assert response.status_code == 200
        profit = response.json()
        assert profit['total_profit'] == 105.5

    def test_list_trades_endpoint(self):
        """Test /api/v1/trades endpoint."""
        from fastapi.testclient import TestClient

        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot

        client = TestClient(app)
        response = client.get("/api/v1/trades", headers=AUTH_HEADERS)

        assert response.status_code == 200
        trades = response.json()
        assert len(trades) == 0

    def test_get_config_endpoint(self):
        """Test GET /api/v1/config endpoint."""
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
        response = client.get("/api/v1/config", headers=AUTH_HEADERS)

        assert response.status_code == 200

    def test_get_pairlist_endpoint(self):
        """Test GET /api/v1/pairlist endpoint."""
        from fastapi.testclient import TestClient

        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot

        client = TestClient(app)
        response = client.get("/api/v1/pairlist", headers=AUTH_HEADERS)

        assert response.status_code == 200
        pairlist = response.json()
        assert len(pairlist) == 3

    def test_status_without_bot(self):
        """Test status endpoint when bot is not initialized."""
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)
        response = client.get("/api/v1/status", headers=AUTH_HEADERS)

        assert response.status_code == 503
