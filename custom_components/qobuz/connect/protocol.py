"""QConnect WebSocket framing — follows nickblt/qonductor connection.rs."""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

QCLOUD_AUTHENTICATE = 1
QCLOUD_SUBSCRIBE = 2
QCLOUD_PAYLOAD = 6
QCLOUD_ERROR = 9


def encode_varint(value: int) -> bytes:
    """Encode unsigned protobuf-style varint."""
    out = bytearray()
    while value > 127:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value & 0x7F)
    return bytes(out)


def decode_varint(buf: bytes, pos: int = 0) -> tuple[int, int]:
    """Decode varint; returns (value, new_position)."""
    result = 0
    shift = 0
    while pos < len(buf):
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
        if shift > 64:
            raise ValueError("varint too long")
    raise ValueError("truncated varint")


def encode_envelope(msg_type: int, data: bytes) -> bytes:
    """Wire format: [msg_type: u8][payload_len: varint][payload]."""
    buf = bytearray()
    buf.append(msg_type & 0xFF)
    buf.extend(encode_varint(len(data)))
    buf.extend(data)
    return bytes(buf)


def iter_batches_from_ws_binary(data: bytes):
    """Parse one WS binary frame into zero or one QConnectBatch."""
    from .generated import Payload, QConnectBatch

    if not data:
        return
    msg_type = data[0]
    payload_len, next_pos = decode_varint(data, 1)
    end = next_pos + payload_len
    if end > len(data):
        _LOGGER.debug("Incomplete envelope")
        return
    outer_bytes = data[next_pos:end]
    if msg_type == QCLOUD_ERROR:
        _LOGGER.warning("Qobuz Connect error frame (%s bytes)", len(outer_bytes))
        return
    if msg_type != QCLOUD_PAYLOAD:
        _LOGGER.debug("Unhandled envelope type %s", msg_type)
        return
    outer_pl = Payload()
    outer_pl.ParseFromString(outer_bytes)
    if not outer_pl.payload:
        return
    batch = QConnectBatch()
    batch.ParseFromString(outer_pl.payload)
    yield batch


def encode_authenticate_frame(auth_msg) -> bytes:
    """Envelope type AUTHENTICATE (1)."""
    return encode_envelope(QCLOUD_AUTHENTICATE, auth_msg.SerializeToString())


def encode_subscribe_frame(sub_msg) -> bytes:
    """Envelope type SUBSCRIBE (2)."""
    return encode_envelope(QCLOUD_SUBSCRIBE, sub_msg.SerializeToString())


def encode_qconnect_command(
    qmsg,
    *,
    batch_messages_id: int,
    payload_msg_id: int,
    now_ms: int,
) -> bytes:
    """Wrap QConnectMessage in QConnectBatch -> Payload -> outer envelope (PAYLOAD=6)."""
    from .generated import Payload, QConnectBatch

    batch = QConnectBatch()
    batch.messages_time = now_ms
    batch.messages_id = batch_messages_id
    batch.messages.append(qmsg)
    outer = Payload()
    outer.msg_id = payload_msg_id
    outer.msg_date = now_ms
    outer.proto = 1
    outer.payload = batch.SerializeToString()
    return encode_envelope(QCLOUD_PAYLOAD, outer.SerializeToString())


def now_ms() -> int:
    import time

    return int(time.time() * 1000)
