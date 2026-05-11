"""Tests for Qobuz config flow."""

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.qobuz.const import DOMAIN


async def test_user_flow(hass, mock_api):
    """Test successful user flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"email": "test@example.com", "password": "secret"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Qobuz (test@example.com)"


async def test_reauth(hass, mock_config_entry: MockConfigEntry):
    """Test reauth flow."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": mock_config_entry.entry_id},
        data=mock_config_entry.data,
    )
    assert result["type"] == FlowResultType.FORM
