"""Tests for the Qobuz config flow (browser-token auth)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.qobuz.api import QobuzAuthError
from custom_components.qobuz.const import DOMAIN

_VALID_TOKEN = "a" * 64  # realistic-length placeholder


async def _start_flow(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

async def test_form_is_shown(hass, bypass_setup):
    """The first step shows the token-entry form."""
    result = await _start_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_valid_token_creates_entry(hass, bypass_setup):
    """A valid browser token creates a config entry. Password is never stored."""
    with patch("custom_components.qobuz.config_flow.QobuzAPIClient") as mock_cls:
        mock_cls.return_value.validate_token = AsyncMock(
            return_value={"user_id": "u1", "app_id": "950096963"}
        )

        result = await _start_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"email": "me@example.com", "user_auth_token": _VALID_TOKEN, "app_id": ""},
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Qobuz (me@example.com)"
    assert result["data"]["user_id"] == "u1"
    assert result["data"]["token"] == _VALID_TOKEN
    assert result["data"]["app_id"] == "950096963"
    assert "password" not in result["data"]


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

async def test_invalid_token_shows_error(hass, bypass_setup):
    """An expired or invalid token keeps the form open with an error."""
    with patch("custom_components.qobuz.config_flow.QobuzAPIClient") as mock_cls:
        mock_cls.return_value.validate_token = AsyncMock(
            side_effect=QobuzAuthError("token rejected")
        )

        result = await _start_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"email": "me@example.com", "user_auth_token": "badtoken", "app_id": ""},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


async def test_unexpected_exception_shows_unknown_error(hass, bypass_setup):
    """An unexpected exception surfaces as the 'unknown' error."""
    with patch("custom_components.qobuz.config_flow.QobuzAPIClient") as mock_cls:
        mock_cls.return_value.validate_token = AsyncMock(side_effect=RuntimeError("oops"))

        result = await _start_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"email": "x@example.com", "user_auth_token": "tok", "app_id": ""},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "unknown"


# ---------------------------------------------------------------------------
# Reauth
# ---------------------------------------------------------------------------

async def test_reauth_shows_form(hass, bypass_setup, mock_config_entry):
    """Re-auth flow presents the token form again."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": mock_config_entry.entry_id,
        },
        data=mock_config_entry.data,
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
