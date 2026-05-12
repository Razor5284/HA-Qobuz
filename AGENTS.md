# AGENTS.md

## Cursor Cloud specific instructions

This is a Python-only Home Assistant custom integration (no Docker, no database, no frontend build).

### Environment

- **Python 3.13** is required (the venv lives at `/workspace/.venv`).
- Activate with: `source /workspace/.venv/bin/activate`
- All runtime and dev dependencies are in `requirements-dev.txt`.

### Key commands

| Task | Command |
|------|---------|
| Lint | `make lint` (runs `ruff check .`) |
| Test | `make test` (runs `pytest tests/ -v --tb=short`) |
| Manual API test | `QOBUZ_TOKEN=<token> make test-api` |

### Notes

- There is no build step; the integration is pure Python.
- The protobuf generated files (`custom_components/qobuz/connect/generated/*_pb2.py`) are already committed — no `protoc` compilation needed unless `.proto` files change.
- Tests use `pytest-homeassistant-custom-component` which provides a full HA test harness (mocked core). No running HA instance is needed to run tests.
- The `Makefile` also has `deploy-local` and `deploy-ssh` targets for deploying to a real HA instance, but those require a live HA installation and are not needed for development/testing in this environment.

---

## Routine workflow (all agents)

1. **Branch:** Implement on a feature branch off `main` (for Cursor Cloud automation, branches are often named `cursor/<topic>-<suffix>`; use **lowercase** names).
2. **Implement** with focused diffs; match existing style and imports in `custom_components/qobuz/`.
3. **Verify:** Run `make lint` and `make test` before considering work complete. Fix new failures you introduce; note pre-existing flakes separately if needed.
4. **Ship to main:** Open a PR against `main`, get review/merge as per repo policy.
5. **Protobuf:** If you edit `.proto` files, regenerate `*_pb2.py`, commit them, and ensure imports still work (payload vs queue modules — see README / connect code for patterns).

---

## Versioning

- **User-visible version:** `custom_components/qobuz/manifest.json` → `"version"` (semver `0.x.y`). HACS and HA use this.
- **Connect client string:** `custom_components/qobuz/connect/client.py` → `INTEGRATION_VERSION` (same `0.x.y` as the manifest for releases, so device/software strings in QConnect match the published integration).

Bump both when cutting a release.

---

## Release pattern

When asked to **release** after changes are on `main`:

1. **Changelog:** Add a **`vX.Y.Z`** bullet block at the **top** of the “Changelog” section in `README.md` (newest first). Summarize user-visible fixes and any breaking or operational notes.
2. **Commit:** Push the README update to `main` if it is not already included in the release commit.
3. **Git tag:** Create an **annotated** tag on the commit that should ship (usually current `main`):

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z: <short summary>"
   git push origin vX.Y.Z
   ```

4. **GitHub Release:** Create a release for that tag (UI or `gh release create vX.Y.Z --title "…" --notes "…"`) so users and HACS have a clear artifact. Link the merged PR in the release notes when relevant.

Do **not** change unrelated documentation files unless the task explicitly asks for them.

---

## Quality and testing expectations

- **Lint:** `make lint` must pass for merged work.
- **Tests:** `make test` should pass. There has been an occasional teardown **`verify_cleanup`** assertion involving a Home Assistant background thread in `test_config_flow`; if it appears without code changes in that area, treat it as environmental until proven otherwise.
- **Manual checks:** Qobuz API behaviour can be exercised with `QOBUZ_TOKEN=… make test-api` when changing `api.py` or token flows.

---

## Integration-specific reminders

- **Qobuz Connect:** WebSocket + protobuf; nested assignments require **`CopyFrom`** (protobuf 5+). Do not schedule **`hass.async_create_task`** from arbitrary threads — use **`loop.call_soon_threadsafe`** (or HA-documented equivalents) when reacting from dispatcher/worker paths (see `media_player.py` Connect callback).
- **Imports:** Controller payload messages often live in **`qconnect_payload_pb2`**; only some symbols are re-exported from `connect/generated/__init__.py`. If an import fails, import from the correct `*_pb2` module or add a narrow export to `__init__.py`.
- **REST `getState`:** Often returns **503**; the coordinator is designed to fall back to Connect when REST is idle.

---

## References

- Changelog: `README.md` (section near bottom).
- Connect design: `docs/adr/0001-qobuz-connect-approach.md`, `docs/adr/0002-phase3-qconnect-controller.md`.
- Upstream protocol reference used in the past: [qonductor](https://github.com/nickblt/qonductor) (QConnect controller patterns).
