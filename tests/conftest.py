"""Pytest configuration and fixtures for Qobuz integration tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Add the project root so `custom_components` is importable in CI and local runs
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.qobuz.const import DOMAIN


@pytest.fixture
def mock_api():
    """Mock Qobuz API client."""
    with patch("custom_components.qobuz.api.QobuzAPIClient") as mock:
        instance = mock.return_value
        instance.login = AsyncMock(return_value={"user_id": "u1", "token": "t1"})
        instance.get_playlists = AsyncMock(return_value=[{"id": "p1", "name": "Test"}])
        instance.get_current_playback = AsyncMock(return_value={"is_playing": False})
        instance.is_authenticated = True
        yield instance


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={"email": "test@example.com", "user_id": "u1", "token": "t1"},
        entry_id="test_entry",
    )


def load_fixture(name: str) -> dict:
    """Load JSON fixture."""
    path = Path(__file__).parent / "fixtures" / name
    return json.loads(path.read_text(encoding="utf-8"))
