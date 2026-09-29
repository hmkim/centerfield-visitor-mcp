"""Compatibility layer over the MCP Python SDK.

mcp 1.x exposes ``mcp.server.fastmcp.FastMCP`` (HTTP options are constructor kwargs);
mcp 2.x renamed it to ``mcp.server.mcpserver.MCPServer`` (HTTP options are ``run()`` kwargs).
The rest of the decorator API (``@server.tool``, ``server.list_tools()``) is identical,
so the server module only needs these two helpers.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _ServerClass  # type: ignore

    MCP_MAJOR = 2
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _ServerClass  # type: ignore

    MCP_MAJOR = 1

try:
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError:  # pragma: no cover - very old SDKs
    TransportSecuritySettings = None  # type: ignore


_LOOPBACK_BINDS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
# Host header values a loopback-bound server may see; ``:*`` is the SDK's any-port wildcard.
LOOPBACK_ALLOWED_HOSTS = [
    "127.0.0.1:*",
    "localhost:*",
    "[::1]:*",
    "127.0.0.1",
    "localhost",
    "[::1]",
]


def resolve_allowed_hosts(settings: Any) -> list[str]:
    """Host allow-list for DNS-rebinding protection.

    ``CF_HTTP_ALLOWED_HOSTS`` wins when set. Otherwise a loopback bind gets the localhost
    allow-list (so a browser page cannot reach the local endpoint via a rebound DNS name);
    a non-loopback bind returns ``[]`` because the public hostname is unknown here.
    """
    hosts = list(settings.allowed_hosts)
    if hosts:
        return hosts
    if settings.http_host in _LOOPBACK_BINDS:
        return list(LOOPBACK_ALLOWED_HOSTS)
    return []


def _http_kwargs(settings: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "host": settings.http_host,
        "port": settings.http_port,
        "streamable_http_path": settings.http_path,
        "stateless_http": settings.http_stateless,
        "json_response": settings.http_json_response,
    }
    if TransportSecuritySettings is not None:
        hosts = resolve_allowed_hosts(settings)
        if hosts:
            kwargs["transport_security"] = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=hosts,
                allowed_origins=[f"https://{h}" for h in hosts] + [f"http://{h}" for h in hosts],
            )
        else:
            logger.warning(
                "CF_HTTP_ALLOWED_HOSTS is empty and CF_HTTP_HOST=%s is not loopback: "
                "DNS-rebinding protection is OFF. Set CF_HTTP_ALLOWED_HOSTS to the public "
                "hostname(s) (e.g. 'mcp.example.com:*') or make sure the HTTPS front "
                "validates Host/Origin.",
                settings.http_host,
            )
            kwargs["transport_security"] = TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            )
    return kwargs


def create_server(name: str, settings: Any, **extra: Any):
    """Instantiate the SDK server class for the configured transport."""
    if MCP_MAJOR == 1 and settings.transport == "streamable-http":
        return _ServerClass(name, **_http_kwargs(settings), **extra)
    return _ServerClass(name, **extra)


def run_server(server: Any, settings: Any) -> None:
    """Block and serve on the configured transport."""
    if settings.transport == "stdio":
        server.run(transport="stdio")
        return
    if MCP_MAJOR == 1:
        server.run(transport="streamable-http")
    else:
        server.run(transport="streamable-http", **_http_kwargs(settings))
