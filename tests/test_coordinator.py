"""Tests for Qobuz data coordinator."""

from custom_components.qobuz.coordinator import QobuzDataUpdateCoordinator


async def test_coordinator_update(hass, mock_api):
    """Test successful data fetch."""
    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)
    await coordinator.async_refresh()
    assert coordinator.data is not None
    assert "playlists" in coordinator.data
    assert coordinator.last_update_success is True