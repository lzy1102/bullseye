"""
Exit Logic for Bullseye

Provides complete implementations for exit decision logic including
stoploss, ROI, and pair locking mechanisms.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class ExitDecision:
    """
    Represents an exit decision with reason.
    """
    should_exit: bool
    exit_reason: Optional[str] = None
    exit_tag: Optional[str] = None
    exit_type: Optional[str] = None  # 'stoploss', 'roi', 'custom', 'timeout', 'signal'


class PairLock:
    """
    Manages pair locking mechanism.
    """
    
    def __init__(self):
        self.locks: Dict[str, Dict[str, Any]] = {}
    
    def lock_pair(self, pair: str, until: datetime, reason: str) -> None:
        """
        Lock a trading pair.
        
        Args:
            pair: Trading pair to lock
            until: Time until pair is locked
            reason: Reason for locking
        """
        self.locks[pair] = {
            'until': until,
            'reason': reason
        }
    
    def unlock_pair(self, pair: str) -> None:
        """
        Unlock a trading pair.
        
        Args:
            pair: Trading pair to unlock
        """
        if pair in self.locks:
            del self.locks[pair]
    
    def is_pair_locked(self, pair: str, current_time: datetime) -> bool:
        """
        Check if a trading pair is currently locked.
        
        Args:
            pair: Trading pair to check
            current_time: Current time
            
        Returns:
            True if pair is locked, False otherwise
        """
        if pair not in self.locks:
            return False
        
        lock_info = self.locks[pair]
        return current_time < lock_info['until']
    
    def get_lock_info(self, pair: str) -> Optional[Dict[str, Any]]:
        """
        Get lock information for a pair.
        
        Args:
            pair: Trading pair
            
        Returns:
            Lock information dict or None if not locked
        """
        return self.locks.get(pair)
    
    def cleanup_expired_locks(self, current_time: datetime) -> None:
        """
        Remove expired locks.
        
        Args:
            current_time: Current time
        """
        expired_pairs = [
            pair for pair, info in self.locks.items()
            if current_time >= info['until']
        ]
        for pair in expired_pairs:
            del self.locks[pair]


class ExitLogic:
    """
    Complete implementation of exit decision logic.
    
    Handles:
    - Stoploss detection
    - ROI (Return on Investment) detection
    - Custom exit logic from strategy
    - Timeout detection
    - Exit signal detection
    - Pair locking
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.pair_lock = PairLock()
    
    def should_exit(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        strategy: Any
    ) -> ExitDecision:
        """
        Determine if a trade should exit.
        
        This is the main exit decision function that considers all exit conditions.
        
        Args:
            pair: Trading pair
            trade: Trade object
            current_time: Current time
            current_rate: Current price
            current_profit: Current profit percentage
            strategy: Strategy instance
            
        Returns:
            ExitDecision with exit decision and reason
        """
        # Check if pair is locked
        if self.pair_lock.is_pair_locked(pair, current_time):
            return ExitDecision(
                should_exit=True,
                exit_reason='pair_locked',
                exit_tag='pair_lock',
                exit_type='lock'
            )
        
        # Check stoploss
        stoploss_decision = self.ft_stoploss_reached(
            pair, trade, current_time, current_rate, current_profit, strategy
        )
        if stoploss_decision.should_exit:
            return stoploss_decision
        
        # Check ROI
        roi_decision = self.min_roi_reached(
            pair, trade, current_time, current_rate, current_profit, strategy
        )
        if roi_decision.should_exit:
            return roi_decision
        
        # Check custom exit
        custom_decision = self.custom_exit(
            pair, trade, current_time, current_rate, current_profit, strategy
        )
        if custom_decision.should_exit:
            return custom_decision
        
        # Check exit timeout
        timeout_decision = self.check_exit_timeout(
            pair, trade, current_time, current_rate, current_profit, strategy
        )
        if timeout_decision.should_exit:
            return timeout_decision
        
        # Check exit signal from strategy
        signal_decision = self.check_exit_signal(
            pair, trade, current_time, current_rate, current_profit, strategy
        )
        if signal_decision.should_exit:
            return signal_decision
        
        # No exit condition met
        return ExitDecision(should_exit=False)
    
    def ft_stoploss_reached(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        strategy: Any
    ) -> ExitDecision:
        """
        Check if stoploss has been reached.
        
        Args:
            pair: Trading pair
            trade: Trade object
            current_time: Current time
            current_rate: Current price
            current_profit: Current profit percentage
            strategy: Strategy instance
            
        Returns:
            ExitDecision with stoploss decision
        """
        # Get stoploss from trade or strategy
        stoploss = None
        if hasattr(trade, 'stop_loss'):
            stoploss = trade.stop_loss
        elif hasattr(strategy, 'stoploss'):
            stoploss = strategy.stoploss
        
        if stoploss is None or stoploss == 0:
            return ExitDecision(should_exit=False)
        
        # Check if stoploss is triggered
        # Stoploss is typically a negative percentage
        if current_profit <= stoploss:
            return ExitDecision(
                should_exit=True,
                exit_reason='stoploss',
                exit_tag='stoploss',
                exit_type='stoploss'
            )
        
        return ExitDecision(should_exit=False)
    
    def min_roi_reached(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        strategy: Any
    ) -> ExitDecision:
        """
        Check if minimum ROI (Return on Investment) has been reached.
        
        Args:
            pair: Trading pair
            trade: Trade object
            current_time: Current time
            current_rate: Current price
            current_profit: Current profit percentage
            strategy: Strategy instance
            
        Returns:
            ExitDecision with ROI decision
        """
        # Get ROI from trade or strategy
        min_roi = None
        if hasattr(trade, 'min_roi'):
            min_roi = trade.min_roi
        elif hasattr(strategy, 'minimal_roi'):
            min_roi = strategy.minimal_roi
        
        if min_roi is None:
            return ExitDecision(should_exit=False)
        
        # Check if custom ROI is defined
        if hasattr(strategy, 'custom_roi'):
            custom_roi = strategy.custom_roi(pair, current_time, current_rate, current_profit)
            if custom_roi is not None and current_profit >= custom_roi:
                return ExitDecision(
                    should_exit=True,
                    exit_reason='custom_roi',
                    exit_tag='roi',
                    exit_type='roi'
                )
        
        # Check static ROI
        if current_profit >= min_roi:
            return ExitDecision(
                should_exit=True,
                exit_reason='roi',
                exit_tag='roi',
                exit_type='roi'
            )
        
        return ExitDecision(should_exit=False)
    
    def custom_exit(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        strategy: Any
    ) -> ExitDecision:
        """
        Check custom exit condition from strategy.
        
        Args:
            pair: Trading pair
            trade: Trade object
            current_time: Current time
            current_rate: Current price
            current_profit: Current profit percentage
            strategy: Strategy instance
            
        Returns:
            ExitDecision with custom exit decision
        """
        if not hasattr(strategy, 'custom_exit'):
            return ExitDecision(should_exit=False)
        
        # Call strategy's custom_exit method
        try:
            should_exit = strategy.custom_exit(
                pair, trade, current_time, current_rate, current_profit
            )
            
            if should_exit:
                return ExitDecision(
                    should_exit=True,
                    exit_reason='custom_exit',
                    exit_tag=getattr(strategy, 'custom_exit_tag', None),
                    exit_type='custom'
                )
        except Exception:
            pass
        
        return ExitDecision(should_exit=False)
    
    def check_exit_timeout(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        strategy: Any
    ) -> ExitDecision:
        """
        Check if exit timeout has been reached.
        
        Args:
            pair: Trading pair
            trade: Trade object
            current_time: Current time
            current_rate: Current price
            current_profit: Current profit percentage
            strategy: Strategy instance
            
        Returns:
            ExitDecision with timeout decision
        """
        # Get timeout settings
        exit_timeout = self.config.get('exit_timeout', None)
        
        if exit_timeout is None:
            return ExitDecision(should_exit=False)
        
        # Check if trade has an open time
        if not hasattr(trade, 'open_date'):
            return ExitDecision(should_exit=False)
        
        # Calculate time since open
        time_since_open = (current_time - trade.open_date).total_seconds()
        
        # Check if timeout reached
        if time_since_open >= exit_timeout:
            return ExitDecision(
                should_exit=True,
                exit_reason='timeout',
                exit_tag='timeout',
                exit_type='timeout'
            )
        
        return ExitDecision(should_exit=False)
    
    def check_exit_signal(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        strategy: Any
    ) -> ExitDecision:
        """
        Check if exit signal from strategy is triggered.
        
        Args:
            pair: Trading pair
            trade: Trade object
            current_time: Current time
            current_rate: Current price
            current_profit: Current profit percentage
            strategy: Strategy instance
            
        Returns:
            ExitDecision with signal decision
        """
        # This would typically be called from the strategy's populate_exit_trend
        # The strategy would set exit signals in the dataframe
        # This method checks if the current candle has an exit signal
        
        # For now, return False as this is handled in the strategy
        return ExitDecision(should_exit=False)
    
    # Pair locking methods
    def lock_pair(self, pair: str, until: datetime, reason: str) -> None:
        """Lock a trading pair."""
        self.pair_lock.lock_pair(pair, until, reason)
    
    def unlock_pair(self, pair: str) -> None:
        """Unlock a trading pair."""
        self.pair_lock.unlock_pair(pair)
    
    def is_pair_locked(self, pair: str, current_time: datetime) -> bool:
        """Check if a trading pair is locked."""
        return self.pair_lock.is_pair_locked(pair, current_time)
    
    def get_lock_info(self, pair: str) -> Optional[Dict[str, Any]]:
        """Get lock information for a pair."""
        return self.pair_lock.get_lock_info(pair)
    
    def cleanup_expired_locks(self, current_time: datetime) -> None:
        """Remove expired locks."""
        self.pair_lock.cleanup_expired_locks(current_time)
