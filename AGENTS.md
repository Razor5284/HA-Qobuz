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
