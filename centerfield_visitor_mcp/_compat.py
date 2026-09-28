"""Compatibility layer over the MCP Python SDK.

mcp 1.x exposes ``mcp.server.fastmcp.FastMCP`` (HTTP options are constructor kwargs);
mcp 2.x renamed it to ``mcp.server.mcpserver.MCPServer`` (HTTP options are ``run()`` kwargs).
The rest of the decorator API (``@server.tool``, ``server.list_tools()``) is identical,
so the server module only needs these two helpers.
"""

from __future__ import annotations

from typing import Any

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


def _http_kwargs(settings: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "host": settings.http_host,
        "port": settings.http_port,
        "streamable_http_path": settings.http_path,
        "stateless_http": settings.http_stateless,
        "json_response": settings.http_json_response,
    }
    if TransportSecuritySettings is not None:
        hosts = settings.allowed_hosts
        if hosts:
            kwargs["transport_security"] = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=hosts,
                allowed_origins=[f"https://{h}" for h in hosts] + [f"http://{h}" for h in hosts],
            )
        else:
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
