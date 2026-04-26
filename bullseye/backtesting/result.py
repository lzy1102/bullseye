"""
Backtest Result - Data structures for backtesting results.
"""
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class BacktestTrade:
    pair: str = ""
    entry_date: Optional[datetime] = None
    exit_date: Optional[datetime] = None
    open_rate: float = 0.0
    close_rate: float = 0.0
    amount: float = 0.0
    stake_amount: float = 0.0
    fee_open: float = 0.0
    fee_close: float = 0.0
    profit: float = 0.0
    profit_pct: float = 0.0
    profit_abs: float = 0.0
    exit_reason: str = ""
    enter_tag: Optional[str] = None
    is_short: bool = False
    leverage: float = 1.0
    trade_duration: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pair": self.pair,
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "exit_date": self.exit_date.isoformat() if self.exit_date else None,
            "open_rate": self.open_rate,
            "close_rate": self.close_rate,
            "amount": self.amount,
            "stake_amount": self.stake_amount,
            "fee_open": self.fee_open,
            "fee_close": self.fee_close,
            "profit": self.profit,
            "profit_pct": self.profit_pct,
            "profit_abs": self.profit_abs,
            "exit_reason": self.exit_reason,
            "enter_tag": self.enter_tag,
            "is_short": self.is_short,
            "leverage": self.leverage,
            "trade_duration_hours": self.trade_duration,
        }


@dataclass
class BacktestMetrics:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_profit: float = 0.0
    total_profit_pct: float = 0.0
    avg_profit: float = 0.0
    avg_profit_pct: float = 0.0
    max_profit: float = 0.0
    max_loss: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_abs: float = 0.0
    avg_trade_duration: float = 0.0
    best_pair: str = ""
    worst_pair: str = ""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    backtest_days: int = 0
    initial_balance: float = 0.0
    final_balance: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "total_profit": round(self.total_profit, 4),
            "total_profit_pct": round(self.total_profit_pct, 2),
            "avg_profit": round(self.avg_profit, 4),
            "avg_profit_pct": round(self.avg_profit_pct, 2),
            "max_profit": round(self.max_profit, 4),
            "max_loss": round(self.max_loss, 4),
            "profit_factor": round(self.profit_factor, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_abs": round(self.max_drawdown_abs, 4),
            "avg_trade_duration_hours": round(self.avg_trade_duration, 2),
            "best_pair": self.best_pair,
            "worst_pair": self.worst_pair,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "backtest_days": self.backtest_days,
            "initial_balance": self.initial_balance,
            "final_balance": round(self.final_balance, 4),
        }


class BacktestResult:
    """
    Container for backtesting results.

    Stores trades, metrics, and provides export capabilities.
    """

    def __init__(
        self,
        strategy_name: str = "",
        trades: Optional[List[BacktestTrade]] = None,
        metrics: Optional[BacktestMetrics] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.strategy_name = strategy_name
        self.trades = trades or []
        self.metrics = metrics or BacktestMetrics()
        self.config = config or {}
        self.created_at = datetime.now()

    def calculate_metrics(self, initial_balance: float = 1000.0) -> None:
        """
        Calculate all backtest metrics from the trade list.
        """
        if not self.trades:
            self.metrics = BacktestMetrics(
                initial_balance=initial_balance,
                final_balance=initial_balance,
            )
            return

        profits = [t.profit_abs for t in self.trades]
        profit_pcts = [t.profit_pct for t in self.trades]
        winning = [t for t in self.trades if t.profit_abs > 0]
        losing = [t for t in self.trades if t.profit_abs <= 0]
        durations = [t.trade_duration for t in self.trades]

        total_profit = sum(profits)
        total_profit_pct = (total_profit / initial_balance) * 100 if initial_balance > 0 else 0
        avg_profit = total_profit / len(self.trades) if self.trades else 0
        avg_profit_pct = sum(profit_pcts) / len(profit_pcts) if profit_pcts else 0

        gross_profit = sum(t.profit_abs for t in winning)
        gross_loss = abs(sum(t.profit_abs for t in losing))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        sharpe = self._calc_sharpe(profits)
        sortino = self._calc_sortino(profits)
        max_dd, max_dd_abs = self._calc_max_drawdown(profits, initial_balance)
        calmar = self._calc_calmar(profit_pcts, max_dd)

        pair_profits: Dict[str, float] = {}
        for t in self.trades:
            pair_profits[t.pair] = pair_profits.get(t.pair, 0.0) + t.profit_abs

        best_pair = max(pair_profits, key=pair_profits.get) if pair_profits else ""
        worst_pair = min(pair_profits, key=pair_profits.get) if pair_profits else ""

        entry_dates = [t.entry_date for t in self.trades if t.entry_date]
        exit_dates = [t.exit_date for t in self.trades if t.exit_date]
        start_date = min(entry_dates) if entry_dates else None
        end_date = max(exit_dates) if exit_dates else None
        backtest_days = (end_date - start_date).days + 1 if start_date and end_date else 0

        self.metrics = BacktestMetrics(
            total_trades=len(self.trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=len(winning) / len(self.trades) if self.trades else 0,
            total_profit=total_profit,
            total_profit_pct=total_profit_pct,
            avg_profit=avg_profit,
            avg_profit_pct=avg_profit_pct,
            max_profit=max(profits) if profits else 0,
            max_loss=min(profits) if profits else 0,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            max_drawdown=max_dd,
            max_drawdown_abs=max_dd_abs,
            avg_trade_duration=sum(durations) / len(durations) if durations else 0,
            best_pair=best_pair,
            worst_pair=worst_pair,
            start_date=start_date,
            end_date=end_date,
            backtest_days=backtest_days,
            initial_balance=initial_balance,
            final_balance=initial_balance + total_profit,
        )

    def _calc_sharpe(self, profits: List[float], risk_free: float = 0.0) -> float:
        import math
        if len(profits) < 2:
            return 0.0
        avg = sum(profits) / len(profits)
        variance = sum((p - avg) ** 2 for p in profits) / (len(profits) - 1)
        std = math.sqrt(variance) if variance > 0 else 0
        if std == 0:
            return 0.0
        return (avg - risk_free) / std * math.sqrt(252)

    def _calc_sortino(self, profits: List[float], risk_free: float = 0.0) -> float:
        import math
        if len(profits) < 2:
            return 0.0
        avg = sum(profits) / len(profits)
        downside = [p for p in profits if p < 0]
        if not downside:
            return float('inf') if avg > 0 else 0.0
        downside_var = sum((p - risk_free) ** 2 for p in downside) / len(downside)
        downside_std = math.sqrt(downside_var) if downside_var > 0 else 0
        if downside_std == 0:
            return 0.0
        return (avg - risk_free) / downside_std * math.sqrt(252)

    def _calc_max_drawdown(self, profits: List[float], initial_balance: float) -> tuple:
        peak = initial_balance
        max_dd = 0.0
        max_dd_abs = 0.0
        balance = initial_balance
        for p in profits:
            balance += p
            if balance > peak:
                peak = balance
            dd_abs = peak - balance
            dd_pct = (dd_abs / peak) * 100 if peak > 0 else 0
            if dd_pct > max_dd:
                max_dd = dd_pct
                max_dd_abs = dd_abs
        return max_dd, max_dd_abs

    def _calc_calmar(self, profit_pcts: List[float], max_dd: float) -> float:
        if max_dd == 0:
            return 0.0
        annual_return = sum(profit_pcts) if profit_pcts else 0
        return annual_return / max_dd

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy_name,
            "created_at": self.created_at.isoformat(),
            "config": self.config,
            "metrics": self.metrics.to_dict(),
            "trades": [t.to_dict() for t in self.trades],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def save(self, filepath: Optional[str] = None) -> str:
        """
        Save backtest results to a JSON file.

        Args:
            filepath: Output file path. If None, auto-generates.

        Returns:
            Path to the saved file.
        """
        if filepath is None:
            results_dir = Path("user_data/backtest_results")
            results_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = str(results_dir / f"backtest-result-{timestamp}.json")

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.to_json())

        return filepath

    @classmethod
    def load(cls, filepath: str) -> "BacktestResult":
        """
        Load backtest results from a JSON file.
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        trades = []
        for t_data in data.get("trades", []):
            trade = BacktestTrade(
                pair=t_data.get("pair", ""),
                open_rate=t_data.get("open_rate", 0),
                close_rate=t_data.get("close_rate", 0),
                amount=t_data.get("amount", 0),
                stake_amount=t_data.get("stake_amount", 0),
                fee_open=t_data.get("fee_open", 0),
                fee_close=t_data.get("fee_close", 0),
                profit=t_data.get("profit", 0),
                profit_pct=t_data.get("profit_pct", 0),
                profit_abs=t_data.get("profit_abs", 0),
                exit_reason=t_data.get("exit_reason", ""),
                enter_tag=t_data.get("enter_tag"),
                is_short=t_data.get("is_short", False),
                leverage=t_data.get("leverage", 1.0),
                trade_duration=t_data.get("trade_duration_hours", 0),
            )
            if t_data.get("entry_date"):
                trade.entry_date = datetime.fromisoformat(t_data["entry_date"])
            if t_data.get("exit_date"):
                trade.exit_date = datetime.fromisoformat(t_data["exit_date"])
            trades.append(trade)

        m = data.get("metrics", {})
        metrics = BacktestMetrics(
            total_trades=m.get("total_trades", 0),
            winning_trades=m.get("winning_trades", 0),
            losing_trades=m.get("losing_trades", 0),
            win_rate=m.get("win_rate", 0),
            total_profit=m.get("total_profit", 0),
            total_profit_pct=m.get("total_profit_pct", 0),
            avg_profit=m.get("avg_profit", 0),
            avg_profit_pct=m.get("avg_profit_pct", 0),
            max_profit=m.get("max_profit", 0),
            max_loss=m.get("max_loss", 0),
            profit_factor=m.get("profit_factor", 0),
            sharpe_ratio=m.get("sharpe_ratio", 0),
            sortino_ratio=m.get("sortino_ratio", 0),
            calmar_ratio=m.get("calmar_ratio", 0),
            max_drawdown=m.get("max_drawdown", 0),
            max_drawdown_abs=m.get("max_drawdown_abs", 0),
            avg_trade_duration=m.get("avg_trade_duration_hours", 0),
            best_pair=m.get("best_pair", ""),
            worst_pair=m.get("worst_pair", ""),
            initial_balance=m.get("initial_balance", 0),
            final_balance=m.get("final_balance", 0),
        )
        if m.get("start_date"):
            metrics.start_date = datetime.fromisoformat(m["start_date"])
        if m.get("end_date"):
            metrics.end_date = datetime.fromisoformat(m["end_date"])
        metrics.backtest_days = m.get("backtest_days", 0)

        return cls(
            strategy_name=data.get("strategy", ""),
            trades=trades,
            metrics=metrics,
            config=data.get("config", {}),
        )

    def get_trades_dataframe(self) -> pd.DataFrame:
        """
        Get trades as a DataFrame for analysis.
        """
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame([t.to_dict() for t in self.trades])
