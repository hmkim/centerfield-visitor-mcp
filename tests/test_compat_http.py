"""DNS-rebinding protection defaults for the streamable-http transport (_compat._http_kwargs)."""

import logging

import pytest

from centerfield_visitor_mcp import _compat
from centerfield_visitor_mcp.config import settings

pytestmark = pytest.mark.skipif(
    _compat.TransportSecuritySettings is None, reason="SDK without TransportSecuritySettings"
)


def _http_kwargs(monkeypatch, host: str, allowed: str = ""):
    monkeypatch.setattr(settings, "http_host", host)
    monkeypatch.setattr(settings, "http_allowed_hosts", allowed)
    return _compat._http_kwargs(settings)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]"])
def test_loopback_bind_keeps_protection_on_with_localhost_allowlist(monkeypatch, host):
    ts = _http_kwargs(monkeypatch, host)["transport_security"]
    assert ts.enable_dns_rebinding_protection is True
    assert ts.allowed_hosts == _compat.LOOPBACK_ALLOWED_HOSTS
    # ``host:*`` is the SDK's any-port wildcard; origins mirror the hosts for both schemes.
    assert "127.0.0.1:*" in ts.allowed_hosts and "localhost:*" in ts.allowed_hosts
    assert "http://localhost:*" in ts.allowed_origins
    assert "https://127.0.0.1:*" in ts.allowed_origins


def test_explicit_allowlist_is_used_as_is(monkeypatch):
    ts = _http_kwargs(monkeypatch, "0.0.0.0", " mcp.example.com:* , localhost:8000 ")["transport_security"]
    assert ts.enable_dns_rebinding_protection is True
    assert ts.allowed_hosts == ["mcp.example.com:*", "localhost:8000"]
    assert "https://mcp.example.com:*" in ts.allowed_origins


def test_explicit_allowlist_overrides_loopback_default(monkeypatch):
    ts = _http_kwargs(monkeypatch, "127.0.0.1", "mcp.example.com")["transport_security"]
    assert ts.allowed_hosts == ["mcp.example.com"]


def test_public_bind_without_allowlist_disables_protection_and_warns(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="centerfield_visitor_mcp._compat"):
        ts = _http_kwargs(monkeypatch, "0.0.0.0")["transport_security"]
    assert ts.enable_dns_rebinding_protection is False
    assert "CF_HTTP_ALLOWED_HOSTS" in caplog.text
    assert "0.0.0.0" in caplog.text


def test_loopback_default_does_not_warn(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="centerfield_visitor_mcp._compat"):
        _http_kwargs(monkeypatch, "127.0.0.1")
    assert "CF_HTTP_ALLOWED_HOSTS" not in caplog.text


def test_resolve_allowed_hosts_matrix(monkeypatch):
    monkeypatch.setattr(settings, "http_allowed_hosts", "")
    monkeypatch.setattr(settings, "http_host", "127.0.0.1")
    assert _compat.resolve_allowed_hosts(settings) == _compat.LOOPBACK_ALLOWED_HOSTS
    monkeypatch.setattr(settings, "http_host", "0.0.0.0")
    assert _compat.resolve_allowed_hosts(settings) == []
    monkeypatch.setattr(settings, "http_allowed_hosts", "a.example:*")
    assert _compat.resolve_allowed_hosts(settings) == ["a.example:*"]
