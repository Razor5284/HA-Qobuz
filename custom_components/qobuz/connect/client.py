"""Basic Qobuz Connect WebSocket client (scaffold)."""

from __future__ import annotations

import logging
from typing import Any

import websockets
from homeassistant.core import HomeAssistant

from ..const import QOBUZ_WS_BASE

_LOGGER = logging.getLogger(__name__)


class QobuzConnectClient:
    """Client for Qobuz Connect (device enumeration + control)."""

    def __init__(self, hass: HomeAssistant, jwt: str | None = None) -> None:
        self.hass = hass
        self._jwt = jwt
        self._ws: websockets.WebSocketClientProtocol | None = None
        self.devices: list[dict[str, Any]] = []

    async def connect(self) -> None:
        """Establish WS connection using JWT (obtained via qws/createToken)."""
        if not self._jwt:
            _LOGGER.warning("No JWT for Connect; skipping WS")
            return
        try:
            self._ws = await websockets.connect(QOBUZ_WS_BASE)
            # In real: send auth frame with jwt, subscribe to notifications
            _LOGGER.info("Connected to Qobuz Connect WS (scaffold)")
            # TODO: handle incoming protobuf messages for device list / state
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Connect WS failed: %s", err)

    async def discover_devices(self) -> list[dict[str, Any]]:
        """Return known or discovered Connect devices."""
        # Phase 2+: mDNS + WS query or REST /device/list if exists
        # For scaffold return mock + any configured
        return self.devices or [{"id": "self", "name": "This Home Assistant instance"}]

    async def transfer_playback(self, device_id: str) -> None:
        """Transfer current stream to device (controller action)."""
        _LOGGER.info("Request transfer to %s (stub)", device_id)
        # Would send protobuf command over WS or REST

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()