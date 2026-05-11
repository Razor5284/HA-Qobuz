"""Qobuz media player platform."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BROWSE_FAVORITES_ALBUMS,
    BROWSE_FAVORITES_ARTISTS,
    BROWSE_FAVORITES_TRACKS,
    BROWSE_PLAYLISTS,
    BROWSE_ROOT,
    DOMAIN,
)
from .coordinator import QobuzDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.REPEAT_SET
    | MediaPlayerEntityFeature.SELECT_SOURCE
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Qobuz media player from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: QobuzDataUpdateCoordinator = data["coordinator"]
    async_add_entities([QobuzMediaPlayer(coordinator, entry)])


class QobuzMediaPlayer(CoordinatorEntity[QobuzDataUpdateCoordinator], MediaPlayerEntity):
    """Representation of the Qobuz media player entity."""

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

    # ------------------------------------------------------------------
    # Device info — groups entities under one device card
    # ------------------------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        user = self.coordinator.user_info or {}
        email = self._entry.data.get("email", "")
        name = user.get("display_name") or user.get("login") or email
        sub = user.get("credential", {}).get("description", "")
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"Qobuz — {name}",
            manufacturer="Qobuz",
            model=sub or "Streaming Service",
            entry_type=DeviceEntryType.SERVICE,
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def state(self) -> MediaPlayerState:
        playback = self.coordinator.current_playback or {}
        if playback.get("is_playing"):
            return MediaPlayerState.PLAYING
        if playback.get("is_paused"):
            return MediaPlayerState.PAUSED
        return MediaPlayerState.IDLE

    # ------------------------------------------------------------------
    # Now-playing metadata
    # ------------------------------------------------------------------

    @property
    def media_title(self) -> str | None:
        return (self.coordinator.current_playback or {}).get("track", {}).get("title")

    @property
    def media_artist(self) -> str | None:
        return (
            (self.coordinator.current_playback or {})
            .get("track", {})
            .get("artist", {})
            .get("name")
        )

    @property
    def media_album_name(self) -> str | None:
        return (
            (self.coordinator.current_playback or {})
            .get("track", {})
            .get("album", {})
            .get("title")
        )

    @property
    def media_image_url(self) -> str | None:
        covers = (
            (self.coordinator.current_playback or {})
            .get("track", {})
            .get("album", {})
            .get("image", {})
        )
        return covers.get("large") or covers.get("medium") or covers.get("small")

    @property
    def media_duration(self) -> int | None:
        return (self.coordinator.current_playback or {}).get("track", {}).get("duration")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose extra Qobuz-specific attributes."""
        attrs: dict[str, Any] = {}
        user = self.coordinator.user_info
        if user:
            attrs["account_name"] = user.get("display_name") or user.get("login")
            attrs["subscription"] = (
                user.get("credential", {}).get("description")
                or user.get("credential", {}).get("label")
            )
        pb = self.coordinator.current_playback or {}
        track = pb.get("track", {})
        if track:
            attrs["track_id"] = track.get("id")
            attrs["album_id"] = track.get("album", {}).get("id")
            # Audio quality info if present
            attrs["media_format"] = track.get("mime_type")
            attrs["bit_depth"] = track.get("bit_depth")
            attrs["sampling_rate"] = track.get("maximum_sampling_rate")
        return attrs

    # ------------------------------------------------------------------
    # Source (Qobuz Connect placeholder)
    # ------------------------------------------------------------------

    @property
    def source(self) -> str | None:
        return (self.coordinator.current_playback or {}).get("device_name", "This device")

    @property
    def source_list(self) -> list[str]:
        connect = (
            self.hass.data.get(DOMAIN, {})
            .get(self._entry.entry_id, {})
            .get("connect_client")
        )
        if connect and getattr(connect, "devices", None):
            return [d.get("name", "Unknown") for d in connect.devices]
        return ["This device"]

    # ------------------------------------------------------------------
    # Transport controls
    # ------------------------------------------------------------------

    async def async_media_play(self) -> None:
        """Resume playback — logs intent; real control requires Connect."""
        _LOGGER.info("Qobuz play requested (state reflects web player)")
        await self.coordinator.async_request_refresh()

    async def async_media_pause(self) -> None:
        _LOGGER.info("Qobuz pause requested")
        await self.coordinator.async_request_refresh()

    async def async_media_next_track(self) -> None:
        _LOGGER.info("Qobuz next track")
        await self.coordinator.async_request_refresh()

    async def async_media_previous_track(self) -> None:
        _LOGGER.info("Qobuz previous track")
        await self.coordinator.async_request_refresh()

    async def async_set_shuffle(self, shuffle: bool) -> None:
        _LOGGER.info("Qobuz shuffle: %s", shuffle)

    async def async_set_repeat(self, repeat: str) -> None:
        _LOGGER.info("Qobuz repeat: %s", repeat)

    async def async_select_source(self, source: str) -> None:
        _LOGGER.info("Qobuz source: %s", source)
        await self.coordinator.async_request_refresh()

    # ------------------------------------------------------------------
    # Play media
    # ------------------------------------------------------------------

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        """Play a media item.

        For tracks, attempts to get a stream URL (requires app_secret).
        If a stream URL is available it is passed to HA's media_player
        service so a connected local player can receive it.  Without the
        secret the track ID is logged as not-actionable.
        """
        _LOGGER.info("Qobuz play_media: type=%s id=%s", media_type, media_id)

        if media_type in {MediaType.TRACK, "track"}:
            url = await self.coordinator.api.get_track_url(media_id)
            if url:
                _LOGGER.debug("Got stream URL for track %s — sending to HA", media_id)
                await self.hass.services.async_call(
                    "media_player",
                    "play_media",
                    {
                        "entity_id": self.entity_id,
                        "media_content_id": url,
                        "media_content_type": "music",
                    },
                    blocking=False,
                )
            else:
                _LOGGER.info(
                    "No stream URL available for track %s (app_secret not yet scraped); "
                    "use the Qobuz app to start playback",
                    media_id,
                )

        await self.coordinator.async_request_refresh()

    # ------------------------------------------------------------------
    # Browse media — full library tree
    # ------------------------------------------------------------------

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse the Qobuz library."""

        if media_content_id in {None, BROWSE_ROOT}:
            return self._browse_root()

        if media_content_id == BROWSE_PLAYLISTS:
            return self._browse_playlists()

        if media_content_id == BROWSE_FAVORITES_TRACKS:
            return self._browse_favorite_tracks()

        if media_content_id == BROWSE_FAVORITES_ALBUMS:
            return self._browse_favorite_albums()

        if media_content_id == BROWSE_FAVORITES_ARTISTS:
            return self._browse_favorite_artists()

        # Playlist contents
        if media_content_type == MediaType.PLAYLIST:
            tracks = await self.coordinator.api.get_playlist_tracks(media_content_id)
            return _playlist_tracks_node(media_content_id, tracks)

        # Album contents
        if media_content_type == MediaType.ALBUM:
            album = await self.coordinator.api.get_album(media_content_id)
            tracks = album.get("tracks", {}).get("items", [])
            return _album_tracks_node(album, tracks)

        return self._browse_root()

    # ------------------------------------------------------------------
    # Browse helpers
    # ------------------------------------------------------------------

    def _browse_root(self) -> BrowseMedia:
        return BrowseMedia(
            title="Qobuz",
            media_class=MediaClass.APP,
            media_content_type=MediaType.APP,
            media_content_id=BROWSE_ROOT,
            can_play=False,
            can_expand=True,
            children=[
                BrowseMedia(
                    title="My Playlists",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.PLAYLIST,
                    media_content_id=BROWSE_PLAYLISTS,
                    can_play=False,
                    can_expand=True,
                ),
                BrowseMedia(
                    title="Favourite Tracks",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.TRACK,
                    media_content_id=BROWSE_FAVORITES_TRACKS,
                    can_play=False,
                    can_expand=True,
                ),
                BrowseMedia(
                    title="Favourite Albums",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.ALBUM,
                    media_content_id=BROWSE_FAVORITES_ALBUMS,
                    can_play=False,
                    can_expand=True,
                ),
                BrowseMedia(
                    title="Favourite Artists",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaType.ARTIST,
                    media_content_id=BROWSE_FAVORITES_ARTISTS,
                    can_play=False,
                    can_expand=True,
                ),
            ],
        )

    def _browse_playlists(self) -> BrowseMedia:
        children = [
            BrowseMedia(
                title=pl.get("name", "Playlist"),
                media_class=MediaClass.PLAYLIST,
                media_content_type=MediaType.PLAYLIST,
                media_content_id=str(pl.get("id")),
                can_play=False,
                can_expand=True,
                thumbnail=_playlist_thumb(pl),
            )
            for pl in self.coordinator.playlists
        ]
        return BrowseMedia(
            title="My Playlists",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.PLAYLIST,
            media_content_id=BROWSE_PLAYLISTS,
            can_play=False,
            can_expand=True,
            children=children,
        )

    def _browse_favorite_tracks(self) -> BrowseMedia:
        children = [
            BrowseMedia(
                title=t.get("title", "Track"),
                media_class=MediaClass.TRACK,
                media_content_type=MediaType.TRACK,
                media_content_id=str(t.get("id")),
                can_play=True,
                can_expand=False,
                thumbnail=_track_thumb(t),
            )
            for t in self.coordinator.favorite_tracks
        ]
        return BrowseMedia(
            title="Favourite Tracks",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.TRACK,
            media_content_id=BROWSE_FAVORITES_TRACKS,
            can_play=False,
            can_expand=True,
            children=children,
        )

    def _browse_favorite_albums(self) -> BrowseMedia:
        children = [
            BrowseMedia(
                title=_album_title(a),
                media_class=MediaClass.ALBUM,
                media_content_type=MediaType.ALBUM,
                media_content_id=str(a.get("id")),
                can_play=False,
                can_expand=True,
                thumbnail=a.get("image", {}).get("small"),
            )
            for a in self.coordinator.favorite_albums
        ]
        return BrowseMedia(
            title="Favourite Albums",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.ALBUM,
            media_content_id=BROWSE_FAVORITES_ALBUMS,
            can_play=False,
            can_expand=True,
            children=children,
        )

    def _browse_favorite_artists(self) -> BrowseMedia:
        children = [
            BrowseMedia(
                title=a.get("name", "Artist"),
                media_class=MediaClass.ARTIST,
                media_content_type=MediaType.ARTIST,
                media_content_id=str(a.get("id")),
                can_play=False,
                can_expand=False,
                thumbnail=a.get("picture"),
            )
            for a in self.coordinator.favorite_artists
        ]
        return BrowseMedia(
            title="Favourite Artists",
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.ARTIST,
            media_content_id=BROWSE_FAVORITES_ARTISTS,
            can_play=False,
            can_expand=True,
            children=children,
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _playlist_thumb(pl: dict[str, Any]) -> str | None:
    img = pl.get("image") or pl.get("images300") or pl.get("images")
    if isinstance(img, dict):
        return img.get("small") or img.get("thumbnail")
    if isinstance(img, list) and img:
        return img[0]
    return None


def _track_thumb(t: dict[str, Any]) -> str | None:
    return t.get("album", {}).get("image", {}).get("small")


def _album_title(album: dict[str, Any]) -> str:
    title = album.get("title", "Album")
    artist = album.get("artist", {}).get("name")
    return f"{artist} — {title}" if artist else title


def _playlist_tracks_node(playlist_id: str, tracks: list[dict[str, Any]]) -> BrowseMedia:
    children = [
        BrowseMedia(
            title=t.get("title", "Track"),
            media_class=MediaClass.TRACK,
            media_content_type=MediaType.TRACK,
            media_content_id=str(t.get("id")),
            can_play=True,
            can_expand=False,
            thumbnail=_track_thumb(t),
        )
        for t in tracks
    ]
    return BrowseMedia(
        title="Playlist",
        media_class=MediaClass.PLAYLIST,
        media_content_type=MediaType.PLAYLIST,
        media_content_id=playlist_id,
        can_play=False,
        can_expand=True,
        children=children,
    )


def _album_tracks_node(album: dict[str, Any], tracks: list[dict[str, Any]]) -> BrowseMedia:
    thumb = album.get("image", {}).get("small")
    children = [
        BrowseMedia(
            title=t.get("title", "Track"),
            media_class=MediaClass.TRACK,
            media_content_type=MediaType.TRACK,
            media_content_id=str(t.get("id")),
            can_play=True,
            can_expand=False,
            thumbnail=thumb,
        )
        for t in tracks
    ]
    return BrowseMedia(
        title=_album_title(album),
        media_class=MediaClass.ALBUM,
        media_content_type=MediaType.ALBUM,
        media_content_id=str(album.get("id", "")),
        can_play=False,
        can_expand=True,
        children=children,
    )
