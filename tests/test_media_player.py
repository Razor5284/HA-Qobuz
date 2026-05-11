"""Tests for the Qobuz MediaPlayerEntity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.media_player import (
    MediaClass,
    MediaPlayerState,
    MediaType,
)

from custom_components.qobuz.media_player import (
    QobuzMediaPlayer,
    _album_title,
    _track_thumb,
)

# ---------------------------------------------------------------------------
# Helper: build a player without HA entity registry
# ---------------------------------------------------------------------------

def _make_player(
    playback=None,
    playlists=None,
    user_info=None,
    favorite_tracks=None,
    favorite_albums=None,
    favorite_artists=None,
    hass=None,
):
    coordinator = MagicMock()
    coordinator.current_playback = playback
    coordinator.playlists = playlists or []
    coordinator.user_info = user_info or {}
    coordinator.favorite_tracks = favorite_tracks or []
    coordinator.favorite_albums = favorite_albums or []
    coordinator.favorite_artists = favorite_artists or []
    api = MagicMock()
    api.has_stream_support = False
    api.get_track_url = AsyncMock(return_value=None)
    api.get_playlist_tracks = AsyncMock(return_value=[])
    api.get_album = AsyncMock(return_value={"id": "a1", "title": "Album", "tracks": {"items": []}})
    coordinator.api = api

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {"email": "test@example.com"}

    player = QobuzMediaPlayer.__new__(QobuzMediaPlayer)
    player.coordinator = coordinator
    player._entry = entry
    player._attr_unique_id = "test_entry_player"
    if hass is not None:
        player.hass = hass
    return player


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

async def test_state_idle(hass):
    assert _make_player().state == MediaPlayerState.IDLE


async def test_state_playing(hass):
    assert _make_player(playback={"is_playing": True}).state == MediaPlayerState.PLAYING


async def test_state_paused(hass):
    p = _make_player(playback={"is_playing": False, "is_paused": True})
    assert p.state == MediaPlayerState.PAUSED


async def test_state_playing_via_connect_fallback(hass):
    """When REST returns no playback but Connect reports playing, state is PLAYING."""
    player = _make_player(playback=None, hass=hass)
    # Simulate connect client being available via hass.data
    cc = MagicMock()
    cc.connected = True
    cc.is_playing = True
    cc.is_paused = False
    hass.data = {"qobuz": {"test_entry": {"connect_client": cc}}}
    assert player.state == MediaPlayerState.PLAYING


async def test_state_paused_via_connect_fallback(hass):
    """When REST returns no playback but Connect reports paused, state is PAUSED."""
    player = _make_player(playback=None, hass=hass)
    cc = MagicMock()
    cc.connected = True
    cc.is_playing = False
    cc.is_paused = True
    hass.data = {"qobuz": {"test_entry": {"connect_client": cc}}}
    assert player.state == MediaPlayerState.PAUSED


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

async def test_media_metadata(hass):
    playback = {
        "track": {
            "title": "Test Song",
            "artist": {"name": "Test Artist"},
            "album": {
                "title": "Test Album",
                "image": {"large": "https://img.example.com/large.jpg"},
            },
            "duration": 240,
        }
    }
    player = _make_player(playback=playback)
    assert player.media_title == "Test Song"
    assert player.media_artist == "Test Artist"
    assert player.media_album_name == "Test Album"
    assert player.media_image_url == "https://img.example.com/large.jpg"
    assert player.media_duration == 240


async def test_metadata_none_with_no_playback(hass):
    player = _make_player()
    assert player.media_title is None
    assert player.media_image_url is None


# ---------------------------------------------------------------------------
# Browse media
# ---------------------------------------------------------------------------

async def test_browse_root_shows_sections(hass):
    """Root browse should show playlists + 3 favorites sections."""
    player = _make_player(hass=hass)
    result = await player.async_browse_media()

    assert result.media_class == MediaClass.APP
    assert result.can_expand is True
    titles = [c.title for c in result.children]
    assert "My Playlists" in titles
    assert "Favourite Tracks" in titles
    assert "Favourite Albums" in titles
    assert "Favourite Artists" in titles


async def test_browse_playlists(hass):
    """Playlists section lists user playlists."""
    playlists = [{"id": "1", "name": "Chill Mix", "image": {}}]
    player = _make_player(playlists=playlists, hass=hass)

    from custom_components.qobuz.const import BROWSE_PLAYLISTS
    result = await player.async_browse_media(
        media_content_type=MediaType.PLAYLIST,
        media_content_id=BROWSE_PLAYLISTS,
    )
    assert len(result.children) == 1
    assert result.children[0].title == "Chill Mix"
    assert result.children[0].media_class == MediaClass.PLAYLIST


async def test_browse_favorite_tracks(hass):
    """Favourite tracks section lists tracks with correct MediaClass."""
    tracks = [{"id": "t1", "title": "My Song", "album": {"image": {}}}]
    player = _make_player(favorite_tracks=tracks, hass=hass)

    from custom_components.qobuz.const import BROWSE_FAVORITES_TRACKS
    result = await player.async_browse_media(
        media_content_type=MediaType.TRACK,
        media_content_id=BROWSE_FAVORITES_TRACKS,
    )
    assert len(result.children) == 1
    assert result.children[0].media_class == MediaClass.TRACK
    assert result.children[0].can_play is True


async def test_browse_favorite_albums(hass):
    """Favourite albums section lists albums."""
    albums = [{"id": "a1", "title": "My Album", "artist": {"name": "Artist"}, "image": {}}]
    player = _make_player(favorite_albums=albums, hass=hass)

    from custom_components.qobuz.const import BROWSE_FAVORITES_ALBUMS
    result = await player.async_browse_media(
        media_content_type=MediaType.ALBUM,
        media_content_id=BROWSE_FAVORITES_ALBUMS,
    )
    assert len(result.children) == 1
    assert result.children[0].media_class == MediaClass.ALBUM


async def test_browse_playlist_tracks(hass):
    """Expanding a playlist returns its tracks."""
    tracks = [{"id": "t1", "title": "Track 1", "album": {"image": {}}}]
    player = _make_player(hass=hass)
    player.coordinator.api.get_playlist_tracks = AsyncMock(return_value=tracks)

    result = await player.async_browse_media(
        media_content_type=MediaType.PLAYLIST,
        media_content_id="playlist_123",
    )
    assert len(result.children) == 1
    assert result.children[0].title == "Track 1"
    assert result.children[0].can_play is True


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

async def test_album_title_with_artist(hass):
    assert _album_title({"title": "Rumours", "artist": {"name": "Fleetwood Mac"}}) == "Fleetwood Mac — Rumours"


async def test_album_title_no_artist(hass):
    assert _album_title({"title": "Untitled"}) == "Untitled"


async def test_track_thumb(hass):
    t = {"album": {"image": {"small": "https://img.example.com/small.jpg"}}}
    assert _track_thumb(t) == "https://img.example.com/small.jpg"


# ---------------------------------------------------------------------------
# Device info
# ---------------------------------------------------------------------------

async def test_device_info_present(hass):
    user_info = {"display_name": "Ryan", "credential": {"description": "Sublime"}}
    player = _make_player(user_info=user_info, hass=hass)
    info = player.device_info
    assert info is not None
    assert "Qobuz" in info["name"]
    assert info["manufacturer"] == "Qobuz"


# ---------------------------------------------------------------------------
# Extra attributes
# ---------------------------------------------------------------------------

async def test_extra_attributes_with_user(hass):
    user_info = {"display_name": "Ryan", "credential": {"description": "Sublime"}}
    player = _make_player(user_info=user_info)
    attrs = player.extra_state_attributes
    assert attrs["account_name"] == "Ryan"
    assert attrs["subscription"] == "Sublime"
