"""Aviso de reparación cuando la estación deja de enviar datos.

Marroxo (10056), lectura real del 2026-09-28: su última lectura es del
2026-09-19 04:50Z.
"""

import re

import aiohttp
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meteogal.const import DOMAIN

from .api.conftest import STATION_NOW, STATIONS, load, mock_meteogalicia

pytestmark = pytest.mark.freeze_time("2026-09-28T16:00:00+00:00")

MARROXO = 10056


def location(station_id: int | None) -> ConfigSubentryData:
    return ConfigSubentryData(
        subentry_type="location",
        title="A Coruña",
        data={
            "latitude": 43.3665,
            "longitude": -8.3735,
            "concello_id": 15030,
            "station_id": station_id,
            "station_weather": True,
            "camera_id": None,
        },
        unique_id=None,
    )


@pytest.fixture(autouse=True)
def meteogalicia(aioclient_mock) -> None:
    # Antes que las demás: la primera respuesta que encaja es la que vale.
    aioclient_mock.get(
        re.compile(re.escape(STATION_NOW) + rf"\?idEst={MARROXO}"),
        json=load(f"ultimos10minEstacionsMeteo_{MARROXO}.json"),
    )
    mock_meteogalicia(aioclient_mock)
    mock_meteogalicia(aioclient_mock, concello=15030)


async def setup(hass: HomeAssistant, station_id: int | None) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Madrid")
    entry = MockConfigEntry(
        domain=DOMAIN, title="MeteoGal", data={}, subentries_data=[location(station_id)]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def issue_id(entry: MockConfigEntry) -> str:
    (subentry_id,) = entry.subentries
    return f"station_stale_{subentry_id}"


async def test_issue_when_station_stale(hass: HomeAssistant) -> None:
    entry = await setup(hass, MARROXO)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id(entry))
    assert issue is not None
    assert issue.is_fixable
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "station_stale"
    assert issue.translation_placeholders == {
        "location": "A Coruña",
        "station": "Marroxo",
        "since": "2026-09-19 06:50",
    }


async def test_no_issue_when_station_recent(hass: HomeAssistant) -> None:
    """Coruña-Dique, lectura del 2026-09-27 21:40Z: menos de un día."""
    entry = await setup(hass, 14000)

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id(entry)) is None


async def start_fix(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    assert await async_setup_component(hass, "repairs", {})
    manager = repairs_flow_manager(hass)
    assert manager is not None
    return await manager.async_init(DOMAIN, data={"issue_id": issue_id(entry)})


async def test_fix_choose_other_station(hass: HomeAssistant) -> None:
    entry = await setup(hass, MARROXO)

    result = await start_fix(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"]["station"] == "Marroxo"
    # Propone la más cercana que envía datos: Coruña-Dique.
    (key,) = result["data_schema"].schema
    assert key.description == {"suggested_value": "14000"}

    manager = repairs_flow_manager(hass)
    result = await manager.async_configure(result["flow_id"], {"station_id": "14000"})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.data["station_id"] == 14000
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id(entry)) is None


async def test_fix_no_station(hass: HomeAssistant) -> None:
    entry = await setup(hass, MARROXO)

    result = await start_fix(hass, entry)
    result = await repairs_flow_manager(hass).async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.data["station_id"] is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id(entry)) is None


async def test_fix_cannot_connect(hass: HomeAssistant, aioclient_mock) -> None:
    """Sin lista de estaciones, enviar reintenta y no cambia nada."""
    entry = await setup(hass, MARROXO)
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATIONS, exc=aiohttp.ClientConnectionError())

    result = await start_fix(hass, entry)
    assert result["errors"] == {"base": "cannot_connect"}
    result = await repairs_flow_manager(hass).async_configure(result["flow_id"], {})

    assert result["errors"] == {"base": "cannot_connect"}
    (subentry,) = entry.subentries.values()
    assert subentry.data["station_id"] == MARROXO


async def test_fix_location_removed(hass: HomeAssistant) -> None:
    entry = await setup(hass, MARROXO)
    issue = issue_id(entry)
    await start_fix(hass, entry)  # carga repairs
    (subentry_id,) = entry.subentries
    # Se abre el aviso y, antes de arreglarlo, se borra la ubicación: el aviso se
    # limpia al recargar. Se vuelve a crear a mano para probar el flujo.
    hass.config_entries.async_remove_subentry(entry, subentry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue) is None
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="station_stale",
        data={"entry_id": entry.entry_id, "subentry_id": subentry_id},
    )

    result = await repairs_flow_manager(hass).async_init(
        DOMAIN, data={"issue_id": issue}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "location_removed"


async def test_remove_entry_removes_issue(hass: HomeAssistant) -> None:
    entry = await setup(hass, MARROXO)
    issue = issue_id(entry)

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue) is None
