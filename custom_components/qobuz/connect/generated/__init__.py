"""Protobuf modules for Qobuz Connect (generated from qonductor protos; see proto/)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_gen_dir = Path(__file__).resolve().parent
_LOAD_ORDER = (
    "qconnect_common_pb2",
    "qconnect_queue_pb2",
    "qconnect_envelope_pb2",
    "qconnect_payload_pb2",
)


def _load_pb2_modules() -> None:
    for name in _LOAD_ORDER:
        if name in sys.modules:
            continue
        path = _gen_dir / f"{name}.py"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            msg = f"Cannot load protobuf module {name} from {path}"
            raise ImportError(msg)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)


_load_pb2_modules()

from qconnect_common_pb2 import (  # noqa: E402
    DeviceCapabilities,
    DeviceInfo,
    DeviceType,
    PlayingState,
    RendererState,
)
from qconnect_envelope_pb2 import (  # noqa: E402
    Authenticate,
    Payload,
    QCloudMessageType,
    Subscribe,
)
from qconnect_payload_pb2 import (  # noqa: E402
    CtrlSrvrAskForQueueState,
    CtrlSrvrAskForRendererState,
    CtrlSrvrJoinSession,
    CtrlSrvrSetActiveRenderer,
    CtrlSrvrSetLoopMode,
    CtrlSrvrSetPlayerState,
    QConnectBatch,
    QConnectMessage,
    QConnectMessageType,
    SrvrCtrlRendererStateUpdated,
)
from qconnect_queue_pb2 import (  # noqa: E402
    SrvrCtrlQueueState,
)

__all__ = [
    "Authenticate",
    "CtrlSrvrAskForQueueState",
    "CtrlSrvrAskForRendererState",
    "CtrlSrvrJoinSession",
    "CtrlSrvrSetActiveRenderer",
    "CtrlSrvrSetLoopMode",
    "CtrlSrvrSetPlayerState",
    "DeviceCapabilities",
    "DeviceInfo",
    "DeviceType",
    "Payload",
    "PlayingState",
    "QCloudMessageType",
    "QConnectBatch",
    "QConnectMessage",
    "QConnectMessageType",
    "RendererState",
    "SrvrCtrlQueueState",
    "SrvrCtrlRendererStateUpdated",
    "Subscribe",
]
