"""Pytest configuration and shared fixtures for the Qobuz integration test suite."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `custom_components` is importable
# both locally and in CI before any test modules are collected.
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.qobuz.const import DOMAIN

# Explicitly activate the pytest-homeassistant-custom-component plugin so HA's
# integration loader can discover custom components during tests.
pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the local custom_components folder visible to HA's loader in every test."""
    yield


@pytest.fixture
def bypass_setup():
    """Prevent HA from running setup/teardown logic (for config flow tests).

    Config flow tests verify the flow itself; they shouldn't exercise the full
    integration setup, which would require a live Qobuz account or extensive
    mocking of the coordinator. Patching both directions keeps the HA test
    harness happy during teardown too.
    """
    with (
        patch("custom_components.qobuz.async_setup_entry", return_value=True),
        patch("custom_components.qobuz.async_unload_entry", return_value=True),
    ):
        yield


@pytest.fixture
def mock_api():
    """Return a MagicMock that stands in for QobuzAPIClient.

    All async methods are AsyncMock and return sensible fixtures so tests
    that need a running coordinator don't hit the network.
    """
    api = MagicMock()
    api.is_authenticated = True
    api.get_playlists = AsyncMock(
        return_value=[{"id": "p1", "name": "Test Playlist", "image": {}}]
    )
    api.get_current_playback = AsyncMock(return_value={"is_playing": False})
    api.get_playlist_tracks = AsyncMock(return_value=[])
    api.play_track = AsyncMock()
    return api


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a MockConfigEntry pre-populated with safe test data."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={"email": "test@example.com", "user_id": "u1", "token": "t1"},
        entry_id="test_entry",
    )


def load_fixture(name: str) -> dict:
    """Load a JSON fixture file from tests/fixtures/."""
    path = Path(__file__).parent / "fixtures" / name
    return json.loads(path.read_text(encoding="utf-8"))
