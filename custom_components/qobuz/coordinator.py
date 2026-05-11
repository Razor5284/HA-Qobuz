"""Data update coordinator for Qobuz integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import QobuzAPIClient, QobuzAPIError, QobuzAuthError
from .const import DEFAULT_POLL_INTERVAL, DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class QobuzDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls Qobuz for library and playback state."""

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
        # Exposed state — kept in sync by _async_update_data
        self.playlists: list[dict[str, Any]] = []
        self.current_playback: dict[str, Any] | None = None
        self.user_info: dict[str, Any] = {}
        self.favorite_tracks: list[dict[str, Any]] = []
        self.favorite_albums: list[dict[str, Any]] = []
        self.favorite_artists: list[dict[str, Any]] = []

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from Qobuz APIs."""
        try:
            # Core polls on every interval
            self.playlists = await self.api.get_playlists()
            self.current_playback = await self.api.get_current_playback()

            # User profile and favorites — fetched once per interval (cheap, cached by Qobuz)
            if not self.user_info:
                self.user_info = await self.api.get_user_info()

            self.favorite_tracks = await self.api.get_favorite_tracks()
            self.favorite_albums = await self.api.get_favorite_albums()
            self.favorite_artists = await self.api.get_favorite_artists()

            return {
                "playlists": self.playlists,
                "current_playback": self.current_playback,
                "user_info": self.user_info,
                "favorite_tracks": self.favorite_tracks,
                "favorite_albums": self.favorite_albums,
                "favorite_artists": self.favorite_artists,
                "authenticated": self.api.is_authenticated,
            }
        except QobuzAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except QobuzAPIError as err:
            raise UpdateFailed(f"Error communicating with Qobuz API: {err}") from err
