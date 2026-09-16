"""
Test bot gateway routing and market-aware connection parameters.
"""
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from bullseye.bot.bot import BullseyeBot
from bullseye.configuration.config import Config
from bullseye.gateway.crypto.ccxt_gateway import CcxtGateway
from bullseye.gateway.dryrun.dryrun_gateway import DryRunGateway
from bullseye.gateway.future.ctp_gateway import CtpGateway
from bullseye.gateway.stock.miniqmt_gateway import MiniQmtGateway
from bullseye.gateway.template.gateway_template import TemplateGateway
from bullseye.trader.eventengine import EventEngine


def make_bot(market_type: str = "crypto", dry_run: bool = False, **entries) -> BullseyeBot:
    config = Config()
    config.set("dry_run", dry_run)
    config.set("market_type", market_type)
    for key, value in entries.items():
        config.set(key, value)

    bot = BullseyeBot(config)
    bot._event_engine = EventEngine()
    return bot


class TestGatewayRouting:
    def test_crypto_live_uses_ccxt(self):
        bot = make_bot("crypto", dry_run=False)
        gateway = bot._create_gateway()
        assert isinstance(gateway, CcxtGateway)

    def test_stock_live_uses_miniqmt(self):
        bot = make_bot("stock", dry_run=False)
        gateway = bot._create_gateway()
        assert isinstance(gateway, MiniQmtGateway)

    def test_future_live_uses_ctp(self):
        bot = make_bot("future", dry_run=False)
        gateway = bot._create_gateway()
        assert isinstance(gateway, CtpGateway)

    def test_custom_gateway_loaded_by_path(self):
        bot = make_bot(
            "custom", dry_run=False,
            custom={
                "gateway": "bullseye.gateway.template.gateway_template.TemplateGateway",
            },
        )
        gateway = bot._create_gateway()
        assert isinstance(gateway, TemplateGateway)

    def test_custom_gateway_bad_path_raises(self):
        bot = make_bot("custom", dry_run=False, custom={"gateway": "no_module.NoClass"})
        with pytest.raises(ImportError):
            bot._create_gateway()

    def test_custom_gateway_missing_config_raises(self):
        bot = make_bot("custom", dry_run=False, custom={})
        with pytest.raises(ValueError, match="custom.gateway"):
            bot._create_gateway()

    @pytest.mark.parametrize("market,inner_type", [
        ("crypto", CcxtGateway),
        ("stock", MiniQmtGateway),
        ("future", CtpGateway),
    ])
    def test_dry_run_wraps_real_gateway(self, market, inner_type):
        bot = make_bot(market, dry_run=True)
        gateway = bot._create_gateway()
        assert isinstance(gateway, DryRunGateway)
        assert isinstance(gateway._real_gateway, inner_type)


class TestConnectKwargs:
    def test_stock_kwargs_from_stock_section(self):
        bot = make_bot("stock", stock={
            "qmt_path": "D:\\QMT\\userdata_mini",
            "session_id": 42,
            "account_id": "ACC123",
        })
        kwargs = bot._gateway_connect_kwargs()
        assert kwargs == {
            "qmt_path": "D:\\QMT\\userdata_mini",
            "session_id": 42,
            "account_id": "ACC123",
        }

    def test_future_kwargs_from_future_section(self):
        bot = make_bot("future", future={
            "userid": "u1", "password": "p1", "brokerid": "9999",
            "td_address": "tcp://td", "md_address": "tcp://md",
        })
        kwargs = bot._gateway_connect_kwargs()
        assert kwargs["user_id"] == "u1"
        assert kwargs["broker_id"] == "9999"
        assert kwargs["td_address"] == "tcp://td"

    def test_custom_kwargs_passthrough(self):
        bot = make_bot("custom", custom={
            "gateway": "x.y.Z",
            "base_url": "http://127.0.0.1:8000",
            "kill_switch_file": ".stop",
        })
        kwargs = bot._gateway_connect_kwargs()
        assert kwargs["base_url"] == "http://127.0.0.1:8000"
        assert kwargs["kill_switch_file"] == ".stop"
        assert "gateway" not in kwargs

    def test_crypto_kwargs_from_exchange_section(self):
        bot = make_bot("crypto", exchange={
            "name": "binance", "key": "K", "secret": "S", "sandbox": True,
        })
        kwargs = bot._gateway_connect_kwargs()
        assert kwargs == {
            "api_key": "K", "secret": "S", "passphrase": "", "sandbox": True,
        }
