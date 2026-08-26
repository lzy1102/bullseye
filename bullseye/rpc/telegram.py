"""
Telegram Integration for Bullseye

Provides Telegram bot functionality for notifications and control.
"""
import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TelegramConfig:
    """Telegram configuration."""
    enabled: bool = False
    token: str = ""
    chat_id: str = ""
    notification_settings: Dict[str, str] = None
    
    def __post_init__(self):
        if self.notification_settings is None:
            self.notification_settings = {
                'status': 'warning',
                'warning': 'on',
                'startup': 'on',
                'entry': 'on',
                'entry_fill': 'on',
                'exit': 'on',
                'exit_fill': 'on',
                'protection_trigger': 'on',
                'show_candle': 'off',
                'strategy_msg': 'on',
            }


class TelegramBot:
    """
    Telegram Bot for Bullseye trading notifications.
    
    Supports:
    - Trade entry/exit notifications
    - Status updates
    - Interactive commands
    - Custom messages from strategy
    """
    
    def __init__(self, config: TelegramConfig):
        self.config = config
        self.bot = None
        self._initialized = False
        
        if config.enabled and config.token:
            self._init_bot()
    
    def _init_bot(self):
        """Initialize the Telegram bot."""
        try:
            from telegram import Bot
            self.bot = Bot(token=self.config.token)
            self._initialized = True
            logger.info("Telegram bot initialized successfully")
        except ImportError:
            logger.error("python-telegram-bot not installed. Install with: pip install python-telegram-bot")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
    
    def send_message(self, message: str, parse_mode: str = 'HTML') -> bool:
        """
        Send a message to Telegram.
        
        Args:
            message: Message text
            parse_mode: Parse mode (HTML, Markdown, etc.)
            
        Returns:
            True if sent successfully
        """
        if not self._initialized or not self.config.chat_id:
            return False
        
        try:
            coroutine = self.bot.send_message(
                chat_id=self.config.chat_id,
                text=message,
                parse_mode=parse_mode
            )
            return bool(self._run_coroutine(coroutine))
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def _run_coroutine(self, coroutine) -> Any:
        """
        Execute a python-telegram-bot coroutine from synchronous code.

        Handles both environments:
        - No running event loop (normal sync usage): block via asyncio.run()
        - Running event loop (e.g. inside FastAPI): schedule as a task
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)

        task = asyncio.ensure_future(coroutine)
        return task
    
    def notify_entry(self, trade: Dict[str, Any]) -> bool:
        """
        Notify about trade entry.
        
        Args:
            trade: Trade information dictionary
        """
        if not self._should_notify('entry'):
            return False
        
        pair = trade.get('pair', 'Unknown')
        amount = trade.get('amount', 0)
        rate = trade.get('open_rate', 0)
        tag = trade.get('entry_tag', '')
        
        message = f"""
<b>🟢 Entry Signal</b>

<b>Pair:</b> <code>{pair}</code>
<b>Amount:</b> {amount:.8f}
<b>Rate:</b> {rate:.8f}
<b>Tag:</b> {tag}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message)
    
    def notify_exit(self, trade: Dict[str, Any], profit: float, profit_percent: float) -> bool:
        """
        Notify about trade exit.
        
        Args:
            trade: Trade information dictionary
            profit: Profit amount
            profit_percent: Profit percentage
        """
        if not self._should_notify('exit'):
            return False
        
        pair = trade.get('pair', 'Unknown')
        tag = trade.get('exit_tag', '')
        emoji = "🟢" if profit > 0 else "🔴"
        
        message = f"""
<b>{emoji} Exit Signal</b>

<b>Pair:</b> <code>{pair}</code>
<b>Profit:</b> {profit:.4f} ({profit_percent:.2f}%)
<b>Tag:</b> {tag}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message)
    
    def notify_startup(self, version: str, mode: str) -> bool:
        """
        Notify about bot startup.
        
        Args:
            version: Bot version
            mode: Trading mode (dry/live)
        """
        if not self._should_notify('startup'):
            return False
        
        emoji = "🟡" if mode == "dry" else "🟢"
        
        message = f"""
<b>{emoji} Bullseye Started</b>

<b>Version:</b> {version}
<b>Mode:</b> {mode.upper()}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message)
    
    def notify_status(self, status: Dict[str, Any]) -> bool:
        """
        Send status update.
        
        Args:
            status: Status information dictionary
        """
        if not self._should_notify('status'):
            return False
        
        open_trades = status.get('open_trades', 0)
        profit = status.get('profit', 0)
        balance = status.get('balance', 0)
        
        message = f"""
<b>📊 Status Update</b>

<b>Open Trades:</b> {open_trades}
<b>Profit:</b> {profit:.4f}
<b>Balance:</b> {balance:.4f}
<b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message)
    
    def notify_protection_trigger(self, protection: str, until: datetime) -> bool:
        """
        Notify about protection trigger.
        
        Args:
            protection: Protection name
            until: Until when the protection is active
        """
        if not self._should_notify('protection_trigger'):
            return False
        
        message = f"""
<b>🛡️ Protection Triggered</b>

<b>Protection:</b> {protection}
<b>Active Until:</b> {until.strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message)
    
    def send_strategy_message(self, message: str) -> bool:
        """
        Send a custom message from strategy.
        
        Args:
            message: Custom message
        """
        if not self._should_notify('strategy_msg'):
            return False
        
        formatted_message = f"""
<b>📢 Strategy Message</b>

{message}
"""
        return self.send_message(formatted_message)
    
    def _should_notify(self, notification_type: str) -> bool:
        """Check if notification type is enabled."""
        if not self._initialized:
            return False
        
        setting = self.config.notification_settings.get(notification_type, 'off')
        return setting.lower() in ('on', 'true', 'yes', '1')
    
    def start_polling(self):
        """Start command polling (for interactive commands)."""
        # This would start a separate thread to handle commands
        # Implementation depends on the bot architecture
        pass


class TelegramRPC:
    """
    RPC Manager for Telegram integration.
    
    Handles all Telegram-related RPC functionality.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = TelegramConfig(
            enabled=config.get('enabled', False),
            token=config.get('token', ''),
            chat_id=config.get('chat_id', ''),
            notification_settings=config.get('notification_settings', {})
        )
        self.bot = TelegramBot(self.config)
    
    def startup(self, version: str, mode: str):
        """Send startup notification."""
        self.bot.notify_startup(version, mode)
    
    def entry(self, trade: Dict[str, Any]):
        """Send entry notification."""
        self.bot.notify_entry(trade)
    
    def exit(self, trade: Dict[str, Any], profit: float, profit_percent: float):
        """Send exit notification."""
        self.bot.notify_exit(trade, profit, profit_percent)
    
    def status(self, status: Dict[str, Any]):
        """Send status update."""
        self.bot.notify_status(status)
    
    def protection_trigger(self, protection: str, until: datetime):
        """Send protection trigger notification."""
        self.bot.notify_protection_trigger(protection, until)
    
    def strategy_msg(self, message: str):
        """Send strategy message."""
        self.bot.send_strategy_message(message)
