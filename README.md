# HA-Qobuz

Home Assistant integration for Qobuz music streaming, with rich library browsing, playback control, and Qobuz Connect support.

> **Important disclaimer**: This is an **unofficial integration** using reverse-engineered and community-documented API patterns (no official public Spotify-like Web API exists for Qobuz). It is **fully AI-generated code**. Use at your own risk. Qobuz may change endpoints without notice, and this may violate their Terms of Service. No warranty, no official support from Qobuz or the author. Credentials are handled securely but you should use a dedicated or limited account if concerned.

Compatible with latest Home Assistant (2025+ patterns).

## Features (comparable to SpotifyPlus where feasible)

- Media player entity with browse media (playlists, favourites → tracks), signed stream URLs when the player bundle secret can be scraped
- **Qobuz Connect (Phase 3)**: WebSocket controller session — discovers Connect renderers, transfer playback (`select_source` / service), play/pause via Connect when the session is active (protobuf protocol aligned with [qonductor](https://github.com/nickblt/qonductor))
- REST polling for library + “now playing” via `/player/getState` where available
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

You authenticate with a **browser session token** (not your password — Qobuz blocks automated login). After setup, a `media_player` and account/subscription sensors appear under one device.

### Options (via UI)

- **Polling interval** (default 30s)

Advanced overrides (app id / secret) are not exposed in the options flow yet; the integration scrapes current credentials from the official web player bundle when possible.

## Qobuz Connect

When `/qws/createToken` succeeds, the integration opens a regional **QConnect WebSocket**, authenticates with the issued JWT, joins as a **controller** (“Home Assistant”), and listens for renderer add/remove/active events. You can:

- See **sources** = discovered Connect devices (speaker/TV/Cast endpoints registered with Qobuz)
- **Transfer playback** to a device (media player → Source, or `qobuz.transfer_playback`)
- **Play / Pause** via Connect when the WS session is connected (otherwise state still follows REST polling)

**Next/previous** track skipping is not mapped yet (queue-level QConnect messages); use the Qobuz app or the device UI if needed.

See [docs/adr/0001-qobuz-connect-approach.md](docs/adr/0001-qobuz-connect-approach.md) and [docs/adr/0002-phase3-qconnect-controller.md](docs/adr/0002-phase3-qconnect-controller.md).

## Development & Maintenance

- Versioning follows semantic versioning (e.g. 0.1.0 initial).
- Full test suite + CI (pytest, ruff) ensures long-term maintainability.
- See `CONTRIBUTING.md` (to be added) for running tests and contributing fixtures.

## Credits

Inspired by the excellent [SpotifyPlus](https://github.com/thlucas1/homeassistantcomponent_spotifyplus) integration for scope and UX patterns.

## Changelog

See GitHub releases for detailed changes.

**v0.10.0** — Connect playback state, metadata & track skipping:
- **Fix**: Connect WebSocket now processes `RENDERER_STATE_UPDATED`, `QUEUE_STATE`, and `SESSION_STATE` messages — playback state (playing/paused), track metadata, and device info are now properly surfaced to the media player entity
- **Fix**: When the REST `/player/getState` endpoint returns no data (common for most accounts), the coordinator falls back to Connect WebSocket state and fetches track metadata via `get_track_info()` API
- **New**: Next/previous track via Qobuz Connect protocol (sends `CtrlSrvrSetPlayerState` with target queue item)
- **New**: On WebSocket connect, client immediately requests current renderer and queue state so existing playback is picked up
- **New**: `source` attribute and source list now reliably reflect Connect devices and the active playback device

**v0.9.0** — Full QConnect WebSocket controller (device list, transfer, play/pause via Connect).

## Troubleshooting

### HACS "Download failed" or 404 zipball error

If you see an error like:

> Got status code 404 when trying to download .../archive/refs/heads/f530bf8.zip

This usually means HACS tried to fetch a non-existent branch or commit hash.

**Fix:**
1. In HACS → Custom repositories, remove the entry if it points to a specific commit/hash.
2. Re-add using exactly: `https://github.com/Razor5284/HA-Qobuz` (no branch or commit suffix).
3. Make sure the repository's default branch on GitHub is `main` (or `master`) and contains the latest code.
4. For the most reliable installs, create a **GitHub Release** (see "Development, Versioning & Releasing" below). HACS prefers releases.

After fixing, click "Redownload" in the integration card in HACS.

### "No JWT for Connect" or Connect reconnect messages in logs

If `/qws/createToken` fails, check that your session token is valid and review logs for API errors. When Connect starts correctly you should see **Qobuz Connect WebSocket connected** at INFO level.

## Development, Versioning & Releasing (for maintainers)

We follow a lightweight GitHub Flow + Semantic Versioning process.

### Branching model
- `main` — stable, releasable code only.
- Feature branches: `feature/short-description` or `fix/issue-xxx`.
- Never commit directly to `main`; always open a PR.

### Versioning
- Follow [SemVer](https://semver.org/): `MAJOR.MINOR.PATCH`.
- The single source of truth for the integration version is `custom_components/qobuz/manifest.json`.
- Also keep `hacs.json` in sync if it contains version constraints.

### Release process
1. **Prepare the release**
   - Update the version in `custom_components/qobuz/manifest.json` (e.g. `0.1.0` → `0.2.0`).
   - Update `README.md` changelog / features if needed.
   - (Optional) Add an entry to a `CHANGELOG.md`.
   - Run tests and lint: `ruff check . && pytest tests/`.

2. **Create the release on GitHub**
   - Push your changes to `main`.
   - Go to the repository on GitHub → **Releases** → **Draft a new release**.
   - Choose a tag version (e.g. `v0.2.0` — the `v` prefix is recommended).
   - Target branch: `main`.
   - Write release notes (what's new, breaking changes, Connect improvements, etc.).
   - Publish the release.

3. **HACS users will see the update**
   - HACS automatically detects new releases and offers updates.
   - Users on the default branch will also get the latest `main` code when they redownload.

### First time / initial publish
- Make sure the GitHub repository is public (or users have a GitHub token configured in HACS for private repos).
- The "Add to Home Assistant" badge in this README points to the correct repository.

Following this process ensures reliable HACS installs and a clean upgrade path for users.

---

**Repository**: https://github.com/Razor5284/HA-Qobuz
