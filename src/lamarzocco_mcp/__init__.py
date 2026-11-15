"""Unofficial MCP server for La Marzocco home espresso machines, built on pylamarzocco."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lamarzocco-mcp")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0"
