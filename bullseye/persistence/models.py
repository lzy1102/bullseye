"""
Persistence Models - SQLAlchemy ORM models for database

Compatible with Freqtrade database schema.
"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean,
    Numeric, Enum as SQLEnum, Text, Index
)
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


class Trade(Base):
    """
    Trade record table

    Compatible with Freqtrade trades table structure.
    """
    __tablename__ = 'trades'

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Trading pair and market info
    pair = Column(String(25), nullable=False, index=True)
    exchange = Column(String(25), nullable=False)
    market_type = Column(String(10), default="crypto")

    # Trade status
    is_open = Column(Boolean, nullable=False, default=True, index=True)

    # Entry information
    open_date = Column(DateTime, nullable=False, default=datetime.now(timezone.utc), index=True)
    open_rate = Column(Float, nullable=False)
    open_rate_requested = Column(Float, nullable=True)
    open_trade_value = Column(Float, nullable=False)

    # Exit information
    close_date = Column(DateTime, nullable=True, index=True)
    close_rate = Column(Float, nullable=True)
    close_rate_requested = Column(Float, nullable=True)

    # Profit information
    close_profit_abs = Column(Float, nullable=True)
    close_profit = Column(Float, nullable=True)

    # Strategy information
    enter_tag = Column(String(100), nullable=True)
    exit_reason = Column(String(50), nullable=True)
    exit_status = Column(String(50), nullable=True)

    # Order information
    stake_amount = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    amount_requested = Column(Float, nullable=True)

    # Fee information
    fee_open = Column(Float, nullable=False, default=0.0)
    fee_close = Column(Float, nullable=False, default=0.0)

    # Timeframe
    timeframe = Column(String(10), nullable=True)

    # Strategy
    strategy = Column(String(100), nullable=True)

    # Trading mode
    trading_mode = Column(String(20), nullable=True)

    def __repr__(self):
        return (f"Trade(id={self.id}, pair={self.pair}, "
                f"is_open={self.is_open}, open_rate={self.open_rate})")


class Order(Base):
    """
    Order record table

    Compatible with Freqtrade orders table structure.
    """
    __tablename__ = 'orders'

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Trade association
    trade_id = Column(Integer, nullable=True, index=True)

    # Order information
    pair = Column(String(25), nullable=False, index=True)
    order_id = Column(String(100), nullable=True, index=True)
    order_date = Column(DateTime, nullable=False, default=datetime.now(timezone.utc), index=True)
    order_updated = Column(DateTime, nullable=True)

    # Order type and side
    order_type = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)  # buy | sell

    # Amount and price
    amount = Column(Float, nullable=False)
    amount_requested = Column(Float, nullable=True)
    price = Column(Float, nullable=True)
    price_requested = Column(Float, nullable=True)

    # Filled amount
    filled = Column(Float, nullable=False, default=0.0)
    remaining = Column(Float, nullable=True)

    # Order value
    cost = Column(Float, nullable=True)
    average = Column(Float, nullable=True)

    # Status
    status = Column(String(50), nullable=False)

    # Fee
    fee = Column(Float, nullable=True, default=0.0)

    # Freqtrade specific
    ft_pair = Column(String(25), nullable=True)
    ft_order_side = Column(String(10), nullable=True)

    def __repr__(self):
        return (f"Order(id={self.id}, pair={self.pair}, "
                f"order_id={self.order_id}, status={self.status})")


class PairLock(Base):
    """
    Pair lock table

    Used to prevent re-entry on the same pair for a specified time period.
    """
    __tablename__ = 'pairlocks'

    id = Column(Integer, primary_key=True, autoincrement=True)

    pair = Column(String(25), nullable=False, index=True)
    lock_time = Column(DateTime, nullable=False, default=datetime.now(timezone.utc), index=True)
    lock_end_time = Column(DateTime, nullable=False, index=True)
    reason = Column(String(50), nullable=False)
    lock_side = Column(String(10), nullable=False, default='*')  # long | short | *
    active = Column(Boolean, nullable=False, default=True, index=True)

    def __repr__(self):
        return f"PairLock(pair={self.pair}, until={self.lock_end_time})"


class IndexRecord(Base):
    """
    Index record table

    Used to track downloaded data.
    """
    __tablename__ = 'index'

    id = Column(Integer, primary_key=True, autoincrement=True)

    pair = Column(String(25), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)
    date = Column(DateTime, nullable=False, index=True)
    download_date = Column(DateTime, nullable=False, default=datetime.now(timezone.utc))

    def __repr__(self):
        return f"IndexRecord(pair={self.pair}, timeframe={self.timeframe}, date={self.date})"


class BacktestResult(Base):
    """
    Backtest result table
    """
    __tablename__ = 'backtest_results'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Backtest metadata
    strategy = Column(String(100), nullable=False)
    timeframe = Column(String(10), nullable=False)
    timerange = Column(String(50), nullable=False)

    # Results
    total_trades = Column(Integer, nullable=False)
    profit_total = Column(Float, nullable=False)
    profit_mean = Column(Float, nullable=True)
    profit_median = Column(Float, nullable=True)
    profit_total_abs = Column(Float, nullable=True)

    # Performance metrics
    sharpe_ratio = Column(Float, nullable=True)
    sortino_ratio = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    max_drawdown_abs = Column(Float, nullable=True)

    # Win rate
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    win_rate = Column(Float, nullable=True)

    # Timestamps
    backtest_start = Column(DateTime, nullable=False, default=datetime.now(timezone.utc))
    backtest_end = Column(DateTime, nullable=True)

    # Parameters
    parameters = Column(Text, nullable=True)  # JSON string

    def __repr__(self):
        return (f"BacktestResult(strategy={self.strategy}, "
                f"profit_total={self.profit_total}, sharpe={self.sharpe_ratio})")
