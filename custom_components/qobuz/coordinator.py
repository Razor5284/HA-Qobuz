"""Data update coordinator for Qobuz integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import QobuzAPIClient, QobuzAPIError
from .const import DEFAULT_POLL_INTERVAL, DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class QobuzDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to fetch Qobuz data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: QobuzAPIClient,
        update_interval: int = DEFAULT_POLL_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.api = api
        self.playlists: list[dict[str, Any]] = []
        self.current_playback: dict[str, Any] | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from Qobuz."""
        try:
            self.playlists = await self.api.get_playlists()
            self.current_playback = await self.api.get_current_playback()
            return {
                "playlists": self.playlists,
                "current_playback": self.current_playback,
                "authenticated": self.api.is_authenticated,
            }
        except QobuzAPIError as err:
            raise UpdateFailed(f"Error communicating with Qobuz API: {err}") from err
