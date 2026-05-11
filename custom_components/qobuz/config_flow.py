"""Config flow and options flow for the Qobuz integration.

Qobuz's login endpoint is reCAPTCHA-protected and cannot be used by automated
clients (this affects all third-party Qobuz tools, not just this integration).
Instead we ask the user to provide a session token extracted directly from
their browser after a normal login at play.qobuz.com.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import QobuzAPIClient, QobuzAuthError
from .const import (
    CONF_APP_ID,
    CONF_EMAIL,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.data_entry_flow import FlowResult

_LOGGER = logging.getLogger(__name__)

CONF_USER_AUTH_TOKEN = "user_auth_token"

_TOKEN_INSTRUCTIONS = (
    "Qobuz requires a session token rather than your password.\n\n"
    "How to get your token:\n"
    "1. Open **https://play.qobuz.com** in your browser and log in.\n"
    "2. Press **F12** → **Application** tab → **Local Storage** → **https://play.qobuz.com**.\n"
    "3. Click the **localuser** row and copy the **token** value.\n"
    "4. Paste it in the 'User Auth Token' field below.\n\n"
    "The token typically lasts several days. You will be prompted to refresh it when it expires."
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_USER_AUTH_TOKEN): str,
        vol.Optional(CONF_APP_ID, default=""): str,
    }
)


class QobuzConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow for Qobuz (browser-token auth)."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> QobuzOptionsFlow:
        return QobuzOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the token entry form and validate on submit."""
        errors: dict[str, str] = {}

        if user_input is not None:
            token: str = user_input[CONF_USER_AUTH_TOKEN].strip()
            app_id: str | None = user_input.get(CONF_APP_ID, "").strip() or None

            try:
                session = async_get_clientsession(self.hass)
                api = QobuzAPIClient(session)
                # Validate token by making a real API call — this also fetches
                # user_id so we don't need to ask for it separately.
                validated = await api.validate_token(token, app_id)
            except QobuzAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception validating Qobuz token")
                errors["base"] = "unknown"
            else:
                entry_data = {
                    CONF_EMAIL: user_input[CONF_EMAIL],
                    "user_id": validated["user_id"],
                    "token": token,
                    "app_id": validated["app_id"],
                }

                if self._reauth_entry is not None:
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry, data=entry_data
                    )
                    await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

                return self.async_create_entry(
                    title=f"Qobuz ({user_input[CONF_EMAIL]})",
                    data=entry_data,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            description_placeholders={"instructions": _TOKEN_INSTRUCTIONS},
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Prompt for a fresh token when the current one expires."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()


class QobuzOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Qobuz — adjustable polling and advanced settings."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the options form."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._entry.options.get(
            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_POLL_INTERVAL, default=current_interval): vol.All(
                    int, vol.Range(min=10, max=300)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
