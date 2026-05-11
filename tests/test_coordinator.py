"""Tests for the Qobuz DataUpdateCoordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.qobuz.api import QobuzAPIError, QobuzAuthError
from custom_components.qobuz.coordinator import QobuzDataUpdateCoordinator


async def test_successful_refresh_populates_data(hass, mock_api):
    """A successful refresh populates all coordinator attributes."""
    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)
    await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert coordinator.data is not None
    assert "playlists" in coordinator.data
    assert coordinator.data["authenticated"] is True
    assert len(coordinator.playlists) == 1
    assert coordinator.playlists[0]["name"] == "Test Playlist"
    assert coordinator.user_info["display_name"] == "Test User"


async def test_auth_error_raises_config_entry_auth_failed(hass, mock_api):
    """QobuzAuthError should raise ConfigEntryAuthFailed (not UpdateFailed)."""
    mock_api.get_playlists = AsyncMock(side_effect=QobuzAuthError("token expired"))

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_api_error_raises_update_failed(hass, mock_api):
    """Non-auth API errors surface as UpdateFailed."""
    mock_api.get_playlists = AsyncMock(side_effect=QobuzAPIError("network error"))

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)
    with pytest.raises(UpdateFailed, match="network error"):
        await coordinator._async_update_data()


async def test_playback_none_when_api_returns_none(hass, mock_api):
    """When get_current_playback returns None, current_playback is None."""
    mock_api.get_current_playback = AsyncMock(return_value=None)

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)
    await coordinator.async_refresh()

    assert coordinator.current_playback is None
    assert coordinator.last_update_success is True


async def test_favorites_populated(hass, mock_api):
    """Favorites lists are populated on refresh."""
    mock_api.get_favorite_tracks = AsyncMock(
        return_value=[{"id": "t1", "title": "Favourite Song", "album": {}}]
    )
    mock_api.get_favorite_albums = AsyncMock(
        return_value=[{"id": "a1", "title": "Favourite Album", "artist": {"name": "Artist"}}]
    )

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)
    await coordinator.async_refresh()

    assert len(coordinator.favorite_tracks) == 1
    assert coordinator.favorite_tracks[0]["title"] == "Favourite Song"
    assert len(coordinator.favorite_albums) == 1
