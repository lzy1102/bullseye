"""
RPC Module for Bullseye

Provides RPC functionality for notifications and control.
"""

from .telegram import TelegramRPC, TelegramBot, TelegramConfig
from .webhook import WebhookRPC, WebhookClient, WebhookConfig
from .api_server import create_app, start_api_server

__all__ = [
    'TelegramRPC',
    'TelegramBot',
    'TelegramConfig',
    'WebhookRPC',
    'WebhookClient',
    'WebhookConfig',
    'create_app',
    'start_api_server',
]
