"""Tests for Qobuz sensor entities."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.qobuz.sensor import QobuzAccountSensor, QobuzSubscriptionSensor


def _make_sensor_cls(cls, user_info):
    coordinator = MagicMock()
    coordinator.user_info = user_info
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {"email": "test@example.com"}

    sensor = cls.__new__(cls)
    sensor.coordinator = coordinator
    sensor._entry = entry
    return sensor


async def test_account_sensor_display_name(hass):
    sensor = _make_sensor_cls(
        QobuzAccountSensor,
        {"display_name": "Ryan", "email": "r@example.com", "country_code": "GB", "store": "gb"},
    )
    assert sensor.native_value == "Ryan"
    attrs = sensor.extra_state_attributes
    assert attrs["email"] == "r@example.com"
    assert attrs["country"] == "GB"


async def test_account_sensor_falls_back_to_login(hass):
    sensor = _make_sensor_cls(QobuzAccountSensor, {"login": "rlogin"})
    assert sensor.native_value == "rlogin"


async def test_subscription_sensor(hass):
    sensor = _make_sensor_cls(
        QobuzSubscriptionSensor,
        {"credential": {"description": "Sublime", "offer_type_label": "Annual"}},
    )
    assert sensor.native_value == "Sublime"
    assert sensor.extra_state_attributes["offer_type"] == "Annual"


async def test_subscription_sensor_none(hass):
    sensor = _make_sensor_cls(QobuzSubscriptionSensor, {})
    assert sensor.native_value is None
