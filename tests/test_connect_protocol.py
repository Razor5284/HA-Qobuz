"""Tests for QConnect wire framing (nickblt/qonductor-compatible envelopes)."""

from __future__ import annotations

from custom_components.qobuz.connect import protocol
from custom_components.qobuz.connect.generated import (
    Payload,
    QConnectBatch,
    QConnectMessage,
    QConnectMessageType,
)


def test_encode_decode_payload_roundtrip() -> None:
    inner = QConnectMessage()
    inner.message_type = QConnectMessageType.MESSAGE_TYPE_CTRL_SRVR_JOIN_SESSION

    batch = QConnectBatch()
    batch.messages_time = protocol.now_ms()
    batch.messages_id = 2
    batch.messages.append(inner)

    outer = Payload()
    outer.msg_id = 3
    outer.msg_date = protocol.now_ms()
    outer.proto = 1
    outer.payload = batch.SerializeToString()

    frame = protocol.encode_envelope(protocol.QCLOUD_PAYLOAD, outer.SerializeToString())
    batches = list(protocol.iter_batches_from_ws_binary(frame))
    assert len(batches) == 1
    assert len(batches[0].messages) == 1
    assert batches[0].messages[0].message_type == inner.message_type


def test_authenticate_envelope_prefix() -> None:
    from custom_components.qobuz.connect.generated import Authenticate

    auth = Authenticate()
    auth.msg_id = 1
    auth.msg_date = 1000
    auth.jwt = "abc"
    raw = protocol.encode_authenticate_frame(auth)
    assert raw[0] == protocol.QCLOUD_AUTHENTICATE
