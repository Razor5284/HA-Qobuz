"""Qobuz sensor platform — account and subscription information."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import QobuzDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Qobuz sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: QobuzDataUpdateCoordinator = data["coordinator"]
    async_add_entities(
        [
            QobuzAccountSensor(coordinator, entry),
            QobuzSubscriptionSensor(coordinator, entry),
        ]
    )


class _QobuzSensorBase(CoordinatorEntity[QobuzDataUpdateCoordinator], SensorEntity):
    """Base class for Qobuz sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: QobuzDataUpdateCoordinator,
        entry: ConfigEntry,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        user = self.coordinator.user_info or {}
        email = self._entry.data.get("email", "")
        name = user.get("display_name") or user.get("login") or email
        sub = user.get("credential", {}).get("description", "")
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"Qobuz — {name}",
            manufacturer="Qobuz",
            model=sub or "Streaming Service",
            entry_type=DeviceEntryType.SERVICE,
        )


class QobuzAccountSensor(_QobuzSensorBase):
    """Sensor showing the Qobuz account display name."""

    _attr_name = "Account"
    _attr_icon = "mdi:account-music"

    def __init__(
        self,
        coordinator: QobuzDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "account")

    @property
    def native_value(self) -> str | None:
        user = self.coordinator.user_info or {}
        return user.get("display_name") or user.get("login")

    @property
    def extra_state_attributes(self) -> dict:
        user = self.coordinator.user_info or {}
        return {
            "email": user.get("email"),
            "country": user.get("country_code"),
            "store": user.get("store"),
        }


class QobuzSubscriptionSensor(_QobuzSensorBase):
    """Sensor showing the active Qobuz subscription plan."""

    _attr_name = "Subscription"
    _attr_icon = "mdi:music-note-plus"

    def __init__(
        self,
        coordinator: QobuzDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, "subscription")

    @property
    def native_value(self) -> str | None:
        user = self.coordinator.user_info or {}
        cred = user.get("credential", {})
        return cred.get("description") or cred.get("label")

    @property
    def extra_state_attributes(self) -> dict:
        user = self.coordinator.user_info or {}
        cred = user.get("credential", {})
        return {
            "offer_type": cred.get("offer_type_label"),
            "parameters": cred.get("parameters"),
        }
