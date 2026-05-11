"""Tests for the Qobuz config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.qobuz.api import QobuzAuthError
from custom_components.qobuz.const import DOMAIN

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _start_flow(hass):
    """Initialise the user flow and return the first result (a FORM)."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

async def test_form_is_shown(hass, bypass_setup):
    """The first step of the flow should display a login form."""
    result = await _start_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_successful_login_creates_entry(hass, bypass_setup):
    """Valid credentials should create a config entry without storing the password."""
    with patch(
        "custom_components.qobuz.config_flow.QobuzAPIClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            return_value={"user_id": "u1", "token": "tok1"}
        )

        result = await _start_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"email": "me@example.com", "password": "s3cr3t"},
        )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Qobuz (me@example.com)"
    assert result["data"]["email"] == "me@example.com"
    assert result["data"]["user_id"] == "u1"
    assert result["data"]["token"] == "tok1"
    # Password must never be persisted
    assert "password" not in result["data"]


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

async def test_invalid_credentials_show_error(hass, bypass_setup):
    """Wrong credentials should show an error and keep the form open."""
    with patch(
        "custom_components.qobuz.config_flow.QobuzAPIClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=QobuzAuthError("bad credentials")
        )

        result = await _start_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"email": "bad@example.com", "password": "wrong"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


async def test_unexpected_exception_shows_unknown_error(hass, bypass_setup):
    """An unexpected exception should surface as the 'unknown' error."""
    with patch(
        "custom_components.qobuz.config_flow.QobuzAPIClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(side_effect=RuntimeError("boom"))

        result = await _start_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"email": "x@example.com", "password": "y"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "unknown"


# ---------------------------------------------------------------------------
# Reauth
# ---------------------------------------------------------------------------

async def test_reauth_shows_login_form(hass, bypass_setup, mock_config_entry):
    """Re-auth flow should present the login form again."""
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
