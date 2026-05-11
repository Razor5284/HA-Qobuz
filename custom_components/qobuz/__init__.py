"""The Qobuz integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import QobuzAPIClient
from .connect.client import QobuzConnectClient
from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN
from .coordinator import QobuzDataUpdateCoordinator
from .services import async_setup_services

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Qobuz from a config entry."""
    session = async_get_clientsession(hass)
    api = QobuzAPIClient(session)

    # Rehydrate credentials; always re-scrape the live app_id to avoid stale values.
    if "token" in entry.data and "user_id" in entry.data:
        scraped_app_id = await api.scrape_app_id()
        api.set_auth(
            entry.data["token"],
            entry.data["user_id"],
            scraped_app_id or entry.data.get("app_id"),
        )

    # Best-effort: also scrape app_secret to enable stream URL generation
    _app_id, app_secret = await api.scrape_app_credentials()
    if app_secret:
        api.set_app_secret(app_secret)
        _LOGGER.debug("Qobuz app_secret scraped successfully — stream URLs available")
    else:
        _LOGGER.debug("Qobuz app_secret not found — stream URL generation unavailable")

    # Respect poll interval from options, falling back to the default
    poll_interval: int = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    coordinator = QobuzDataUpdateCoordinator(hass, api, update_interval=poll_interval)

    connect_client = QobuzConnectClient(hass, api, entry.entry_id)
    connect_client.start()

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
        "connect_client": connect_client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass)

    # Re-setup when options change (e.g. poll interval updated)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if data and (client := data.get("connect_client")):
            await client.shutdown()
    return unload_ok
