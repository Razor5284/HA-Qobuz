# ADR 0002: Phase 3 — QConnect controller (WebSocket + protobuf)

## Status
Accepted (May 2026)

## Context
Phase 1–2 delivered REST-backed library browsing, polling playback, sensors, and a Connect **scaffold**. Users need real **Qobuz Connect** behaviour: discover cast/speaker renderers, transfer playback, and remote transport without relying only on `/player/getState`.

Community reference: the Rust [qonductor](https://github.com/nickblt/qonductor) crate documents the wire format:

- Outer envelope: `[msg_type: u8][varint length][payload]`
- `Authenticate` / `Subscribe` / `Payload` messages (`proto/qconnect_envelope.proto`)
- Inner `QConnectBatch` / `QConnectMessage` (`proto/qconnect_payload.proto`)
- JWT from Qobuz REST: `GET /api.json/0.2/qws/createToken` → `jwt` + regional `wss://…/ws` endpoint

## Decision
Implement a **pure-Python controller client** inside `custom_components/qobuz/connect/`:

1. **`api.create_qws_token()`** — normalize nested `jwt_qws` JSON from the API.
2. **`websockets`** to the regional endpoint; send `Authenticate` + `Subscribe` + `CtrlSrvrJoinSession` as Home Assistant controller (friendly name “Home Assistant”).
3. **Generated Python protobuf** from the same `.proto` files as qonductor (vendored under `connect/proto/`, generated code under `connect/generated/`).
4. **Inbound handlers** for `SrvrCtrlAddRenderer`, `SrvrCtrlRemoveRenderer`, `SrvrCtrlActiveRendererChanged` to populate `source_list` / `source`.
5. **Outbound** `CtrlSrvrSetPlayerState` (play/pause) and `CtrlSrvrSetActiveRenderer` (transfer), invoked from `media_player` and `qobuz.transfer_playback`.
6. **Lazy export** in `connect/__init__.py` so importing `connect.protocol` for tests does not require `websockets` until the client class is used.
7. **`async_dispatcher_send`** on device list / active renderer changes so the media player updates without waiting for the next poll.

## Consequences
- **Positive**: Feature parity with “Spotify Connect–style” switching for many setups; no native binary; covered by unit tests for framing.
- **Trade-offs**: Next/previous/shuffle/queue require additional message types and queue state — deferred. Protocol changes by Qobuz may break WS handling; reconnect loop mitigates transient failures.
- **Dependency**: `protobuf` added to `manifest.json` for generated modules.

## References
- nickblt/qonductor `connection.rs`, `proto/*.proto`
- Qobuz community patterns for `/qws/createToken`
