"""
Webhook Integration for Bullseye

Provides webhook functionality for external notifications.
"""
import logging
import json
from typing import Dict, Any
from datetime import datetime
from dataclasses import dataclass
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


@dataclass
class WebhookConfig:
    """Webhook configuration."""
    enabled: bool = False
    url: str = ""
    format: str = "json"  # json, form, raw
    retry_count: int = 3
    timeout: int = 10

    def __post_init__(self):
        if self.format not in ('json', 'form', 'raw'):
            self.format = 'json'


class WebhookClient:
    """
    Webhook client for sending notifications.
    
    Supports:
    - JSON format
    - Form data format
    - Raw format
    - Retry mechanism
    """

    def __init__(self, config: WebhookConfig):
        self.config = config
        self.session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=config.retry_count,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def send(self, event: str, data: Dict[str, Any]) -> bool:
        """
        Send webhook notification.
        
        Args:
            event: Event type (entry, exit, etc.)
            data: Event data
            
        Returns:
            True if sent successfully
        """
        if not self.config.enabled or not self.config.url:
            return False

        try:
            payload = self._format_payload(event, data)
            headers = self._get_headers()

            response = self.session.post(
                self.config.url,
                data=payload if self.config.format == 'form' else None,
                json=payload if self.config.format == 'json' else None,
                headers=headers,
                timeout=self.config.timeout
            )

            response.raise_for_status()
            logger.debug(f"Webhook sent successfully: {event}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send webhook: {e}")
            return False

    def _format_payload(self, event: str, data: Dict[str, Any]) -> Any:
        """Format payload based on configuration."""
        if self.config.format == 'json':
            return {
                'event': event,
                'timestamp': datetime.now().isoformat(),
                'data': data
            }
        elif self.config.format == 'form':
            return {
                'event': event,
                'timestamp': datetime.now().isoformat(),
                **{f'data_{k}': v for k, v in data.items()}
            }
        else:  # raw
            return json.dumps({
                'event': event,
                'timestamp': datetime.now().isoformat(),
                'data': data
            })

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers based on format."""
        if self.config.format == 'json':
            return {'Content-Type': 'application/json'}
        elif self.config.format == 'form':
            return {'Content-Type': 'application/x-www-form-urlencoded'}
        else:
            return {'Content-Type': 'text/plain'}


class WebhookRPC:
    """
    RPC Manager for Webhook integration.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = WebhookConfig(
            enabled=config.get('enabled', False),
            url=config.get('url', ''),
            format=config.get('format', 'json'),
            retry_count=config.get('retry_count', 3),
            timeout=config.get('timeout', 10)
        )
        self.client = WebhookClient(self.config)

    def startup(self, version: str, mode: str):
        """Send startup notification."""
        self.client.send('startup', {
            'version': version,
            'mode': mode,
            'timestamp': datetime.now().isoformat()
        })

    def entry(self, trade: Dict[str, Any]):
        """Send entry notification."""
        self.client.send('entry', trade)

    def exit(self, trade: Dict[str, Any], profit: float, profit_percent: float):
        """Send exit notification."""
        self.client.send('exit', {
            **trade,
            'profit': profit,
            'profit_percent': profit_percent
        })

    def status(self, status: Dict[str, Any]):
        """Send status update."""
        self.client.send('status', status)

    def protection_trigger(self, protection: str, until: datetime):
        """Send protection trigger notification."""
        self.client.send('protection_trigger', {
            'protection': protection,
            'until': until.isoformat()
        })
