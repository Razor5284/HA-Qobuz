"""Qobuz Connect protocol handling (WebSocket + device management)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import QobuzConnectClient


def __getattr__(name: str):
    if name == "QobuzConnectClient":
        from .client import QobuzConnectClient

        return QobuzConnectClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["QobuzConnectClient"]
