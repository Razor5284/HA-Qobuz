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


def _make_renderer_state_msg(
    playing_state: int,
    position: int = 0,
    duration: int = 0,
    queue_index: int = 0,
    *,
    renderer_id: int = 1,
):
    """Build a mock QConnectMessage with srvr_ctrl_renderer_state_updated."""
    import qconnect_payload_pb2

    from custom_components.qobuz.connect.generated import (
        QConnectMessageType,
    )

    qmsg = qconnect_payload_pb2.QConnectMessage()
    qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_RENDERER_STATE_UPDATED
    rsu = qmsg.srvr_ctrl_renderer_state_updated
    rsu.renderer_id = renderer_id
    rsu.message_id = 42
    state = rsu.state
    state.playing_state = playing_state
    state.current_position.value = position
    state.duration = duration
    state.current_queue_index = queue_index
    return qmsg


def _make_queue_state_msg(track_ids: list[int], queue_major: int = 1, queue_minor: int = 0):
    """Build a mock QConnectMessage with srvr_ctrl_queue_state."""
    import qconnect_payload_pb2

    from custom_components.qobuz.connect.generated import QConnectMessageType

    qmsg = qconnect_payload_pb2.QConnectMessage()
    qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_QUEUE_STATE
    qs = qmsg.srvr_ctrl_queue_state
    qs.queue_version.major = queue_major
    qs.queue_version.minor = queue_minor
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


async def test_connect_client_ignores_state_from_inactive_renderer(hass):
    """RendererStateUpdated for a non-active renderer must not clobber playback."""
    from custom_components.qobuz.connect.generated import PlayingState

    client = _make_connect_client(hass)
    client._active_renderer_id = 2

    wrong = _make_renderer_state_msg(
        PlayingState.PLAYING_STATE_PLAYING,
        queue_index=9,
        renderer_id=1,
    )
    client._handle_qmsg(wrong)

    assert client.is_playing is False
    assert client.current_queue_index == 0

    ok = _make_renderer_state_msg(
        PlayingState.PLAYING_STATE_PLAYING,
        queue_index=1,
        renderer_id=2,
    )
    client._handle_qmsg(ok)

    assert client.is_playing is True
    assert client.current_queue_index == 1


async def test_coordinator_prefers_connect_when_rest_is_empty_dict(hass, mock_api):
    """A truthy but idle REST body must not block Connect playback."""
    mock_api.get_current_playback = AsyncMock(return_value={})
    mock_api.get_track_info = AsyncMock(return_value={
        "id": 55,
        "title": "From Connect",
        "duration": 200,
        "artist": {"name": "A"},
        "album": {"title": "Al", "image": {}},
    })

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)
    cc = MagicMock()
    cc.connected = True
    cc.is_playing = True
    cc.is_paused = False
    cc.playing_state = 2
    cc.current_track_id = 55
    cc.current_position = 1000
    cc.active_device_name = "Web"
    coordinator.connect_client = cc

    await coordinator.async_refresh()

    assert coordinator.current_playback is not None
    assert coordinator.current_playback["track"]["title"] == "From Connect"
    assert coordinator.current_playback["source"] == "connect"


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
    """Connect fallback returns None if server reports STOPPED."""
    mock_api.get_current_playback = AsyncMock(return_value=None)

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)

    cc = MagicMock()
    cc.connected = True
    cc.is_playing = False
    cc.is_paused = False
    cc.playing_state = 1  # PLAYING_STATE_STOPPED
    coordinator.connect_client = cc

    await coordinator.async_refresh()

    assert coordinator.current_playback is None


async def test_coordinator_connect_fallback_unknown_state_with_track(hass, mock_api):
    """UNKNOWN playing_state with a queue track still yields Connect playback + metadata."""
    mock_api.get_current_playback = AsyncMock(return_value=None)
    mock_api.get_track_info = AsyncMock(return_value={
        "id": 999,
        "title": "Ambiguous Track",
        "duration": 180,
        "artist": {"name": "Artist"},
        "album": {"title": "Album", "image": {}},
    })

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)

    cc = MagicMock()
    cc.connected = True
    cc.is_playing = False
    cc.is_paused = False
    cc.playing_state = 0  # PLAYING_STATE_UNKNOWN
    cc.current_track_id = 999
    cc.current_position = 3000
    cc.duration = 180
    cc.active_device_name = "Kitchen"
    coordinator.connect_client = cc

    await coordinator.async_refresh()

    assert coordinator.current_playback is not None
    assert coordinator.current_playback["track"]["title"] == "Ambiguous Track"
    assert coordinator.current_playback["is_playing"] is True
    assert coordinator.current_playback["is_paused"] is False
    assert coordinator.current_playback["source"] == "connect"


async def test_coordinator_connect_fallback_unknown_no_timing_not_forced_playing(
    hass, mock_api,
):
    """UNKNOWN state without position/duration does not set is_playing True."""
    mock_api.get_current_playback = AsyncMock(return_value=None)
    mock_api.get_track_info = AsyncMock(return_value={
        "id": 1,
        "title": "T",
        "duration": 0,
        "artist": {"name": "A"},
        "album": {"title": "Al", "image": {}},
    })

    coordinator = QobuzDataUpdateCoordinator(hass, mock_api)
    cc = MagicMock()
    cc.connected = True
    cc.is_playing = False
    cc.is_paused = False
    cc.playing_state = 0
    cc.current_track_id = 1
    cc.current_position = 0
    cc.duration = 0
    cc.active_device_name = None
    coordinator.connect_client = cc

    await coordinator.async_refresh()

    assert coordinator.current_playback is not None
    assert coordinator.current_playback["is_playing"] is False


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


# ---------------------------------------------------------------------------
# Connect client: next/previous track
# ---------------------------------------------------------------------------


async def test_connect_client_next_track(hass):
    """media_next_track should advance queue index and send command."""
    from custom_components.qobuz.connect.generated import PlayingState

    client = _make_connect_client(hass)
    client._ws = MagicMock()
    client._ws.send = AsyncMock()

    queue_msg = _make_queue_state_msg([100, 200, 300], queue_major=5, queue_minor=3)
    client._handle_qmsg(queue_msg)

    state_msg = _make_renderer_state_msg(PlayingState.PLAYING_STATE_PLAYING, queue_index=0)
    client._handle_qmsg(state_msg)

    result = await client.media_next_track()
    assert result is True
    assert client.current_queue_index == 0
    upd = _make_renderer_state_msg(
        PlayingState.PLAYING_STATE_PLAYING, queue_index=1, renderer_id=1
    )
    client._handle_qmsg(upd)
    assert client.current_queue_index == 1
    client._ws.send.assert_called_once()


async def test_connect_client_next_track_at_end(hass):
    """media_next_track returns False at end of queue."""
    from custom_components.qobuz.connect.generated import PlayingState

    client = _make_connect_client(hass)
    client._ws = MagicMock()
    client._ws.send = AsyncMock()

    queue_msg = _make_queue_state_msg([100, 200], queue_major=1, queue_minor=0)
    client._handle_qmsg(queue_msg)

    state_msg = _make_renderer_state_msg(PlayingState.PLAYING_STATE_PLAYING, queue_index=1)
    client._handle_qmsg(state_msg)

    result = await client.media_next_track()
    assert result is False
    assert client.current_queue_index == 1
    client._ws.send.assert_not_called()


async def test_connect_client_previous_track(hass):
    """media_previous_track should go back in queue."""
    from custom_components.qobuz.connect.generated import PlayingState

    client = _make_connect_client(hass)
    client._ws = MagicMock()
    client._ws.send = AsyncMock()

    queue_msg = _make_queue_state_msg([100, 200, 300], queue_major=2, queue_minor=1)
    client._handle_qmsg(queue_msg)

    state_msg = _make_renderer_state_msg(PlayingState.PLAYING_STATE_PLAYING, queue_index=2)
    client._handle_qmsg(state_msg)

    result = await client.media_previous_track()
    assert result is True
    assert client.current_queue_index == 2
    upd = _make_renderer_state_msg(
        PlayingState.PLAYING_STATE_PLAYING, queue_index=1, renderer_id=1
    )
    client._handle_qmsg(upd)
    assert client.current_queue_index == 1
    client._ws.send.assert_called_once()


async def test_connect_client_previous_track_at_start(hass):
    """media_previous_track returns False at start of queue."""
    from custom_components.qobuz.connect.generated import PlayingState

    client = _make_connect_client(hass)
    client._ws = MagicMock()
    client._ws.send = AsyncMock()

    queue_msg = _make_queue_state_msg([100, 200], queue_major=1, queue_minor=0)
    client._handle_qmsg(queue_msg)

    state_msg = _make_renderer_state_msg(PlayingState.PLAYING_STATE_PLAYING, queue_index=0)
    client._handle_qmsg(state_msg)

    result = await client.media_previous_track()
    assert result is False
    assert client.current_queue_index == 0
    client._ws.send.assert_not_called()


# ---------------------------------------------------------------------------
# Connect client: device discovery
# ---------------------------------------------------------------------------


async def test_connect_client_device_added(hass):
    """ADD_RENDERER message should populate the devices list."""
    import qconnect_payload_pb2

    from custom_components.qobuz.connect.generated import QConnectMessageType

    client = _make_connect_client(hass)

    qmsg = qconnect_payload_pb2.QConnectMessage()
    qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_ADD_RENDERER
    add = qmsg.srvr_ctrl_add_renderer
    add.renderer_id = 42
    add.renderer.friendly_name = "Living Room Speaker"
    add.renderer.model = "Sonos"

    client._handle_qmsg(qmsg)

    assert len(client.devices) == 1
    assert client.devices[0]["name"] == "Living Room Speaker"
    assert client.devices[0]["id"] == "42"


async def test_connect_client_active_renderer(hass):
    """ACTIVE_RENDERER_CHANGED should update active_device_name."""
    import qconnect_payload_pb2

    from custom_components.qobuz.connect.generated import QConnectMessageType

    client = _make_connect_client(hass)

    # Add a renderer first
    add_msg = qconnect_payload_pb2.QConnectMessage()
    add_msg.message_type = QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_ADD_RENDERER
    add_msg.srvr_ctrl_add_renderer.renderer_id = 7
    add_msg.srvr_ctrl_add_renderer.renderer.friendly_name = "Kitchen Speaker"
    client._handle_qmsg(add_msg)

    # Set it as active
    active_msg = qconnect_payload_pb2.QConnectMessage()
    active_msg.message_type = QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_ACTIVE_RENDERER_CHANGED
    active_msg.srvr_ctrl_active_renderer_changed.renderer_id = 7
    client._handle_qmsg(active_msg)

    assert client.active_device_name == "Kitchen Speaker"


async def test_connect_client_device_removed(hass):
    """REMOVE_RENDERER message should remove from devices list."""
    import qconnect_payload_pb2

    from custom_components.qobuz.connect.generated import QConnectMessageType

    client = _make_connect_client(hass)

    # Add two renderers
    for rid, name in [(1, "Speaker A"), (2, "Speaker B")]:
        add_msg = qconnect_payload_pb2.QConnectMessage()
        add_msg.message_type = QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_ADD_RENDERER
        add_msg.srvr_ctrl_add_renderer.renderer_id = rid
        add_msg.srvr_ctrl_add_renderer.renderer.friendly_name = name
        client._handle_qmsg(add_msg)

    assert len(client.devices) == 2

    # Remove one
    rem_msg = qconnect_payload_pb2.QConnectMessage()
    rem_msg.message_type = QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_REMOVE_RENDERER
    rem_msg.srvr_ctrl_remove_renderer.renderer_id = 1
    client._handle_qmsg(rem_msg)

    assert len(client.devices) == 1
    assert client.devices[0]["name"] == "Speaker B"
