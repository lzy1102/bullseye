"""
Tests for the CTP futures gateway (offline: no CTP API and no network).

Guards the two failure modes found against SimNow:

1. openctp-ctp's SWIG bindings take and return `str` for char* fields.
   Passing `bytes` raises TypeError on every request, so the gateway must
   never encode strings and must normalize whatever comes back.
2. The CTP libraries abort at import time unless zh_CN.GB18030 / en_US.UTF-8
   exist, and the legacy SimNow front addresses are dead.
"""
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from bullseye.gateway.future import ctp_gateway  # noqa: E402
from bullseye.gateway.future.ctp_gateway import _to_str  # noqa: E402

DEAD_SIMNOW = "180.168.146.187"


class TestToStr:
    """_to_str normalizes CTP char* fields to str."""

    def test_plain_str_passes_through(self):
        assert _to_str("rb2601") == "rb2601"

    def test_bytes_are_decoded(self):
        assert _to_str(b"rb2601") == "rb2601"

    def test_gbk_error_text(self):
        assert _to_str("用户不合法".encode("gbk")) == "用户不合法"

    def test_undecodable_bytes_do_not_raise(self):
        assert isinstance(_to_str(b"\xff\xfe\x00"), str)

    def test_none_becomes_empty_string(self):
        assert _to_str(None) == ""


class TestSwigStringContract:
    """openctp char* fields are str; bytes break every call."""

    def test_gateway_never_encodes_strings(self):
        source = inspect.getsource(ctp_gateway)
        assert ".encode()" not in source, (
            "CTP char* fields must be str for openctp-ctp; .encode() raises TypeError"
        )

    def test_gateway_never_assigns_bytes_literals(self):
        source = inspect.getsource(ctp_gateway)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or '"""' in stripped:
                continue
            assert not stripped.startswith("field.") or 'b"' not in stripped, (
                "CTP char* fields must be str; bytes literal: %s" % stripped
            )

    def test_ensure_protocol_adds_tcp_scheme(self):
        assert ctp_gateway.CtpGateway._ensure_protocol("1.2.3.4:5") == "tcp://1.2.3.4:5"
        assert ctp_gateway.CtpGateway._ensure_protocol("tcp://1.2.3.4:5") == "tcp://1.2.3.4:5"


class TestSimNowAddresses:
    """The legacy SimNow front addresses no longer answer."""

    def test_config_has_no_dead_address(self):
        for name in ("config.yaml", "config.yaml.example"):
            path = ROOT / name
            if not path.exists():
                continue
            assert DEAD_SIMNOW not in path.read_text(encoding="utf-8"), (
                "%s still points at the retired SimNow front" % name
            )

    def test_current_simnow_front_is_configured(self):
        path = ROOT / "config.yaml.example"
        if not path.exists():
            pytest.skip("config.yaml.example not present")
        text = path.read_text(encoding="utf-8")
        assert "tcp://182.254.243.31:30001" in text
        assert "tcp://182.254.243.31:30011" in text


class TestDockerfileLocale:
    """openctp-ctp aborts at import without zh_CN.GB18030 / en_US.UTF-8."""

    def test_dockerfile_generates_required_locales(self):
        path = ROOT / "Dockerfile"
        if not path.exists():
            pytest.skip("Dockerfile not present")
        text = path.read_text(encoding="utf-8")
        assert "zh_CN.GB18030" in text
        assert "en_US.UTF-8" in text
