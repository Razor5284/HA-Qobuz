# ADR 0001: Qobuz Connect Implementation Approach

## Status
Accepted (Phase 0 decision, May 2026)

## Context
Qobuz Connect is a proprietary WebSocket + Protobuf-based protocol for device discovery, playback control, and multi-room streaming. The goal is to support:
- Enumerating available Qobuz Connect devices/outputs
- Switching active playback ("transfer stream") to those devices
- Transport controls (play/pause/seek/volume) on the active device

Unlike Spotify Connect (well-documented public Web API + Connect SDK), Qobuz's Connect protocol is reverse-engineered. The Rust `qonductor` crate provides a solid reference implementation primarily for the **renderer** (device) side.

No official Python client or public controller API exists. Community projects (qobuz-player, qobuz-proxy) focus on renderer or proxy roles.

## Decision
**Pure-Python implementation using `aiohttp` + `websockets` + `protobuf` (or dynamic message handling). No companion binary or microservice for v1.**

Rationale:
- Keeps the integration self-contained, easy to install via HACS, no external runtime deps or build steps.
- Aligns with Home Assistant's preference for pure-Python custom components.
- The main Qobuz account REST API (via unofficial but widely used patterns: api.json endpoints, JWT/session tokens) already provides library access, playlists, favorites, and basic playback initiation.
- For Connect device listing and transfer, initial support will:
  - Expose the integration's own `media_player` as a Connect-compatible target where feasible (mDNS advertisement + WS listener for incoming commands, modeled after qonductor but in Python).
  - Use any discoverable REST endpoints for "active devices" or "player status" if present in the authenticated session.
  - Provide `select_source` / source_list for manually configured or discovered devices, with transport proxied via the main API or WS when possible.
- Full bidirectional controller (HA discovers and commands arbitrary Qobuz Connect renderers without the official app) is deferred to a future phase or optional advanced mode, as it requires complete protobuf schema reverse-engineering for controller->renderer messages and may violate Qobuz ToS or change frequently.

## Consequences
- **Positive**: Faster initial delivery of rich media_player + browsing (Phase 1), solid foundation, maintainable test suite.
- **Trade-offs**: True "pull available devices and switch" may initially be limited to devices visible via the user's Qobuz session or manual config; full auto-discovery of all LAN Connect devices requires mDNS + controller WS logic (stretch goal).
- **Risks**: Protocol changes by Qobuz will break WS/Connect parts; mitigated by clear diagnostics, versioned client, and fallback to REST-only mode.
- **Next steps**: Phase 1 implements the REST client and media_player MVP. Connect renderer advertisement and basic source switching added in Phase 2. If controller features prove essential, evaluate adding a lightweight Python protobuf generator step or optional Rust helper (but prefer avoiding).

## References
- qonductor crate docs (renderer commands, JWT flow, direct connect)
- Community issues on qobuz-player for auth/token creation (`/api.json/0.2/qws/createToken`)
- Qobuz Connect user help pages (device compatibility, transfer flow)

This decision was reached after reviewing available open-source implementations and API patterns; no official Qobuz third-party Connect controller SDK was identified.
