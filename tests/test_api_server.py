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
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert data['name'] == 'Bullseye API'
        assert data['version'] == '1.0.0'
    
    def test_get_status_endpoint(self):
        """Test /api/v1/status endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        response = client.get("/api/v1/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data['state'] == 'running'
        assert data['mode'] == 'dry'
        assert data['version'] == '1.0.0'
    
    def test_get_balance_endpoint(self):
        """Test /api/v1/balance endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        response = client.get("/api/v1/balance")
        
        assert response.status_code == 200
        balances = response.json()
        assert len(balances) == 1
        assert balances[0]['currency'] == 'USDT'
        assert balances[0]['total'] == 1000
    
    def test_get_profit_endpoint(self):
        """Test /api/v1/profit endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        response = client.get("/api/v1/profit")
        
        assert response.status_code == 200
        profit = response.json()
        assert profit['total_profit'] == 105.5
        assert profit['total_profit_percent'] == 10.55
    
    def test_list_trades_endpoint(self):
        """Test /api/v1/trades endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        response = client.get("/api/v1/trades")
        
        assert response.status_code == 200
        trades = response.json()
        assert len(trades) == 0
    
    def test_create_trade_endpoint(self):
        """Test POST /api/v1/trade endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app, TradeRequest
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        
        trade_request = TradeRequest(
            pair='BTC/USDT',
            side='buy',
            amount=0.1,
            tag='test_entry'
        )
        
        response = client.post("/api/v1/trade", json=trade_request)
        
        assert response.status_code == 200
        trade = response.json()
        assert trade['pair'] == 'BTC/USDT'
        assert trade['side'] == 'buy'
        assert trade['amount'] == 0.1
        assert trade['status'] == 'open'
    
    def test_sell_trade_endpoint(self):
        """Test POST /api/v1/trade/{id}/sell endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        response = client.post("/api/v1/trade/1/sell")
        
        assert response.status_code == 200
        trade = response.json()
        assert trade['status'] == 'closed'
    
    def test_cancel_trade_endpoint(self):
        """Test DELETE /api/v1/trade/{id} endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        response = client.delete("/api/v1/trade/1")
        
        assert response.status_code == 200
        data = response.json()
        assert data['message'] == 'Trade cancelled'
    
    def test_get_config_endpoint(self):
        """Test GET /api/v1/config endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        config = {
            'max_open_trades': 5,
            'stake_currency': 'USDT',
            'stake_amount': 100,
            'dry_run': True,
            'strategy': 'TestStrategy'
        }
        
        app = create_app(config)
        
        client = TestClient(app)
        response = client.get("/api/v1/config")
        
        assert response.status_code == 200
        data = response.json()
        assert data['max_open_trades'] == 5
        assert data['stake_currency'] == 'USDT'
    
    def test_get_pairlist_endpoint(self):
        """Test GET /api/v1/pairlist endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        response = client.get("/api/v1/pairlist")
        
        assert response.status_code == 200
        pairlist = response.json()
        assert len(pairlist) == 3
    
    def test_start_backtest_endpoint(self):
        """Test POST /api/v1/backtest endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        response = client.post("/api/v1/backtest", json={
            'strategy': 'TestStrategy',
            'timerange': '20240101-20240131'
        })
        
        assert response.status_code == 200
        data = response.json()
        assert 'backtest_id' in data
        assert data['status'] == 'started'
    
    def test_get_backtest_result_endpoint(self):
        """Test GET /api/v1/backtest/{id} endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        response = client.get("/api/v1/backtest/1")
        
        assert response.status_code == 200
        data = response.json()
        assert data['backtest_id'] == 1
        assert data['status'] == 'completed'
    
    def test_stop_backtest_endpoint(self):
        """Test DELETE /api/v1/backtest/{id} endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        response = client.delete("/api/v1/backtest/1")
        
        assert response.status_code == 200
        data = response.json()
        assert data['message'] == 'Backtest stopped'
    
    def test_get_logs_endpoint(self):
        """Test GET /api/v1/logs endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        response = client.get("/api/v1/logs")
        
        assert response.status_code == 200
        data = response.json()
        assert 'logs' in data
        assert len(data['logs']) == 1
    
    def test_get_chart_data_endpoint(self):
        """Test GET /api/v1/chart/{pair} endpoint."""
        from fastapi.testclient import TestClient
        from bullseye.rpc.api_server import create_app
        
        mock_bot = MockBot()
        app = create_app()
        app.state.bot = mock_bot
        
        client = TestClient(app)
        response = client.get("/api/v1/chart/BTC/USDT")
        
        assert response.status_code == 200
        data = response.json()
        assert data['pair'] == 'BTC/USDT'
        assert data['timeframe'] == '5m'
        assert 'data' in data
        assert len(data['data']) == 1
