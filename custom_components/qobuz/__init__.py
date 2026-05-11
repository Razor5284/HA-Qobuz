"""The Qobuz integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import QobuzAPIClient
from .connect.client import QobuzConnectClient
from .const import DOMAIN
from .coordinator import QobuzDataUpdateCoordinator
from .services import async_setup_services

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Qobuz from a config entry."""
    session = async_get_clientsession(hass)
    api = QobuzAPIClient(session)

    # Rehydrate token if stored (from previous login)
    # In real flow we store token/user_id in entry.data
    if "token" in entry.data:
        api._token = entry.data["token"]  # type: ignore[attr-defined]
        api._user_id = entry.data.get("user_id")

    coordinator = QobuzDataUpdateCoordinator(hass, api)

    # Connect client (JWT rehydrated from entry if present)
    connect_client = QobuzConnectClient(hass, entry.data.get("jwt_qws"))
    if entry.data.get("token"):
        # Best-effort connect in background
        hass.async_create_background_task(
            connect_client.connect(), "qobuz-connect-ws"
        )

    # Perform initial refresh
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
        "connect_client": connect_client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await async_setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
