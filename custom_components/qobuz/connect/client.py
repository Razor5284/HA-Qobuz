"""Qobuz Connect WebSocket client — controller session (devices + transport)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
import uuid
from typing import TYPE_CHECKING, Any

import websockets
from homeassistant.helpers.dispatcher import async_dispatcher_send

from ..api import QobuzAPIClient, QobuzAPIError
from ..const import DOMAIN
from . import protocol

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

INTEGRATION_VERSION = "0.11.6"

# QConnect uses max uint64 as "no active renderer" in some server messages.
RENDERER_ID_NO_ACTIVE = (1 << 64) - 1


def _default_ssl_context() -> ssl.SSLContext:
    """Build TLS context (blocking cert store load — run in HA executor)."""
    return ssl.create_default_context()


class QobuzConnectClient:
    """Maintain a QConnect controller WebSocket: device list + playback commands."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: QobuzAPIClient,
        entry_id: str,
    ) -> None:
        self.hass = hass
        self._api = api
        self._entry_id = entry_id
        self._ws: Any = None
        self._msg_id = 0
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._connected = False
        self.devices: list[dict[str, Any]] = []
        self._renderers: dict[int, dict[str, Any]] = {}
        self._active_renderer_id: int | None = None
        self._send_lock = asyncio.Lock()
        self._consecutive_failures = 0
        # QConnect session identity (filled from SrvrCtrlSessionState; see qonductor)
        self._join_device_uuid: bytes | None = None
        self._session_uuid: bytes | None = None
        self._session_id: int | None = None
        self._pending_discovery_asks = False

        # Playback state from Connect WebSocket
        self.playing_state: int = 0  # PlayingState enum value
        self.current_position: int = 0  # ms
        self.duration: int = 0  # seconds
        self.current_queue_index: int = 0
        self.queue_track_ids: list[int] = []
        # Full queue state for track skipping
        self._queue_tracks: list[dict[str, Any]] = []  # [{queue_item_id, track_id}]
        self._queue_version: dict[str, int] | None = None  # {major, minor}
        self._queue_action_uuid: bytes | None = None
        self._queue_hash: bytes | None = None
        self._shuffle_mode: bool | None = None
        self._loop_mode: int | None = None
        self._renderer_volumes: dict[int, float] = {}
        self._max_audio_quality: int | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def active_device_name(self) -> str | None:
        if self._active_renderer_id is None:
            return None
        r = self._renderers.get(self._active_renderer_id)
        return r.get("name") if r else None

    @property
    def is_playing(self) -> bool:
        from .generated import PlayingState  # noqa: PLC0415

        return self.playing_state == PlayingState.PLAYING_STATE_PLAYING

    @property
    def is_paused(self) -> bool:
        from .generated import PlayingState  # noqa: PLC0415

        return self.playing_state == PlayingState.PLAYING_STATE_PAUSED

    @property
    def shuffle_mode(self) -> bool | None:
        """Last known shuffle flag from queue snapshot or server ack (if any)."""
        return self._shuffle_mode

    @property
    def loop_mode(self) -> int | None:
        """Raw qconnect ``LoopMode`` enum value from server ack (if any)."""
        return self._loop_mode

    @property
    def volume_level(self) -> float | None:
        """Last known volume for the active renderer (0..1), from Connect."""
        if self._active_renderer_id is None:
            return None
        return self._renderer_volumes.get(self._active_renderer_id)

    @property
    def connect_max_audio_quality(self) -> int | None:
        """Last reported max streaming quality id from Connect (if any)."""
        return self._max_audio_quality

    @property
    def current_track_id(self) -> int | None:
        """Return the Qobuz track_id currently playing from the queue."""
        if self.queue_track_ids and 0 <= self.current_queue_index < len(self.queue_track_ids):
            return self.queue_track_ids[self.current_queue_index]
        return None

    def start(self) -> None:
        """Begin background connect/reconnect loop."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = self.hass.async_create_background_task(
            self._run_loop(), f"qobuz-connect-{self._entry_id}"
        )

    async def shutdown(self) -> None:
        """Stop background task and close the socket."""
        self._stop.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._close_ws()

    async def _close_ws(self) -> None:
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        self._connected = False

    def _next_msg_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _notify_entity_update(self) -> None:
        async_dispatcher_send(
            self.hass,
            f"{DOMAIN}_connect_{self._entry_id}",
        )

    def _sync_device_list(self) -> None:
        self.devices = [
            {
                "id": str(rid),
                "name": info.get("name", f"Device {rid}"),
                "renderer_id": rid,
            }
            for rid, info in sorted(self._renderers.items())
        ]
        self._notify_entity_update()

    def _reset_connect_session_cache(self) -> None:
        """Clear renderer/queue snapshot when a new WebSocket session starts."""
        self._renderers.clear()
        self.devices = []
        self._active_renderer_id = None
        self.queue_track_ids.clear()
        self._queue_tracks.clear()
        self._queue_version = None
        self._queue_action_uuid = None
        self._queue_hash = None
        self._shuffle_mode = None
        self._loop_mode = None
        self._renderer_volumes.clear()
        self._max_audio_quality = None
        self.playing_state = 0
        self.current_position = 0
        self.duration = 0
        self.current_queue_index = 0

    def _merge_update_renderer(self, di: Any) -> None:
        """Apply SrvrCtrlUpdateRenderer (same device UUID, refreshed DeviceInfo)."""
        if di.device_uuid and len(di.device_uuid) == 16:
            uid = bytes(di.device_uuid)
            for rid, info in list(self._renderers.items()):
                ex = info.get("device_info")
                if ex and ex.device_uuid == uid:
                    name = di.friendly_name or di.model or info.get("name", f"Renderer {rid}")
                    self._renderers[rid] = {"name": name, "device_info": di}
                    self._sync_device_list()
                    _LOGGER.debug("Connect: updated renderer %s (%s)", rid, name)
                    return
        # Fallback: some AVRs send updates with no UUID but a stable display name.
        label = (di.friendly_name or di.model or di.brand or "").strip()
        if label:
            for rid, info in list(self._renderers.items()):
                if (info.get("name") or "").strip() == label:
                    self._renderers[rid] = {"name": label, "device_info": di}
                    self._sync_device_list()
                    _LOGGER.debug("Connect: updated renderer %s by name match", rid)
                    return
        _LOGGER.info(
            "Connect: update_renderer unmatched (uuid=%s name=%r model=%r)",
            bool(di.device_uuid and len(di.device_uuid) == 16),
            di.friendly_name,
            di.model,
        )

    def _handle_qmsg(self, qmsg: Any) -> None:
        from .generated import QConnectMessageType  # noqa: PLC0415

        mt = qmsg.message_type or 0
        if mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_ADD_RENDERER:
            add = qmsg.srvr_ctrl_add_renderer
            if add and add.HasField("renderer_id"):
                rid = int(add.renderer_id)
                if add.HasField("renderer"):
                    di = add.renderer
                    name = (
                        di.friendly_name
                        or di.model
                        or di.brand
                        or f"Renderer {rid}"
                    )
                else:
                    di = None
                    name = f"Renderer {rid}"
                self._renderers[rid] = {"name": name, "device_info": di}
                self._sync_device_list()
                _LOGGER.debug("Connect: added renderer %s (%s)", rid, name)
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_UPDATE_RENDERER:
            up = qmsg.srvr_ctrl_update_renderer
            if up and up.renderer:
                self._merge_update_renderer(up.renderer)
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_REMOVE_RENDERER:
            rem = qmsg.srvr_ctrl_remove_renderer
            if rem and rem.HasField("renderer_id"):
                rid = int(rem.renderer_id)
                self._renderers.pop(rid, None)
                self._renderer_volumes.pop(rid, None)
                if self._active_renderer_id == rid:
                    self._active_renderer_id = None
                self._sync_device_list()
                _LOGGER.debug("Connect: removed renderer %s", rid)
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_ACTIVE_RENDERER_CHANGED:
            ch = qmsg.srvr_ctrl_active_renderer_changed
            if ch and ch.HasField("renderer_id"):
                rid = int(ch.renderer_id)
                if rid == RENDERER_ID_NO_ACTIVE:
                    self._active_renderer_id = None
                    _LOGGER.debug("Connect: active renderer cleared (none)")
                else:
                    self._active_renderer_id = rid
                    _LOGGER.debug("Connect: active renderer -> %s", self._active_renderer_id)
                self._notify_entity_update()
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_RENDERER_STATE_UPDATED:
            rsu = qmsg.srvr_ctrl_renderer_state_updated
            if rsu and rsu.state:
                rid: int | None = None
                if rsu.HasField("renderer_id"):
                    rid = int(rsu.renderer_id)
                    if rid != RENDERER_ID_NO_ACTIVE and rid not in self._renderers:
                        self._renderers[rid] = {
                            "name": f"Renderer {rid}",
                            "device_info": None,
                        }
                        self._sync_device_list()
                    if rid == RENDERER_ID_NO_ACTIVE:
                        self._apply_renderer_state(rsu.state)
                        _LOGGER.debug(
                            "Connect: renderer state (no active renderer) — ps=%s idx=%s",
                            self.playing_state,
                            self.current_queue_index,
                        )
                    elif (
                        self._active_renderer_id is not None
                        and rid != self._active_renderer_id
                    ):
                        _LOGGER.debug(
                            "Connect: ignoring renderer state from inactive renderer %s",
                            rid,
                        )
                    else:
                        self._apply_renderer_state(rsu.state)
                        _LOGGER.debug(
                            "Connect: renderer state updated — playing_state=%s pos=%s dur=%s idx=%s",
                            self.playing_state,
                            self.current_position,
                            self.duration,
                            self.current_queue_index,
                        )
                else:
                    self._apply_renderer_state(rsu.state)
                    _LOGGER.debug(
                        "Connect: renderer state updated (no renderer_id) — playing_state=%s",
                        self.playing_state,
                    )
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_SESSION_STATE:
            ss = qmsg.srvr_ctrl_session_state
            if ss:
                if ss.HasField("session_id"):
                    self._session_id = int(ss.session_id)
                if ss.session_uuid and len(ss.session_uuid) == 16:
                    self._session_uuid = bytes(ss.session_uuid)
                if ss.HasField("track_index"):
                    self.current_queue_index = int(ss.track_index)
                self._pending_discovery_asks = True
                self._notify_entity_update()
                _LOGGER.debug(
                    "Connect: session state — session_id=%s track_index=%s",
                    self._session_id,
                    ss.track_index if ss.HasField("track_index") else None,
                )
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_QUEUE_STATE:
            qs = qmsg.srvr_ctrl_queue_state
            if qs:
                self._apply_queue_state(qs)
                _LOGGER.debug(
                    "Connect: queue state — %d tracks", len(self.queue_track_ids)
                )
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_QUEUE_TRACKS_LOADED:
            qtl = qmsg.srvr_ctrl_queue_tracks_loaded
            if qtl:
                self._apply_queue_tracks_loaded(qtl)
                _LOGGER.debug(
                    "Connect: queue tracks loaded — %d tracks", len(self.queue_track_ids)
                )
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_QUEUE_TRACKS_ADDED:
            added = qmsg.srvr_ctrl_queue_tracks_added
            if added:
                self._apply_queue_tracks_added(added)
                _LOGGER.debug(
                    "Connect: queue tracks added — %d tracks (total %d)",
                    len(added.tracks),
                    len(self._queue_tracks),
                )
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_QUEUE_CLEARED:
            cleared = qmsg.srvr_ctrl_queue_cleared
            if cleared and cleared.queue_version:
                self._queue_version = {
                    "major": int(cleared.queue_version.major),
                    "minor": int(cleared.queue_version.minor),
                }
            self._queue_tracks.clear()
            self.queue_track_ids.clear()
            self._apply_queue_meta_from(cleared)
            self._notify_entity_update()
            _LOGGER.debug("Connect: queue cleared")
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_QUEUE_VERSION_CHANGED:
            vc = qmsg.srvr_ctrl_queue_version_changed
            if vc and vc.queue_version:
                self._queue_version = {
                    "major": int(vc.queue_version.major),
                    "minor": int(vc.queue_version.minor),
                }
                self._notify_entity_update()
                _LOGGER.debug("Connect: queue version changed")
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_SHUFFLE_MODE_SET:
            sm = qmsg.srvr_ctrl_shuffle_mode_set
            if sm:
                if sm.HasField("shuffle_on"):
                    self._shuffle_mode = bool(sm.shuffle_on)
                self._apply_queue_meta_from(sm)
                self._notify_entity_update()
                _LOGGER.debug("Connect: shuffle mode set -> %s", self._shuffle_mode)
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_LOOP_MODE_SET:
            lm = qmsg.srvr_ctrl_loop_mode_set
            if lm and lm.HasField("mode"):
                self._loop_mode = int(lm.mode)
                self._notify_entity_update()
                _LOGGER.debug("Connect: loop mode set -> %s", self._loop_mode)
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_VOLUME_CHANGED:
            vol = qmsg.srvr_ctrl_volume_changed
            if vol and vol.HasField("renderer_id") and vol.HasField("volume"):
                rid = int(vol.renderer_id)
                level = max(0.0, min(1.0, int(vol.volume) / 100.0))
                self._renderer_volumes[rid] = level
                self._notify_entity_update()
                _LOGGER.debug("Connect: volume renderer=%s -> %.2f", rid, level)
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_MAX_AUDIO_QUALITY_CHANGED:
            aq = qmsg.srvr_ctrl_max_audio_quality_changed
            if aq and aq.HasField("max_audio_quality"):
                self._max_audio_quality = int(aq.max_audio_quality)
                self._notify_entity_update()
                _LOGGER.debug(
                    "Connect: max audio quality changed -> %s", self._max_audio_quality
                )
        else:
            _LOGGER.debug("Connect: unhandled message type %s", mt)

    def _apply_renderer_state(self, state: Any) -> None:
        """Update local playback state from a RendererState protobuf."""
        if state.HasField("playing_state"):
            self.playing_state = int(state.playing_state)
        if state.current_position and state.current_position.HasField("value"):
            self.current_position = int(state.current_position.value)
        if state.HasField("duration"):
            self.duration = int(state.duration)
        if state.HasField("current_queue_index"):
            self.current_queue_index = int(state.current_queue_index)
        self._notify_entity_update()

    def _apply_queue_meta_from(self, obj: Any) -> None:
        """Store queue_hash / action_uuid when present (needed for shuffle and some writes)."""
        if obj is None:
            return
        qh = getattr(obj, "queue_hash", None)
        if qh:
            self._queue_hash = bytes(qh)
        au = getattr(obj, "action_uuid", None)
        if au:
            self._queue_action_uuid = bytes(au)

    def _apply_queue_state(self, qs: Any) -> None:
        """Update local queue track list from SrvrCtrlQueueState."""
        self.queue_track_ids = [int(t.track_id) for t in qs.tracks if t.track_id]
        self._queue_tracks = [
            {"queue_item_id": int(t.queue_item_id), "track_id": int(t.track_id)}
            for t in qs.tracks
            if t.track_id
        ]
        if qs.queue_version:
            self._queue_version = {
                "major": int(qs.queue_version.major),
                "minor": int(qs.queue_version.minor),
            }
        self._apply_queue_meta_from(qs)
        if qs.HasField("shuffle_mode"):
            self._shuffle_mode = bool(qs.shuffle_mode)
        self._notify_entity_update()

    def _apply_queue_tracks_loaded(self, qtl: Any) -> None:
        """Update local queue track list from SrvrCtrlQueueLoadTracks (server response)."""
        self.queue_track_ids = [int(t.track_id) for t in qtl.tracks if t.track_id]
        self._queue_tracks = [
            {"queue_item_id": int(t.queue_item_id), "track_id": int(t.track_id)}
            for t in qtl.tracks
            if t.track_id
        ]
        if qtl.queue_version:
            self._queue_version = {
                "major": int(qtl.queue_version.major),
                "minor": int(qtl.queue_version.minor),
            }
        self._apply_queue_meta_from(qtl)
        self._notify_entity_update()

    def _apply_queue_tracks_added(self, added: Any) -> None:
        """Merge SrvrCtrlQueueTracksAdded (delta) into the local queue snapshot."""
        if added.queue_version:
            self._queue_version = {
                "major": int(added.queue_version.major),
                "minor": int(added.queue_version.minor),
            }
        self._apply_queue_meta_from(added)
        existing_ids = {int(r["queue_item_id"]) for r in self._queue_tracks}
        for t in added.tracks:
            if not t.track_id:
                continue
            qid = int(t.queue_item_id)
            if qid in existing_ids:
                continue
            self._queue_tracks.append(
                {"queue_item_id": qid, "track_id": int(t.track_id)}
            )
            existing_ids.add(qid)
        self.queue_track_ids = [int(r["track_id"]) for r in self._queue_tracks]
        self._notify_entity_update()

    async def _send_raw(self, data: bytes) -> None:
        if self._ws is None:
            return
        async with self._send_lock:
            await self._ws.send(data)

    async def _send_qconnect_ctrl(self, qmsg: Any) -> None:
        """Send a single QConnectMessage wrapped as PAYLOAD batch."""
        now = protocol.now_ms()
        batch_mid = self._msg_id
        payload_mid = self._next_msg_id()
        await self._send_raw(
            protocol.encode_qconnect_command(
                qmsg,
                batch_messages_id=batch_mid,
                payload_msg_id=payload_mid,
                now_ms=now,
            )
        )

    async def _send_authenticate(self, jwt: str) -> None:
        from .generated import Authenticate  # noqa: PLC0415

        auth = Authenticate()
        auth.msg_id = self._next_msg_id()
        auth.msg_date = protocol.now_ms()
        auth.jwt = jwt
        await self._send_raw(protocol.encode_authenticate_frame(auth))

    async def _send_subscribe(self) -> None:
        from .generated import Subscribe  # noqa: PLC0415

        sub = Subscribe()
        sub.msg_id = self._next_msg_id()
        sub.msg_date = protocol.now_ms()
        sub.proto = 1
        await self._send_raw(protocol.encode_subscribe_frame(sub))

    async def _send_join_controller(self) -> None:
        from .generated import (  # noqa: PLC0415
            CtrlSrvrJoinSession,
            DeviceCapabilities,
            DeviceInfo,
            DeviceType,
            QConnectMessage,
            QConnectMessageType,
        )

        device_uuid = uuid.uuid4().bytes
        self._join_device_uuid = device_uuid
        caps = DeviceCapabilities()
        caps.min_audio_quality = 1
        caps.max_audio_quality = 4
        caps.volume_remote_control = 2

        info = DeviceInfo()
        info.device_uuid = device_uuid
        info.friendly_name = "Home Assistant"
        info.brand = "Home Assistant"
        info.model = "Qobuz"
        # Web-style controller — matches typical browser / remote control clients
        info.type = DeviceType.DEVICE_TYPE_LAPTOP
        info.capabilities.CopyFrom(caps)
        info.software_version = f"ha-qobuz-{INTEGRATION_VERSION}"

        join = CtrlSrvrJoinSession()
        join.device_info.CopyFrom(info)

        qmsg = QConnectMessage()
        qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_JOIN_SESSION
        qmsg.ctrl_srvr_join_session.CopyFrom(join)

        now = protocol.now_ms()
        batch_mid = self._msg_id
        payload_mid = self._next_msg_id()
        frame = protocol.encode_qconnect_command(
            qmsg,
            batch_messages_id=batch_mid,
            payload_msg_id=payload_mid,
            now_ms=now,
        )
        await self._send_raw(frame)

    async def _send_ask_for_renderer_state(self) -> None:
        """Request current renderer state (requires session_id once known)."""
        from .generated import (  # noqa: PLC0415
            CtrlSrvrAskForRendererState,
            QConnectMessage,
            QConnectMessageType,
        )

        ask = CtrlSrvrAskForRendererState()
        ask.session_id = int(self._session_id) if self._session_id is not None else 0

        qmsg = QConnectMessage()
        qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_ASK_FOR_RENDERER_STATE
        qmsg.ctrl_srvr_ask_for_renderer_state.CopyFrom(ask)

        now = protocol.now_ms()
        batch_mid = self._msg_id
        payload_mid = self._next_msg_id()
        frame = protocol.encode_qconnect_command(
            qmsg,
            batch_messages_id=batch_mid,
            payload_msg_id=payload_mid,
            now_ms=now,
        )
        await self._send_raw(frame)

    async def _send_ask_for_queue_state(self) -> None:
        """Request queue state (queue_uuid = session UUID or our join UUID)."""
        from .generated import (  # noqa: PLC0415
            CtrlSrvrAskForQueueState,
            QConnectMessage,
            QConnectMessageType,
        )

        queue_uuid = self._session_uuid or self._join_device_uuid
        if not queue_uuid:
            _LOGGER.debug("Connect: skip ask_for_queue_state (no queue UUID yet)")
            return

        ask = CtrlSrvrAskForQueueState()
        ask.queue_uuid = queue_uuid

        qmsg = QConnectMessage()
        qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_ASK_FOR_QUEUE_STATE
        qmsg.ctrl_srvr_ask_for_queue_state.CopyFrom(ask)

        now = protocol.now_ms()
        batch_mid = self._msg_id
        payload_mid = self._next_msg_id()
        frame = protocol.encode_qconnect_command(
            qmsg,
            batch_messages_id=batch_mid,
            payload_msg_id=payload_mid,
            now_ms=now,
        )
        await self._send_raw(frame)

    async def _send_discovery_asks(self) -> None:
        """Ask server for renderer + queue snapshots (qonductor-style parameters)."""
        await self._send_ask_for_renderer_state()
        await self._send_ask_for_queue_state()

    async def _send_player_state(self, playing: bool, paused: bool) -> None:
        from .generated import (  # noqa: PLC0415
            CtrlSrvrSetPlayerState,
            PlayingState,
            QConnectMessage,
            QConnectMessageType,
        )

        qmsg = QConnectMessage()
        qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_SET_PLAYER_STATE
        ctrl = CtrlSrvrSetPlayerState()
        if paused:
            ctrl.playing_state = PlayingState.PLAYING_STATE_PAUSED
        elif playing:
            ctrl.playing_state = PlayingState.PLAYING_STATE_PLAYING
        else:
            ctrl.playing_state = PlayingState.PLAYING_STATE_STOPPED
        qmsg.ctrl_srvr_set_player_state.CopyFrom(ctrl)

        now = protocol.now_ms()
        batch_mid = self._msg_id
        payload_mid = self._next_msg_id()
        frame = protocol.encode_qconnect_command(
            qmsg,
            batch_messages_id=batch_mid,
            payload_msg_id=payload_mid,
            now_ms=now,
        )
        await self._send_raw(frame)

    async def set_active_renderer(self, renderer_id: int) -> None:
        """Switch playback to the given Connect renderer (transfer)."""
        from .generated import (  # noqa: PLC0415
            CtrlSrvrSetActiveRenderer,
            QConnectMessage,
            QConnectMessageType,
        )

        qmsg = QConnectMessage()
        qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_SET_ACTIVE_RENDERER
        ctrl = CtrlSrvrSetActiveRenderer()
        ctrl.renderer_id = renderer_id
        qmsg.ctrl_srvr_set_active_renderer.CopyFrom(ctrl)

        now = protocol.now_ms()
        batch_mid = self._msg_id
        payload_mid = self._next_msg_id()
        frame = protocol.encode_qconnect_command(
            qmsg,
            batch_messages_id=batch_mid,
            payload_msg_id=payload_mid,
            now_ms=now,
        )
        await self._send_raw(frame)

    async def media_play(self) -> None:
        await self._send_player_state(playing=True, paused=False)

    async def media_pause(self) -> None:
        await self._send_player_state(playing=False, paused=True)

    async def media_next_track(self) -> bool:
        """Skip to the next track in the queue. Returns True if successful."""
        next_idx = self.current_queue_index + 1
        if next_idx >= len(self._queue_tracks):
            _LOGGER.debug("Connect: no next track (at end of queue)")
            return False
        return await self._skip_to_queue_index(next_idx)

    async def media_previous_track(self) -> bool:
        """Skip to the previous track in the queue. Returns True if successful."""
        prev_idx = self.current_queue_index - 1
        if prev_idx < 0:
            _LOGGER.debug("Connect: no previous track (at start of queue)")
            return False
        return await self._skip_to_queue_index(prev_idx)

    async def _skip_to_queue_index(self, target_idx: int) -> bool:
        """Set the player state to play the track at the given queue index."""
        from .generated import (  # noqa: PLC0415
            CtrlSrvrSetPlayerState,
            PlayingState,
            QConnectMessage,
            QConnectMessageType,
        )

        if not self._queue_tracks or not self._queue_version:
            _LOGGER.debug("Connect: no queue data for track skip")
            return False
        if target_idx < 0 or target_idx >= len(self._queue_tracks):
            return False

        target_item = self._queue_tracks[target_idx]
        queue_item_id = target_item["queue_item_id"]

        qmsg = QConnectMessage()
        qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_SET_PLAYER_STATE
        ctrl = CtrlSrvrSetPlayerState()
        ctrl.playing_state = PlayingState.PLAYING_STATE_PLAYING
        ctrl.current_position = 0
        qi = ctrl.current_queue_item
        qi.id = queue_item_id
        qv = qi.queue_version
        qv.major = self._queue_version["major"]
        qv.minor = self._queue_version["minor"]
        qmsg.ctrl_srvr_set_player_state.CopyFrom(ctrl)
        await self._send_qconnect_ctrl(qmsg)
        self._notify_entity_update()
        _LOGGER.debug("Connect: skipping to queue index %s (item %s)", target_idx, queue_item_id)
        return True

    async def transfer_playback(self, device_id: str) -> None:
        """Transfer to device id string (renderer numeric id)."""
        try:
            rid = int(device_id)
        except ValueError as err:
            raise ValueError(f"Invalid device id {device_id!r}") from err
        await self.set_active_renderer(rid)

    async def _receive_loop(self) -> None:
        assert self._ws is not None
        async for message in self._ws:
            if isinstance(message, bytes):
                for batch in protocol.iter_batches_from_ws_binary(message):
                    for qmsg in batch.messages:
                        self._handle_qmsg(qmsg)
                    await self._flush_pending_discovery_asks()
            elif isinstance(message, str):
                _LOGGER.debug("Unexpected WS text: %s", message[:120])

    async def _flush_pending_discovery_asks(self) -> None:
        """Send AskFor* after SESSION_STATE (same event loop as WS reader)."""
        if not self._pending_discovery_asks:
            return
        self._pending_discovery_asks = False
        try:
            await self._send_discovery_asks()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Connect: discovery asks failed: %s", err)

    async def _one_connection(self) -> bool:
        """Attempt one Connect session. Returns True if it connected successfully."""
        try:
            tok = await self._api.create_qws_token()
        except QobuzAPIError as err:
            if self._consecutive_failures == 0:
                _LOGGER.warning(
                    "Qobuz Connect: cannot create WS token: %s "
                    "(will keep retrying in the background). "
                    "Playback from other devices uses Connect when this succeeds; "
                    "REST /player/getState is often unavailable (503) even with a valid account.",
                    err,
                )
            else:
                _LOGGER.debug("Qobuz Connect: createToken retry failed: %s", err)
            self._consecutive_failures += 1
            return False
        except Exception:  # noqa: BLE001
            if self._consecutive_failures == 0:
                _LOGGER.warning("Qobuz Connect: createToken failed unexpectedly")
            self._consecutive_failures += 1
            return False

        jwt = tok["jwt"]
        uri = tok["endpoint"]
        self._msg_id = 0
        self._session_id = None
        self._session_uuid = None
        self._join_device_uuid = None
        self._pending_discovery_asks = False

        connect_kw: dict[str, Any] = {
            "additional_headers": {
                "Origin": "https://play.qobuz.com",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            },
            "max_size": None,
        }
        if uri.lower().startswith("wss"):
            connect_kw["ssl"] = await self.hass.async_add_executor_job(
                _default_ssl_context
            )

        try:
            self._ws = await websockets.connect(uri, **connect_kw)
        except Exception as err:  # noqa: BLE001
            if self._consecutive_failures == 0:
                _LOGGER.warning("Qobuz Connect WebSocket connection failed: %s", err)
            else:
                _LOGGER.debug("Qobuz Connect WebSocket retry failed: %s", err)
            self._consecutive_failures += 1
            return False

        self._connected = True
        self._consecutive_failures = 0
        _LOGGER.info("Qobuz Connect WebSocket connected to %s", uri)
        self._reset_connect_session_cache()

        try:
            await self._send_authenticate(jwt)
            await self._send_subscribe()
            await self._send_join_controller()
            await self._send_discovery_asks()
            await self._receive_loop()
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Qobuz Connect session ended: %s", err)
        finally:
            await self._close_ws()
        return True

    async def _run_loop(self) -> None:
        backoff = 30
        while not self._stop.is_set():
            connected = await self._one_connection()
            if self._stop.is_set():
                break
            if connected:
                backoff = 5
            _LOGGER.debug("Qobuz Connect reconnecting in %ss", backoff)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            backoff = min(backoff * 2, 300)

    async def play_track_now(self, track_id: int) -> bool:
        """Clear the session queue, add one track, and start playback at index 0."""
        import time

        if not self._connected or self._ws is None or track_id <= 0:
            return False
        import qconnect_queue_pb2 as qq

        from .generated import QConnectMessage, QConnectMessageType

        tid_u32 = track_id & 0xFFFFFFFF
        suggested_qid = (int(track_id) << 16) ^ tid_u32

        if self._queue_version is not None:
            clear = qq.CtrlSrvrClearQueue()
            clear.queue_version.major = self._queue_version["major"]
            clear.queue_version.minor = self._queue_version["minor"]
            cq = QConnectMessage()
            cq.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_CLEAR_QUEUE
            cq.ctrl_srvr_clear_queue.CopyFrom(clear)
            await self._send_qconnect_ctrl(cq)
            self._queue_version = None
            self._queue_tracks.clear()
            self.queue_track_ids.clear()
            self._queue_hash = None
            self._queue_action_uuid = None
            await asyncio.sleep(0.15)

        add = qq.CtrlSrvrQueueAddTracks()
        if self._queue_version is not None:
            add.queue_version.major = self._queue_version["major"]
            add.queue_version.minor = self._queue_version["minor"]
        if self._queue_hash:
            add.queue_hash = self._queue_hash
        if self._queue_action_uuid:
            add.action_uuid = self._queue_action_uuid
        tr = add.tracks.add()
        tr.queue_item_id = suggested_qid
        tr.track_id = tid_u32
        aq = QConnectMessage()
        aq.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_QUEUE_ADD_TRACKS
        aq.ctrl_srvr_queue_add_tracks.CopyFrom(add)
        await self._send_qconnect_ctrl(aq)

        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            if not self._connected or self._ws is None:
                _LOGGER.debug("Connect: play_track_now aborted (WebSocket closed)")
                return False
            if self._queue_tracks and self._queue_version:
                return await self._skip_to_queue_index(0)
            try:
                await self._send_ask_for_queue_state()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Connect: play_track_now ask_for_queue_state: %s", err)
                return False
            await asyncio.sleep(0.2)

        _LOGGER.warning(
            "Connect: play_track_now could not resolve queue for track_id=%s",
            track_id,
        )
        return False

    async def set_shuffle_mode(self, shuffle_on: bool) -> None:
        """Toggle shuffle via QConnect (requires current queue item + version)."""
        if not self._connected or not self._queue_tracks or not self._queue_version:
            _LOGGER.debug("Connect: shuffle — no queue context")
            return
        import qconnect_payload_pb2 as qp

        from .generated import QConnectMessage, QConnectMessageType

        idx = min(self.current_queue_index, len(self._queue_tracks) - 1)
        item_id = int(self._queue_tracks[idx]["queue_item_id"])
        sh = qp.CtrlSrvrSetShuffleMode()
        sh.queue_version.major = self._queue_version["major"]
        sh.queue_version.minor = self._queue_version["minor"]
        sh.shuffle_on = shuffle_on
        sh.current_queue_item_id = item_id & 0xFFFFFFFF
        if self._queue_hash:
            sh.queue_hash = self._queue_hash
        if self._queue_action_uuid:
            sh.action_uuid = self._queue_action_uuid
        qmsg = QConnectMessage()
        qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_SET_SHUFFLE_MODE
        qmsg.ctrl_srvr_set_shuffle_mode.CopyFrom(sh)
        await self._send_qconnect_ctrl(qmsg)

    async def set_loop_mode(self, loop_mode: int) -> None:
        """Set repeat / loop mode (qconnect LoopMode enum value)."""
        if not self._connected:
            return
        import qconnect_payload_pb2 as qp

        from .generated import QConnectMessage, QConnectMessageType

        lm = qp.CtrlSrvrSetLoopMode()
        lm.mode = loop_mode
        qmsg = QConnectMessage()
        qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_SET_LOOP_MODE
        qmsg.ctrl_srvr_set_loop_mode.CopyFrom(lm)
        await self._send_qconnect_ctrl(qmsg)

    async def set_repeat_mode(self, mode: str) -> None:
        """Map HA-style repeat string to LoopMode and send."""
        from qconnect_common_pb2 import LoopMode  # noqa: PLC0415

        key = (mode or "off").lower()
        if "one" in key:
            val = int(LoopMode.LOOP_MODE_REPEAT_ONE)
        elif "all" in key:
            val = int(LoopMode.LOOP_MODE_REPEAT_ALL)
        else:
            val = int(LoopMode.LOOP_MODE_OFF)
        await self.set_loop_mode(val)

    async def media_seek(self, position_sec: float) -> bool:
        """Seek current queue item to ``position_sec`` (Connect)."""
        if not self._connected or not self._queue_tracks or not self._queue_version:
            _LOGGER.debug("Connect: seek — no queue context")
            return False
        from .generated import (  # noqa: PLC0415
            CtrlSrvrSetPlayerState,
            QConnectMessage,
            QConnectMessageType,
        )

        pos_ms = max(0, min(0xFFFFFFFF, int(float(position_sec) * 1000)))
        idx = min(max(0, self.current_queue_index), len(self._queue_tracks) - 1)
        target_item = self._queue_tracks[idx]
        queue_item_id = int(target_item["queue_item_id"])

        qmsg = QConnectMessage()
        qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_SET_PLAYER_STATE
        ctrl = CtrlSrvrSetPlayerState()
        ctrl.playing_state = self.playing_state
        ctrl.current_position = pos_ms
        qi = ctrl.current_queue_item
        qi.id = queue_item_id & 0xFFFFFFFF
        qv = qi.queue_version
        qv.major = self._queue_version["major"]
        qv.minor = self._queue_version["minor"]
        qmsg.ctrl_srvr_set_player_state.CopyFrom(ctrl)
        await self._send_qconnect_ctrl(qmsg)
        self._notify_entity_update()
        _LOGGER.debug("Connect: seek to %sms (queue item %s)", pos_ms, queue_item_id)
        return True

    async def set_volume_level(self, level: float) -> None:
        """Set absolute volume on the active renderer (``level`` 0..1)."""
        if not self._connected or self._active_renderer_id is None:
            _LOGGER.debug("Connect: volume — no active renderer")
            return
        import qconnect_payload_pb2 as qp

        from .generated import QConnectMessage, QConnectMessageType

        rid = int(self._active_renderer_id)
        if rid < -2147483648 or rid > 2147483647:
            _LOGGER.warning(
                "Connect: volume — renderer id %s does not fit int32; cannot send",
                rid,
            )
            return
        pct = max(0, min(100, int(round(float(level) * 100))))
        ctrl = qp.CtrlSrvrSetVolume()
        ctrl.renderer_id = rid
        ctrl.volume = pct
        qmsg = QConnectMessage()
        qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_SET_VOLUME
        qmsg.ctrl_srvr_set_volume.CopyFrom(ctrl)
        await self._send_qconnect_ctrl(qmsg)

    async def set_max_streaming_quality(self, quality: int) -> None:
        """Request a max streaming quality id via Connect (Qobuz quality scale)."""
        if not self._connected:
            return
        import qconnect_payload_pb2 as qp

        from .generated import QConnectMessage, QConnectMessageType

        ctrl = qp.CtrlSrvrSetMaxAudioQuality()
        ctrl.max_audio_quality = int(quality)
        qmsg = QConnectMessage()
        qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_SET_MAX_AUDIO_QUALITY
        qmsg.ctrl_srvr_set_max_audio_quality.CopyFrom(ctrl)
        await self._send_qconnect_ctrl(qmsg)

    async def discover_devices(self) -> list[dict[str, Any]]:
        """Return Connect devices seen on the WebSocket."""
        return list(self.devices)
