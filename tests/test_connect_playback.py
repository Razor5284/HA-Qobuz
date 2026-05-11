"""Tests for Connect client playback state handling and coordinator fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.qobuz.connect.client import QobuzConnectClient
from custom_components.qobuz.coordinator import QobuzDataUpdateCoordinator

# ---------------------------------------------------------------------------
# Connect client: renderer state handling
# ---------------------------------------------------------------------------


def _make_connect_client(hass) -> QobuzConnectClient:
    """Create a QobuzConnectClient with mocked dependencies."""
    api = MagicMock()
    client = QobuzConnectClient(hass, api, "test_entry")
    client._connected = True
    return client


def _make_renderer_state_msg(playing_state: int, position: int = 0, duration: int = 0, queue_index: int = 0):
    """Build a mock QConnectMessage with srvr_ctrl_renderer_state_updated."""
    import qconnect_payload_pb2

    from custom_components.qobuz.connect.generated import (
        QConnectMessageType,
    )

    qmsg = qconnect_payload_pb2.QConnectMessage()
    qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_RENDERER_STATE_UPDATED
    rsu = qmsg.srvr_ctrl_renderer_state_updated
    rsu.renderer_id = 1
    rsu.message_id = 42
    state = rsu.state
    state.playing_state = playing_state
    state.current_position.value = position
    state.duration = duration
    state.current_queue_index = queue_index
    return qmsg


def _make_queue_state_msg(track_ids: list[int]):
    """Build a mock QConnectMessage with srvr_ctrl_queue_state."""
    import qconnect_payload_pb2

    from custom_components.qobuz.connect.generated import QConnectMessageType

    qmsg = qconnect_payload_pb2.QConnectMessage()
    qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_QUEUE_STATE
    qs = qmsg.srvr_ctrl_queue_state
    for tid in track_ids:
        tr = qs.tracks.add()
        tr.track_id = tid
        tr.queue_item_id = tid * 10
    return qmsg


def _make_session_state_msg(track_index: int):
    """Build a mock QConnectMessage with srvr_ctrl_session_state."""
    import qconnect_payload_pb2

    from custom_components.qobuz.connect.generated import QConnectMessageType

    qmsg = qconnect_payload_pb2.QConnectMessage()
    qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_SESSION_STATE
    ss = qmsg.srvr_ctrl_session_state
    ss.track_index = track_index
    return qmsg


async def test_connect_client_renderer_state_playing(hass):
    """Connect client should report is_playing after receiving PLAYING state."""
    from custom_components.qobuz.connect.generated import PlayingState

    client = _make_connect_client(hass)
    msg = _make_renderer_state_msg(
        PlayingState.PLAYING_STATE_PLAYING, position=5000, duration=240, queue_index=2
    )
    client._handle_qmsg(msg)

    assert client.is_playing is True
    assert client.is_paused is False
    assert client.current_position == 5000
    assert client.duration == 240
    assert client.current_queue_index == 2


async def test_connect_client_renderer_state_paused(hass):
    """Connect client should report is_paused after receiving PAUSED state."""
    from custom_components.qobuz.connect.generated import PlayingState

    client = _make_connect_client(hass)
    msg = _make_renderer_state_msg(PlayingState.PLAYING_STATE_PAUSED, position=10000)
    client._handle_qmsg(msg)

    assert client.is_playing is False
    assert client.is_paused is True
    assert client.current_position == 10000


async def test_connect_client_queue_state(hass):
    """Connect client should track queue track IDs."""
    client = _make_connect_client(hass)
    msg = _make_queue_state_msg([111, 222, 333])
    client._handle_qmsg(msg)

    assert client.queue_track_ids == [111, 222, 333]


async def test_connect_client_current_track_id(hass):
    """current_track_id should combine queue_track_ids and current_queue_index."""
    from custom_components.qobuz.connect.generated import PlayingState

    client = _make_connect_client(hass)

    queue_msg = _make_queue_state_msg([100, 200, 300])
    client._handle_qmsg(queue_msg)

    state_msg = _make_renderer_state_msg(
        PlayingState.PLAYING_STATE_PLAYING, queue_index=1
    )
    client._handle_qmsg(state_msg)

    assert client.current_track_id == 200


async def test_connect_client_current_track_id_out_of_bounds(hass):
    """current_track_id returns None if queue_index is beyond queue length."""
    from custom_components.qobuz.connect.generated import PlayingState

    client = _make_connect_client(hass)
    queue_msg = _make_queue_state_msg([100])
    client._handle_qmsg(queue_msg)

    state_msg = _make_renderer_state_msg(
        PlayingState.PLAYING_STATE_PLAYING, queue_index=5
    )
    client._handle_qmsg(state_msg)

    assert client.current_track_id is None


async def test_connect_client_session_state_updates_index(hass):
    """SESSION_STATE messages should update current_queue_index."""
    client = _make_connect_client(hass)
    queue_msg = _make_queue_state_msg([10, 20, 30])
    client._handle_qmsg(queue_msg)

    session_msg = _make_session_state_msg(track_index=2)
    client._handle_qmsg(session_msg)

    assert client.current_queue_index == 2
    assert client.current_track_id == 30


# ---------------------------------------------------------------------------
# Coordinator: Connect fallback
# ---------------------------------------------------------------------------


async def test_coordinator_uses_connect_fallback_when_rest_returns_none(hass, mock_api):
    """When REST playback is None and Connect reports playing, coordinator should build playback."""
    mock_api.get_current_playback = AsyncMock(return_value=None)
    mock_api.get_track_info = AsyncMock(return_value={
        "id": 12345,
        "title": "Connect Track",
        "duration": 300,
        "artist": {"name": "Test Artist"},
        "album": {"title": "Test Album", "image": {"large": "http://img/large.jpg"}},
    })

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)

    # Set up a mock Connect client
    cc = MagicMock()
    cc.connected = True
    cc.is_playing = True
    cc.is_paused = False
    cc.current_track_id = 12345
    cc.current_position = 5000
    cc.active_device_name = "Living Room Speaker"
    coordinator.connect_client = cc

    await coordinator.async_refresh()

    assert coordinator.current_playback is not None
    assert coordinator.current_playback["is_playing"] is True
    assert coordinator.current_playback["track"]["title"] == "Connect Track"
    assert coordinator.current_playback["track"]["artist"]["name"] == "Test Artist"
    assert coordinator.current_playback["source"] == "connect"
    assert coordinator.current_playback["device_name"] == "Living Room Speaker"
    mock_api.get_track_info.assert_called_once_with("12345")


async def test_coordinator_no_connect_fallback_when_rest_succeeds(hass, mock_api):
    """When REST playback succeeds, Connect fallback is not used."""
    mock_api.get_current_playback = AsyncMock(return_value={"is_playing": True, "track": {"title": "REST Track"}})
    mock_api.get_track_info = AsyncMock()

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)

    cc = MagicMock()
    cc.connected = True
    cc.is_playing = True
    coordinator.connect_client = cc

    await coordinator.async_refresh()

    assert coordinator.current_playback["track"]["title"] == "REST Track"
    mock_api.get_track_info.assert_not_called()


async def test_coordinator_connect_fallback_no_track_id(hass, mock_api):
    """Connect fallback with no track_id still provides basic playing state."""
    mock_api.get_current_playback = AsyncMock(return_value=None)

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)

    cc = MagicMock()
    cc.connected = True
    cc.is_playing = True
    cc.is_paused = False
    cc.current_track_id = None
    cc.active_device_name = "Phone"
    coordinator.connect_client = cc

    await coordinator.async_refresh()

    assert coordinator.current_playback is not None
    assert coordinator.current_playback["is_playing"] is True
    assert coordinator.current_playback["device_name"] == "Phone"
    assert "track" not in coordinator.current_playback


async def test_coordinator_connect_fallback_stopped_returns_none(hass, mock_api):
    """Connect fallback returns None if Connect is neither playing nor paused."""
    mock_api.get_current_playback = AsyncMock(return_value=None)

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)

    cc = MagicMock()
    cc.connected = True
    cc.is_playing = False
    cc.is_paused = False
    coordinator.connect_client = cc

    await coordinator.async_refresh()

    assert coordinator.current_playback is None


async def test_coordinator_connect_fallback_disconnected_returns_none(hass, mock_api):
    """Connect fallback returns None if Connect is not connected."""
    mock_api.get_current_playback = AsyncMock(return_value=None)

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)

    cc = MagicMock()
    cc.connected = False
    cc.is_playing = True
    coordinator.connect_client = cc

    await coordinator.async_refresh()

    assert coordinator.current_playback is None
