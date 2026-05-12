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
    RepeatMode,
)
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
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
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.VOLUME_SET
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

    async def async_added_to_hass(self) -> None:
        """Subscribe to Qobuz Connect device updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_connect_{self._entry.entry_id}",
                self._on_connect_update,
            )
        )

    def _on_connect_update(self, *_args: Any) -> None:
        """Connect pushed new devices or playback — refresh entity + coordinator."""
        self.schedule_update_ha_state()
        self.hass.async_create_task(self._coordinator_refresh_now())

    def _connect_client(self):  # noqa: ANN202
        if not self.hass:
            return None
        return (
            self.hass.data.get(DOMAIN, {})
            .get(self._entry.entry_id, {})
            .get("connect_client")
        )

    async def _coordinator_refresh_now(self) -> None:
        """Refresh playback state immediately (avoids full library poll + debounce)."""
        try:
            await self.coordinator.async_refresh_playback()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Qobuz coordinator refresh failed: %s", err)

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
        # Also check Connect client directly for real-time state
        client = self._connect_client()
        if client and client.connected:
            if client.is_playing:
                return MediaPlayerState.PLAYING
            if client.is_paused:
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
        pb = self.coordinator.current_playback or {}
        d = (pb.get("track") or {}).get("duration")
        if d is not None:
            return int(d)
        client = self._connect_client()
        if client and client.connected and client.duration:
            return int(client.duration)
        return None

    @property
    def media_position(self) -> int | None:
        """Playback position in seconds (Connect sends milliseconds)."""
        pb = self.coordinator.current_playback or {}
        if "position" in pb:
            return int(pb["position"]) // 1000
        client = self._connect_client()
        if client and client.connected:
            return int(client.current_position) // 1000
        return None

    @property
    def shuffle(self) -> bool | None:
        """Shuffle state when Qobuz Connect reports it."""
        client = self._connect_client()
        if client and client.connected:
            return client.shuffle_mode
        return None

    @property
    def repeat(self) -> RepeatMode | None:
        """Repeat mode from last Connect ``LoopMode`` ack (if known)."""
        client = self._connect_client()
        if not client or not client.connected or client.loop_mode is None:
            return None
        from qconnect_common_pb2 import LoopMode  # noqa: PLC0415

        mode = int(client.loop_mode)
        if mode == LoopMode.LOOP_MODE_REPEAT_ONE:
            return RepeatMode.ONE
        if mode == LoopMode.LOOP_MODE_REPEAT_ALL:
            return RepeatMode.ALL
        if mode == LoopMode.LOOP_MODE_OFF:
            return RepeatMode.OFF
        return None

    @property
    def volume_level(self) -> float | None:
        """Volume for the active Connect renderer (0..1), when reported."""
        client = self._connect_client()
        if client and client.connected:
            return client.volume_level
        return None

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
        cc = self._connect_client()
        if cc:
            attrs["qobuz_connect_connected"] = cc.connected
            attrs["qobuz_connect_devices"] = len(cc.devices)
            if cc.connect_max_audio_quality is not None:
                attrs["connect_max_audio_quality"] = cc.connect_max_audio_quality
        return attrs

    # ------------------------------------------------------------------
    # Source (Qobuz Connect placeholder)
    # ------------------------------------------------------------------

    @property
    def source(self) -> str | None:
        client = self._connect_client()
        if client and client.active_device_name:
            return client.active_device_name
        return (self.coordinator.current_playback or {}).get("device_name")

    @property
    def source_list(self) -> list[str]:
        client = self._connect_client()
        if client is None:
            return ["This device"]
        names = [d.get("name", "Unknown") for d in client.devices]
        if names:
            return names
        return ["This device"]

    # ------------------------------------------------------------------
    # Transport controls
    # ------------------------------------------------------------------

    async def async_media_play(self) -> None:
        """Resume playback via Qobuz Connect when the WS session is active."""
        client = self._connect_client()
        if client and client.connected:
            await client.media_play()
        await self._coordinator_refresh_now()

    async def async_media_pause(self) -> None:
        client = self._connect_client()
        if client and client.connected:
            await client.media_pause()
        await self._coordinator_refresh_now()

    async def async_media_next_track(self) -> None:
        """Skip to the next track via Qobuz Connect."""
        client = self._connect_client()
        if client and client.connected:
            await client.media_next_track()
        await self._coordinator_refresh_now()

    async def async_media_previous_track(self) -> None:
        """Skip to the previous track via Qobuz Connect."""
        client = self._connect_client()
        if client and client.connected:
            await client.media_previous_track()
        await self._coordinator_refresh_now()

    async def async_media_seek(self, position: float) -> None:
        """Seek the active Connect session (position in seconds)."""
        client = self._connect_client()
        if client and client.connected:
            await client.media_seek(position)
        await self._coordinator_refresh_now()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume on the active Connect renderer (0..1)."""
        client = self._connect_client()
        if client and client.connected:
            await client.set_volume_level(volume)
        await self._coordinator_refresh_now()

    async def async_set_shuffle(self, shuffle: bool) -> None:
        client = self._connect_client()
        if client and client.connected:
            await client.set_shuffle_mode(shuffle)
        await self._coordinator_refresh_now()

    async def async_set_repeat(self, repeat: Any) -> None:
        val = getattr(repeat, "value", repeat)
        raw = str(val).lower()
        if "one" in raw:
            mode = "one"
        elif "all" in raw:
            mode = "all"
        else:
            mode = "off"
        client = self._connect_client()
        if client and client.connected:
            await client.set_repeat_mode(mode)
        await self._coordinator_refresh_now()

    async def async_select_source(self, source: str) -> None:
        """Transfer playback to a Qobuz Connect renderer by display name."""
        client = self._connect_client()
        if not client:
            return
        for dev in client.devices:
            if dev.get("name") == source:
                await client.transfer_playback(dev["id"])
                break
        await self._coordinator_refresh_now()

    # ------------------------------------------------------------------
    # Play media
    # ------------------------------------------------------------------

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        """Play a track: prefer Qobuz Connect; otherwise stream URL if app_secret exists."""
        _LOGGER.info("Qobuz play_media: type=%s id=%s", media_type, media_id)

        if media_type in {MediaType.TRACK, "track"}:
            client = self._connect_client()
            if client and client.connected:
                try:
                    tid = int(str(media_id).rsplit(":", 1)[-1])
                except ValueError:
                    tid = 0
                if tid > 0 and await client.play_track_now(tid):
                    await self._coordinator_refresh_now()
                    return

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
                    "No Connect queue action and no stream URL for track %s "
                    "(Connect disconnected or queue not ready; app_secret missing for URL)",
                    media_id,
                )

        await self._coordinator_refresh_now()

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
