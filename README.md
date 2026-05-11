# HA-Qobuz

Home Assistant integration for Qobuz music streaming, with rich library browsing, playback control, and Qobuz Connect support.

> **Important disclaimer**: This is an **unofficial integration** using reverse-engineered and community-documented API patterns (no official public Spotify-like Web API exists for Qobuz). It is **fully AI-generated code**. Use at your own risk. Qobuz may change endpoints without notice, and this may violate their Terms of Service. No warranty, no official support from Qobuz or the author. Credentials are handled securely but you should use a dedicated or limited account if concerned.

Compatible with latest Home Assistant (2025+ patterns).

## Features (comparable to SpotifyPlus where feasible)

- Media player entity with play/pause/next/previous, browse media (playlists → tracks)
- Rich metadata (title, artist, album, cover art)
- Qobuz Connect: device/source selection (enumeration + transfer stubbed; full controller in active development per ADR)
- Config flow with re-auth
- Diagnostics support

## Installation via HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Razor5284&repository=HA-Qobuz&category=integration)

**Manual HACS steps** (if the button above doesn't work):

1. Go to HACS → Integrations → three-dot menu → Custom repositories
2. Add `https://github.com/Razor5284/HA-Qobuz` as category **Integration**
3. Install "Qobuz"
4. Restart Home Assistant
5. Settings → Devices & Services → Add Integration → search "Qobuz"

## Configuration

The integration uses a standard config flow:

- Enter your Qobuz **email** and **password** (used only for initial token exchange; password is never stored).
- Supports re-authentication on token expiry.

After setup, a `media_player.qobuz` entity appears.

### Options (via UI)

- Polling interval (default 30s)
- Preferred streaming quality (lossless / hi-res where available)
- App ID / Secret overrides (advanced, for custom credentials from Qobuz)

## Qobuz Connect

The integration aims for first-class Connect support:

- Pull available devices
- Switch active stream ("transfer playback")
- Transport controls on remote devices

See [docs/adr/0001-qobuz-connect-approach.md](docs/adr/0001-qobuz-connect-approach.md) for the pure-Python decision and current limitations (renderer advertisement + best-effort controller).

## Development & Maintenance

- Versioning follows semantic versioning (e.g. 0.1.0 initial).
- Full test suite + CI (pytest, ruff) ensures long-term maintainability.
- See `CONTRIBUTING.md` (to be added) for running tests and contributing fixtures.

## Credits

Inspired by the excellent [SpotifyPlus](https://github.com/thlucas1/homeassistantcomponent_spotifyplus) integration for scope and UX patterns.

## Changelog

See GitHub releases for detailed changes. Initial release focuses on MVP + Connect scaffolding.

---

**Repository**: https://github.com/Razor5284/HA-Qobuz (update this link after publishing/forking)
