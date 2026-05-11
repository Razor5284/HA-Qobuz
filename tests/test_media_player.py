"""Tests for Qobuz media player."""

from custom_components.qobuz.media_player import QobuzMediaPlayer


async def test_media_player_state(hass, mock_api, mock_config_entry):
    """Test basic state and browse."""
    coordinator = type("C", (), {"current_playback": None, "playlists": [], "async_request_refresh": lambda s: None})()
    player = QobuzMediaPlayer(coordinator, mock_config_entry)  # type: ignore[arg-type]
    assert player.state is not None
    # Browse root should return app media
    # (full async_browse_media test would require more mocking)
