"""Custom services for Qobuz integration (selective, validated endpoints only)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH_LIBRARY = "refresh_library"
SERVICE_TRANSFER_PLAYBACK = "transfer_playback"

REFRESH_SCHEMA = vol.Schema({vol.Optional("config_entry"): cv.string})
TRANSFER_SCHEMA = vol.Schema({
    vol.Required("device_id"): cv.string,
    vol.Optional("config_entry"): cv.string,
})


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register selective custom services."""

    async def _refresh_library(call: ServiceCall) -> None:
        """Refresh Qobuz library data (playlists, etc.)."""
        # Could target specific entry; for simplicity refresh all
        for data in hass.data.get(DOMAIN, {}).values():
            if coord := data.get("coordinator"):
                await coord.async_refresh()
        _LOGGER.info("Qobuz library refreshed via service")

    async def _transfer_playback(call: ServiceCall) -> None:
        """Transfer current playback to a Connect device."""
        device_id = call.data["device_id"]
        # In real: find connect_client and call transfer
        _LOGGER.info("Transfer requested to device %s (stub)", device_id)

    # Guard against re-registration when async_setup_entry is called more than once
    # (e.g. during re-auth or after an options update).
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_LIBRARY):
        hass.services.async_register(
            DOMAIN, SERVICE_REFRESH_LIBRARY, _refresh_library, schema=REFRESH_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_TRANSFER_PLAYBACK):
        hass.services.async_register(
            DOMAIN, SERVICE_TRANSFER_PLAYBACK, _transfer_playback, schema=TRANSFER_SCHEMA
        )
