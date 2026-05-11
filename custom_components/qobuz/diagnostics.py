"""Diagnostics support for Qobuz integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

TO_REDACT = {"token", "email", "user_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator = data.get("coordinator")

    diagnostics: dict[str, Any] = {
        "entry": async_redact_data(entry.data, TO_REDACT),
        "options": entry.options,
        "coordinator_last_update_success": getattr(coordinator, "last_update_success", None),
    }

    if coordinator and hasattr(coordinator, "data"):
        diagnostics["data"] = async_redact_data(coordinator.data or {}, TO_REDACT)

    return diagnostics
