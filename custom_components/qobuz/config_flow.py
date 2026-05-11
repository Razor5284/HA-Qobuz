"""Config flow for Qobuz integration."""

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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                session = async_get_clientsession(self.hass)
                api = QobuzAPIClient(session)
                login_data = await api.login(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )

                # Store token and user info; never store raw password
                return self.async_create_entry(
                    title=f"Qobuz ({user_input[CONF_EMAIL]})",
                    data={
                        "email": user_input[CONF_EMAIL],
                        "user_id": login_data.get("user_id"),
                        "token": login_data.get("token"),
                    },
                )
            except QobuzAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Handle reauth on token expiry."""
        return await self.async_step_user()
