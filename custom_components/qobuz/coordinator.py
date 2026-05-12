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

    from .connect.client import QobuzConnectClient

_LOGGER = logging.getLogger(__name__)


def _rest_playback_is_inactive(rest: dict[str, Any] | None) -> bool:
    """True when REST /player/getState is missing or does not describe active media."""
    if rest is None:
        return True
    if rest.get("is_playing") or rest.get("is_paused"):
        return False
    track = rest.get("track")
    return not (isinstance(track, dict) and track)


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
        self.connect_client: QobuzConnectClient | None = None
        # Exposed state — kept in sync by _async_update_data
        self.playlists: list[dict[str, Any]] = []
        self.current_playback: dict[str, Any] | None = None
        self.user_info: dict[str, Any] = {}
        self.favorite_tracks: list[dict[str, Any]] = []
        self.favorite_albums: list[dict[str, Any]] = []
        self.favorite_artists: list[dict[str, Any]] = []
        # Cache for track metadata fetched via Connect track IDs
        self._track_cache: dict[int, dict[str, Any]] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from Qobuz APIs."""
        try:
            # Core polls on every interval
            self.playlists = await self.api.get_playlists()
            rest_playback = await self.api.get_current_playback()
            self.current_playback = rest_playback

            # If REST is empty/idle (or None), merge Connect — avoids ``if not {}`` edge cases
            # and accounts for 200 responses that omit real playback fields.
            if _rest_playback_is_inactive(rest_playback) and self.connect_client:
                connect_playback = await self._build_playback_from_connect()
                if connect_playback:
                    self.current_playback = connect_playback

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

    async def _build_playback_from_connect(self) -> dict[str, Any] | None:
        """Build a playback dict from Connect WebSocket state if active."""
        cc = self.connect_client
        if not cc or not cc.connected:
            return None

        raw_ps = getattr(cc, "playing_state", 0)
        ps = raw_ps if isinstance(raw_ps, int) else 0
        # 1 = PLAYING_STATE_STOPPED — do not reuse stale queue hints as "now playing"
        if ps == 1:
            return None

        if not (cc.is_playing or cc.is_paused) and (ps != 0 or cc.current_track_id is None):
            # UNKNOWN(0) with a resolved queue track: still surface metadata until
            # an explicit renderer state arrives (common right after WS connect).
            return None

        if not cc.current_track_id:
            return {
                "is_playing": cc.is_playing,
                "is_paused": cc.is_paused,
                "source": "connect",
                "device_name": cc.active_device_name,
            }

        track_info = await self._fetch_track_metadata(cc.current_track_id)
        # UNKNOWN + timing hints: treat as playing for HA state (position/duration
        # updates usually follow immediately).
        ambiguous_playing = bool(
            ps == 0
            and not cc.is_paused
            and (cc.current_position > 0 or cc.duration > 0)
        )
        return {
            "is_playing": cc.is_playing or ambiguous_playing,
            "is_paused": cc.is_paused,
            "track": track_info,
            "position": cc.current_position,
            "source": "connect",
            "device_name": cc.active_device_name,
        }

    async def _fetch_track_metadata(self, track_id: int) -> dict[str, Any]:
        """Fetch track metadata, using a simple cache to avoid redundant API calls."""
        if track_id in self._track_cache:
            return self._track_cache[track_id]
        try:
            track_info = await self.api.get_track_info(str(track_id))
            self._track_cache[track_id] = track_info
            # Keep cache bounded
            if len(self._track_cache) > 50:
                oldest = next(iter(self._track_cache))
                del self._track_cache[oldest]
            return track_info
        except (QobuzAPIError, Exception) as err:  # noqa: BLE001
            _LOGGER.debug("Could not fetch track info for %s: %s", track_id, err)
            return {"id": track_id, "title": f"Track {track_id}"}
