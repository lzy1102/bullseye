"""
Order module - Order execution and position management.

Provides order execution and trade tracking for Bullseye.
Supports automatic T+0/T+1 detection for different markets.

T+0 Markets (Can sell immediately):
- Cryptocurrency: BTC/USDT, ETH/USDT
- US Stocks: AAPL, GOOGL, TSLA
- HK Stocks: 00700.HK, 09988.HK
- Futures: AU2506@SHFE, IF2506@CFFEX

T+1 Markets (Can sell next trading day):
- A-shares: 000001.SZ, 600000.SH, 300750.SZ

Freqtrade Compatible:
- LocalTrade tracks trade state with T+1 support
- PositionManager manages open positions
- OrderExecutor handles entry/exit execution

Auto-Detection:
- Settlement type is automatically detected from pair format
- Use `detect_settlement_rule(pair)` to check settlement type
- Use `is_t1_market(pair)` to check if T+1 applies
"""

from .position_manager import (
    LocalTrade,
    PositionManager,
    MarketType,
    ExitType,
)
from .order_executor import OrderExecutor
from .settlement import (
    SettlementDetector,
    SettlementRule,
    SettlementType,
    detect_settlement_rule,
    is_t1_market,
    get_settlement_date,
    init_settlement_detector,
)

__all__ = [
    # Core classes
    "LocalTrade",
    "PositionManager",
    "OrderExecutor",
    # Market types
    "MarketType",
    "ExitType",
    # Settlement (T+1 auto-detection)
    "SettlementDetector",
    "SettlementRule",
    "SettlementType",
    "detect_settlement_rule",
    "is_t1_market",
    "get_settlement_date",
    "init_settlement_detector",
]
