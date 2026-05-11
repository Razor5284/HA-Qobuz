"""Tests for the Qobuz MediaPlayerEntity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.media_player import MediaPlayerState, MediaType

from custom_components.qobuz.media_player import QobuzMediaPlayer

# ---------------------------------------------------------------------------
# Helper: build a player without HA's entity lifecycle
# ---------------------------------------------------------------------------

def _make_player(playback=None, playlists=None, hass=None):
    """Build a QobuzMediaPlayer with a minimal mock coordinator.

    Bypasses CoordinatorEntity.__init__ so we can test properties in isolation
    without needing a real HA entity registry.
    """
    coordinator = MagicMock()
    coordinator.current_playback = playback
    coordinator.playlists = playlists or []

    entry = MagicMock()
    entry.entry_id = "test_entry"

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

async def test_state_idle_with_no_playback(hass):
    """State is IDLE when there is no playback data."""
    player = _make_player(playback=None)
    assert player.state == MediaPlayerState.IDLE


async def test_state_idle_when_not_playing_or_paused(hass):
    """State is IDLE when neither is_playing nor is_paused is set."""
    player = _make_player(playback={"is_playing": False, "is_paused": False})
    assert player.state == MediaPlayerState.IDLE


async def test_state_playing(hass):
    """State is PLAYING when is_playing is True."""
    player = _make_player(playback={"is_playing": True})
    assert player.state == MediaPlayerState.PLAYING


async def test_state_paused(hass):
    """State is PAUSED when is_paused is True and is_playing is False."""
    player = _make_player(playback={"is_playing": False, "is_paused": True})
    assert player.state == MediaPlayerState.PAUSED


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

async def test_metadata_from_playback(hass):
    """Title, artist, album and image URL are read from playback data."""
    playback = {
        "track": {
            "title": "Test Song",
            "artist": {"name": "Test Artist"},
            "album": {
                "title": "Test Album",
                "image": {"large": "https://example.com/large.jpg", "medium": "https://example.com/medium.jpg"},
            },
        }
    }
    player = _make_player(playback=playback)
    assert player.media_title == "Test Song"
    assert player.media_artist == "Test Artist"
    assert player.media_album_name == "Test Album"
    assert player.media_image_url == "https://example.com/large.jpg"


async def test_metadata_none_when_no_playback(hass):
    """Metadata properties return None gracefully when playback is absent."""
    player = _make_player(playback=None)
    assert player.media_title is None
    assert player.media_artist is None
    assert player.media_album_name is None
    assert player.media_image_url is None


async def test_image_falls_back_to_medium(hass):
    """image_url falls back to medium if large is not present."""
    playback = {
        "track": {
            "title": "T",
            "artist": {"name": "A"},
            "album": {"title": "AL", "image": {"medium": "https://example.com/medium.jpg"}},
        }
    }
    player = _make_player(playback=playback)
    assert player.media_image_url == "https://example.com/medium.jpg"


# ---------------------------------------------------------------------------
# Source list
# ---------------------------------------------------------------------------

async def test_source_list_fallback_when_no_connect_client(hass):
    """source_list returns a fallback when hass.data has no connect_client."""
    player = _make_player(hass=hass)
    # hass.data won't have DOMAIN set, so .get(DOMAIN, {}) returns {}
    assert player.source_list == ["This device"]


# ---------------------------------------------------------------------------
# Browse media
# ---------------------------------------------------------------------------

async def test_browse_media_root_returns_playlists(hass):
    """async_browse_media() with no args returns playlists as children."""
    playlists = [
        {"id": "1", "name": "My List", "image": {"small": "https://x.com/img.jpg"}},
        {"id": "2", "name": "Second List", "image": {}},
    ]
    player = _make_player(playlists=playlists, hass=hass)
    player.coordinator.api = MagicMock()

    result = await player.async_browse_media()

    assert result.title == "Qobuz Library"
    assert result.can_expand is True
    assert result.can_play is False
    assert len(result.children) == 2
    assert result.children[0].title == "My List"
    assert result.children[0].media_content_id == "1"
    assert result.children[0].can_play is True


async def test_browse_media_playlist_returns_tracks(hass):
    """async_browse_media() for a playlist id returns its tracks."""
    tracks = [
        {"id": "t1", "title": "Track One", "album": {"image": {"small": "https://x.com/t.jpg"}}},
    ]
    player = _make_player(hass=hass)
    player.coordinator.api = MagicMock()
    player.coordinator.api.get_playlist_tracks = AsyncMock(return_value=tracks)

    result = await player.async_browse_media(
        media_content_type=MediaType.PLAYLIST,
        media_content_id="playlist_123",
    )

    assert len(result.children) == 1
    assert result.children[0].title == "Track One"
    assert result.children[0].media_content_id == "t1"
    assert result.children[0].can_play is True
    assert result.children[0].can_expand is False
