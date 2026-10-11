"""Aviso de reparación cuando la estación de calidad del aire deja de enviar datos.

Respuestas del 2026-09-29: el ICA de Torre Hércules (14) es de las 08:00 locales.
"""

from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meteogal.const import DOMAIN

from .test_air import setup

# Un día y medio después de la última lectura de la estación.
STALE = pytest.mark.freeze_time("2026-10-01T00:00:00+00:00")
RECENT = pytest.mark.freeze_time("2026-09-29T06:30:00+00:00")


def issue_id(entry: MockConfigEntry) -> str:
    (subentry_id,) = entry.subentries
    return f"air_station_stale_{subentry_id}"


@STALE
async def test_issue_when_air_station_stale(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await setup(hass, aioclient_mock)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id(entry))
    assert issue is not None
    assert issue.is_fixable
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "air_station_stale"
    assert issue.translation_placeholders == {
        "location": "A Coruña",
        "station": "Torre Hércules",
        "since": "2026-09-29 08:00",
    }


@RECENT
async def test_no_issue_when_air_station_recent(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await setup(hass, aioclient_mock)

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id(entry)) is None


@STALE
async def test_no_issue_without_air_station(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await setup(hass, aioclient_mock, air_station_id=None)

    (subentry_id,) = entry.subentries
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"air_station_stale_{subentry_id}"
    )
    assert issue is None


async def start_fix(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    assert await async_setup_component(hass, "repairs", {})
    manager = repairs_flow_manager(hass)
    assert manager is not None
    return await manager.async_init(DOMAIN, data={"issue_id": issue_id(entry)})


@STALE
async def test_fix_choose_other_air_station(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await setup(hass, aioclient_mock)

    result = await start_fix(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"]["station"] == "Torre Hércules"
    (key,) = result["data_schema"].schema
    assert key == "air_station_id"
    # Propone la más cercana con dato, que no es la actual.
    suggested = key.description["suggested_value"]
    assert suggested != "14"

    result = await repairs_flow_manager(hass).async_configure(
        result["flow_id"], {"air_station_id": suggested}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.data["air_station_id"] == int(suggested)
    assert subentry.data["station_id"] is None  # la meteorológica no se toca


@STALE
async def test_fix_no_air_station(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await setup(hass, aioclient_mock)

    result = await start_fix(hass, entry)
    result = await repairs_flow_manager(hass).async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.data["air_station_id"] is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id(entry)) is None


@STALE
async def test_issue_removed_with_the_station(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Al reconfigurar la ubicación sin estación de aire, el aviso se limpia."""
    entry = await setup(hass, aioclient_mock)
    issue = issue_id(entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue) is not None

    (subentry,) = entry.subentries.values()
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, "air_station_id": None}
    )
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue) is None


@STALE
async def test_remove_entry_removes_air_issue(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await setup(hass, aioclient_mock)
    issue = issue_id(entry)

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue) is None
