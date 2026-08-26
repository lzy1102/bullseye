"""
FastAPI Application for Bullseye REST API

Provides REST API endpoints for controlling the trading bot.
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Security scheme
security = HTTPBearer()


class BotStatus(BaseModel):
    """Bot status model."""
    state: str
    mode: str
    version: str
    uptime_seconds: float


class Balance(BaseModel):
    """Balance model."""
    currency: str
    total: float
    free: float
    used: float


class Trade(BaseModel):
    """Trade model."""
    id: int
    pair: str
    side: str
    amount: float
    open_rate: float
    close_rate: Optional[float] = None
    profit: Optional[float] = None
    profit_percent: Optional[float] = None
    status: str
    open_date: datetime
    close_date: Optional[datetime] = None
    entry_tag: Optional[str] = None
    exit_tag: Optional[str] = None


class TradeRequest(BaseModel):
    """Trade creation request model."""
    pair: str
    side: str
    amount: float
    price: Optional[float] = None
    tag: Optional[str] = None


class BacktestRequest(BaseModel):
    """Backtest request model."""
    strategy: str
    timerange: Optional[str] = None
    timeframe: Optional[str] = None


class Config(BaseModel):
    """Configuration model."""
    max_open_trades: int
    stake_currency: str
    stake_amount: float
    dry_run: bool
    strategy: str


def create_app(config: Optional[Dict[str, Any]] = None) -> FastAPI:
    """
    Create FastAPI application.
    
    Args:
        config: Optional configuration dict
        
    Returns:
        FastAPI application instance
    """
    app = FastAPI(
        title="Bullseye API",
        description="REST API for Bullseye Quantitative Trading Framework",
        version="1.0.0"
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store config
    app.state.config = config or {}

    # Store bot instance (to be set externally)
    app.state.bot = None

    @app.get("/", tags=["General"])
    async def root():
        """Root endpoint."""
        return {
            "name": "Bullseye API",
            "version": "1.0.0",
            "status": "running"
        }

    @app.get("/api/v1/status", response_model=BotStatus, tags=["Status"])
    async def get_status(credentials: HTTPAuthorizationCredentials = Depends(security)):
        """Get bot status."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        return BotStatus(
            state=bot.state,
            mode=bot.mode,
            version=bot.version,
            uptime_seconds=bot.uptime_seconds()
        )

    @app.get("/api/v1/balance", response_model=List[Balance], tags=["Account"])
    async def get_balance(credentials: HTTPAuthorizationCredentials = Depends(security)):
        """Get account balance."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        balances = bot.get_balances()
        return balances

    @app.get("/api/v1/profit", tags=["Account"])
    async def get_profit(credentials: HTTPAuthorizationCredentials = Depends(security)):
        """Get profit statistics."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        profit = bot.get_profit()
        return profit

    @app.get("/api/v1/performance", tags=["Account"])
    async def get_performance(credentials: HTTPAuthorizationCredentials = Depends(security)):
        """Get performance metrics."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        performance = bot.get_performance()
        return performance

    @app.get("/api/v1/trades", response_model=List[Trade], tags=["Trading"])
    async def list_trades(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        status: Optional[str] = None,
        limit: int = 50
    ):
        """List trades."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        trades = bot.get_trades(status=status, limit=limit)
        return trades

    @app.get("/api/v1/trades/{trade_id}", response_model=Trade, tags=["Trading"])
    async def get_trade(
        trade_id: int,
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ):
        """Get trade by ID."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        trade = bot.get_trade(trade_id)
        if trade is None:
            raise HTTPException(status_code=404, detail="Trade not found")

        return trade

    @app.post("/api/v1/trade", response_model=Trade, tags=["Trading"])
    async def create_trade(
        request: TradeRequest,
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ):
        """Create a new trade."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        trade = bot.create_trade(
            pair=request.pair,
            side=request.side,
            amount=request.amount,
            price=request.price,
            tag=request.tag
        )
        return trade

    @app.post("/api/v1/trade/{trade_id}/sell", response_model=Trade, tags=["Trading"])
    async def sell_trade(
        trade_id: int,
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ):
        """Sell a trade."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        trade = bot.sell_trade(trade_id)
        if trade is None:
            raise HTTPException(status_code=404, detail="Trade not found")

        return trade

    @app.delete("/api/v1/trade/{trade_id}", tags=["Trading"])
    async def cancel_trade(
        trade_id: int,
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ):
        """Cancel a trade."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        success = bot.cancel_trade(trade_id)
        if not success:
            raise HTTPException(status_code=404, detail="Trade not found or cannot be cancelled")

        return {"message": "Trade cancelled"}

    @app.get("/api/v1/config", response_model=Config, tags=["Configuration"])
    async def get_config(credentials: HTTPAuthorizationCredentials = Depends(security)):
        """Get configuration."""
        return Config(
            max_open_trades=app.state.config.get('max_open_trades', 5),
            stake_currency=app.state.config.get('stake_currency', 'USDT'),
            stake_amount=app.state.config.get('stake_amount', 100),
            dry_run=app.state.config.get('dry_run', True),
            strategy=app.state.config.get('strategy', '')
        )

    @app.post("/api/v1/config", response_model=Config, tags=["Configuration"])
    async def update_config(
        config_update: Config,
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ):
        """Update configuration."""
        app.state.config.update(config_update.dict())
        return config_update

    @app.get("/api/v1/pairlist", response_model=List[str], tags=["Configuration"])
    async def get_pairlist(credentials: HTTPAuthorizationCredentials = Depends(security)):
        """Get pairlist."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        pairlist = bot.get_pairlist()
        return pairlist

    @app.post("/api/v1/backtest", tags=["Backtesting"])
    async def start_backtest(
        request: BacktestRequest,
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ):
        """Start a backtest."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        backtest_id = bot.start_backtest(
            strategy=request.strategy,
            timerange=request.timerange,
            timeframe=request.timeframe
        )
        return {"backtest_id": backtest_id, "status": "started"}

    @app.get("/api/v1/backtest/{backtest_id}", tags=["Backtesting"])
    async def get_backtest_result(
        backtest_id: int,
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ):
        """Get backtest result."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        result = bot.get_backtest_result(backtest_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Backtest not found")

        return result

    @app.delete("/api/v1/backtest/{backtest_id}", tags=["Backtesting"])
    async def stop_backtest(
        backtest_id: int,
        credentials: HTTPAuthorizationCredentials = Depends(security)
    ):
        """Stop a backtest."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        success = bot.stop_backtest(backtest_id)
        if not success:
            raise HTTPException(status_code=404, detail="Backtest not found or cannot be stopped")

        return {"message": "Backtest stopped"}

    @app.get("/api/v1/logs", tags=["System"])
    async def get_logs(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        limit: int = 100
    ):
        """Get logs."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        logs = bot.get_logs(limit=limit)
        return {"logs": logs}

    @app.get("/api/v1/chart/{pair}", tags=["Data"])
    async def get_chart_data(
        pair: str,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        timeframe: str = "5m",
        limit: int = 100
    ):
        """Get chart data for a pair."""
        bot = app.state.bot

        if bot is None:
            raise HTTPException(status_code=503, detail="Bot not initialized")

        data = bot.get_chart_data(pair, timeframe=timeframe, limit=limit)
        return {"pair": pair, "timeframe": timeframe, "data": data}

    return app


def start_api_server(app: FastAPI, host: str = "127.0.0.1", port: int = 8080):
    """
    Start the API server.
    
    Args:
        app: FastAPI application
        host: Host to bind to
        port: Port to bind to
    """
    import uvicorn

    logger.info(f"Starting API server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
