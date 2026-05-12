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
SERVICE_SET_STREAMING_QUALITY = "set_streaming_quality"

REFRESH_SCHEMA = vol.Schema({vol.Optional("config_entry"): cv.string})
TRANSFER_SCHEMA = vol.Schema({
    vol.Required("device_id"): cv.string,
    vol.Optional("config_entry"): cv.string,
})
QUALITY_SCHEMA = vol.Schema({
    vol.Required("quality"): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
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
        wanted = call.data.get("config_entry")
        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            if wanted and entry_id != wanted:
                continue
            client = data.get("connect_client")
            if client:
                await client.transfer_playback(device_id)
                _LOGGER.info(
                    "Transfer requested to device %s (entry %s)", device_id, entry_id
                )
                return
        _LOGGER.warning("No Qobuz connect client found for transfer_playback")

    async def _set_streaming_quality(call: ServiceCall) -> None:
        """Set max streaming quality via Qobuz Connect."""
        quality = int(call.data["quality"])
        wanted = call.data.get("config_entry")
        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            if wanted and entry_id != wanted:
                continue
            client = data.get("connect_client")
            if client and client.connected:
                await client.set_max_streaming_quality(quality)
                _LOGGER.info(
                    "Qobuz Connect max streaming quality set to %s (entry %s)",
                    quality,
                    entry_id,
                )
                return
        _LOGGER.warning("No connected Qobuz Connect client for set_streaming_quality")

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
    if not hass.services.has_service(DOMAIN, SERVICE_SET_STREAMING_QUALITY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_STREAMING_QUALITY,
            _set_streaming_quality,
            schema=QUALITY_SCHEMA,
        )
