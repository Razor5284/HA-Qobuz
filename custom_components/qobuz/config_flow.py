"""Config flow for the Qobuz integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import QobuzAPIClient, QobuzAuthError
from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN

if TYPE_CHECKING:
    from homeassistant.data_entry_flow import FlowResult

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class QobuzConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Qobuz."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial (and reauth) login step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                session = async_get_clientsession(self.hass)
                api = QobuzAPIClient(session)
                login_data = await api.login(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
            except QobuzAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception during Qobuz login")
                errors["base"] = "unknown"
            else:
                # Build the entry data — never include the raw password
                entry_data = {
                    "email": user_input[CONF_EMAIL],
                    "user_id": login_data["user_id"],
                    "token": login_data["token"],
                    "app_id": login_data["app_id"],
                }

                if self._reauth_entry is not None:
                    # Update the existing entry with fresh credentials
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
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Initiate reauth when the token has expired."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()
