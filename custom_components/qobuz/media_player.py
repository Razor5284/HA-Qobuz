"""Qobuz media player platform."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_ALBUM_ID, ATTR_PLAYLIST_ID, ATTR_QOBUZ_TRACK_ID, DOMAIN
from .coordinator import QobuzDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.SELECT_SOURCE  # for future Connect devices
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Qobuz media player from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: QobuzDataUpdateCoordinator = data["coordinator"]
    async_add_entities([QobuzMediaPlayer(coordinator, entry)])


class QobuzMediaPlayer(CoordinatorEntity[QobuzDataUpdateCoordinator], MediaPlayerEntity):
    """Representation of a Qobuz playback session."""

    _attr_has_entity_name = True
    _attr_name = "Qobuz"
    _attr_supported_features = SUPPORTED_FEATURES
    _attr_media_content_type = MediaType.MUSIC

    def __init__(
        self, coordinator: QobuzDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_player"

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the player."""
        playback = self.coordinator.current_playback or {}
        if playback.get("is_playing"):
            return MediaPlayerState.PLAYING
        if playback.get("is_paused"):
            return MediaPlayerState.PAUSED
        return MediaPlayerState.IDLE

    @property
    def media_title(self) -> str | None:
        playback = self.coordinator.current_playback or {}
        return playback.get("track", {}).get("title")

    @property
    def media_artist(self) -> str | None:
        playback = self.coordinator.current_playback or {}
        return playback.get("track", {}).get("artist", {}).get("name")

    @property
    def media_album_name(self) -> str | None:
        playback = self.coordinator.current_playback or {}
        return playback.get("track", {}).get("album", {}).get("title")

    @property
    def media_image_url(self) -> str | None:
        playback = self.coordinator.current_playback or {}
        # Prefer large cover
        covers = playback.get("track", {}).get("album", {}).get("image", {})
        return covers.get("large") or covers.get("medium")

    @property
    def source(self) -> str | None:
        """Current active device/source (placeholder for Connect)."""
        playback = self.coordinator.current_playback or {}
        return playback.get("device_name", "This device")

    @property
    def source_list(self) -> list[str]:
        """List of available sources (Connect devices)."""
        # Wired via connect_client in __init__
        connect = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("connect_client")
        if connect and hasattr(connect, "devices") and connect.devices:
            return [d.get("name", "Unknown") for d in connect.devices]
        return ["This device"]  # fallback; Phase 2 populates via WS/mDNS

    async def async_media_play(self) -> None:
        """Resume playback."""
        # In real: call API resume
        _LOGGER.info("Qobuz play requested")
        # For MVP, just update local state if possible
        await self.coordinator.async_request_refresh()

    async def async_media_pause(self) -> None:
        """Pause playback."""
        _LOGGER.info("Qobuz pause requested")
        await self.coordinator.async_request_refresh()

    async def async_media_next_track(self) -> None:
        """Skip to next track."""
        _LOGGER.info("Qobuz next track")
        await self.coordinator.async_request_refresh()

    async def async_media_previous_track(self) -> None:
        """Skip to previous track."""
        _LOGGER.info("Qobuz previous track")
        await self.coordinator.async_request_refresh()

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        """Play a specific media item."""
        _LOGGER.info("Playing Qobuz media: %s (%s)", media_id, media_type)
        if media_type == MediaType.TRACK or "track" in media_id:
            # Assume media_id is qobuz track id
            await self.coordinator.api.play_track(media_id)
        await self.coordinator.async_request_refresh()

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse Qobuz library (playlists, favorites, etc.)."""
        if media_content_id is None:
            # Root: show playlists and favorites
            children = []
            for pl in self.coordinator.playlists:
                children.append(
                    BrowseMedia(
                        title=pl.get("name", "Playlist"),
                        media_class=MediaType.PLAYLIST,
                        media_content_type=MediaType.PLAYLIST,
                        media_content_id=str(pl.get("id")),
                        can_play=True,
                        can_expand=True,
                        thumbnail=pl.get("image", {}).get("small"),
                    )
                )
            return BrowseMedia(
                title="Qobuz Library",
                media_class=MediaType.APP,
                media_content_type=MediaType.APP,
                media_content_id="root",
                can_play=False,
                can_expand=True,
                children=children,
            )

        # If it's a playlist id, return its tracks
        if media_content_type == MediaType.PLAYLIST:
            tracks = await self.coordinator.api.get_playlist_tracks(media_content_id)
            children = []
            for track in tracks:
                children.append(
                    BrowseMedia(
                        title=track.get("title", "Track"),
                        media_class=MediaType.TRACK,
                        media_content_type=MediaType.TRACK,
                        media_content_id=str(track.get("id")),
                        can_play=True,
                        can_expand=False,
                        thumbnail=track.get("album", {}).get("image", {}).get("small"),
                    )
                )
            return BrowseMedia(
                title=f"Playlist {media_content_id}",
                media_class=MediaType.PLAYLIST,
                media_content_type=MediaType.PLAYLIST,
                media_content_id=media_content_id,
                can_play=True,
                can_expand=False,
                children=children,
            )

        # Fallback root
        return await self.async_browse_media()

    async def async_select_source(self, source: str) -> None:
        """Select a playback source (Connect device)."""
        _LOGGER.info("Selecting Qobuz source: %s", source)
        # Phase 2: trigger transfer via Connect or API
        await self.coordinator.async_request_refresh()