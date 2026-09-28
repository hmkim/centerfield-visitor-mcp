"""Centerfield Visitor Reservation MCP Server."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("centerfield-visitor-mcp")
except PackageNotFoundError:  # running from a source checkout without install
    __version__ = "0.0.0+local"

__all__ = ["__version__"]
