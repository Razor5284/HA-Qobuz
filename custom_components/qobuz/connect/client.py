"""Qobuz Connect WebSocket client — controller session (devices + transport)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
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

INTEGRATION_VERSION = "0.9.0"


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

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def active_device_name(self) -> str | None:
        if self._active_renderer_id is None:
            return None
        r = self._renderers.get(self._active_renderer_id)
        return r.get("name") if r else None

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

    def _handle_qmsg(self, qmsg: Any) -> None:
        from .generated import QConnectMessageType  # noqa: PLC0415

        mt = qmsg.message_type or 0
        if mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_ADD_RENDERER:
            add = qmsg.srvr_ctrl_add_renderer
            if add and add.renderer_id and add.renderer:
                rid = int(add.renderer_id)
                di = add.renderer
                name = di.friendly_name or di.model or f"Renderer {rid}"
                self._renderers[rid] = {"name": name, "device_info": di}
                self._sync_device_list()
                _LOGGER.debug("Connect: added renderer %s (%s)", rid, name)
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_REMOVE_RENDERER:
            rem = qmsg.srvr_ctrl_remove_renderer
            if rem and rem.renderer_id:
                rid = int(rem.renderer_id)
                self._renderers.pop(rid, None)
                if self._active_renderer_id == rid:
                    self._active_renderer_id = None
                self._sync_device_list()
                _LOGGER.debug("Connect: removed renderer %s", rid)
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_ACTIVE_RENDERER_CHANGED:
            ch = qmsg.srvr_ctrl_active_renderer_changed
            if ch and ch.renderer_id is not None:
                self._active_renderer_id = int(ch.renderer_id)
                self._notify_entity_update()
                _LOGGER.debug("Connect: active renderer -> %s", self._active_renderer_id)
        elif mt == QConnectMessageType.MESSAGE_TYPE_SRVR_CTRL_SESSION_STATE:
            _LOGGER.debug("Connect: session state update")

    async def _send_raw(self, data: bytes) -> None:
        if self._ws is None:
            return
        async with self._send_lock:
            await self._ws.send(data)

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
        caps = DeviceCapabilities()
        caps.min_audio_quality = 1
        caps.max_audio_quality = 4
        caps.volume_remote_control = 2

        info = DeviceInfo()
        info.device_uuid = device_uuid
        info.friendly_name = "Home Assistant"
        info.brand = "Home Assistant"
        info.model = "Qobuz"
        info.type = DeviceType.DEVICE_TYPE_SPEAKER
        info.capabilities = caps
        info.software_version = f"ha-qobuz-{INTEGRATION_VERSION}"

        join = CtrlSrvrJoinSession()
        join.device_info = info

        qmsg = QConnectMessage()
        qmsg.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_JOIN_SESSION
        qmsg.ctrl_srvr_join_session = join

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
        qmsg.ctrl_srvr_set_player_state = ctrl

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
        qmsg.ctrl_srvr_set_active_renderer = ctrl

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
            elif isinstance(message, str):
                _LOGGER.debug("Unexpected WS text: %s", message[:120])

    async def _one_connection(self) -> None:
        try:
            tok = await self._api.create_qws_token()
        except QobuzAPIError as err:
            _LOGGER.warning("Qobuz Connect: cannot create WS token: %s", err)
            return
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Qobuz Connect: createToken failed")
            return

        jwt = tok["jwt"]
        uri = tok["endpoint"]
        self._msg_id = 0

        try:
            self._ws = await websockets.connect(
                uri,
                additional_headers={"Origin": "https://play.qobuz.com"},
                max_size=None,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Qobuz Connect WebSocket failed: %s", err)
            return

        self._connected = True
        _LOGGER.info("Qobuz Connect WebSocket connected to %s", uri)

        try:
            await self._send_authenticate(jwt)
            await self._send_subscribe()
            await self._send_join_controller()
            await self._receive_loop()
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Qobuz Connect session ended: %s", err)
        finally:
            await self._close_ws()

    async def _run_loop(self) -> None:
        backoff = 5
        while not self._stop.is_set():
            await self._one_connection()
            if self._stop.is_set():
                break
            _LOGGER.debug("Qobuz Connect reconnecting in %ss", backoff)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            backoff = min(backoff * 2, 120)

    async def discover_devices(self) -> list[dict[str, Any]]:
        """Return Connect devices seen on the WebSocket."""
        return list(self.devices)
