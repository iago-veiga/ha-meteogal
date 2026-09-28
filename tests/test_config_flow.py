"""Tests del flujo de configuración."""

from typing import Any

import aiohttp
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
    ConfigSubentryData,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meteogal.api.client import _parse_stations
from custom_components.meteogal.config_flow import METEOSIX_KEY_URL
from custom_components.meteogal.const import DOMAIN
from custom_components.meteogal.geo import nearest_station

from .api.conftest import (
    METEOSIX_BAD_KEY,
    METEOSIX_DOWN_KEY,
    METEOSIX_FORECAST,
    METEOSIX_KEY,
    STATIONS,
    load,
    mock_meteogalicia,
    mock_meteosix,
)

# Praza do Obradoiro, Santiago de Compostela.
SANTIAGO = {"latitude": 42.8805, "longitude": -8.5456}
# Centro de Vigo.
VIGO = {"latitude": 42.2406, "longitude": -8.7207}
MADRID = {"latitude": 40.4168, "longitude": -3.7038}


@pytest.fixture(autouse=True)
def meteogalicia(aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)
    # Al añadir Vigo o A Coruña se recarga la integración: mismos datos que Santiago.
    for concello in (36057, 15030):
        mock_meteogalicia(aioclient_mock, concello=concello)


def nearest_station_id(location: dict[str, float]) -> int:
    stations = _parse_stations(load("listaEstacionsMeteo.json"))
    station, _ = nearest_station(location["latitude"], location["longitude"], stations)
    return station.id


def suggested(result: dict[str, Any]) -> dict[str, Any]:
    """Valores ya elegidos en el formulario."""
    return {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }


async def start(hass: HomeAssistant, location: dict[str, float]) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"location": location}
    )


async def test_first_install(hass: HomeAssistant) -> None:
    result = await start(hass, SANTIAGO)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {"concello": "Santiago de Compostela"}
    station_id = nearest_station_id(SANTIAGO)
    # Santiago-EOAS no tiene cámara: no se propone ninguna.
    assert suggested(result) == {
        "concello_id": "15078",
        "station_id": str(station_id),
        "station_weather": True,
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], suggested(result)
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "MeteoGal"
    assert result["data"] == {}
    entry = result["result"]
    (subentry,) = entry.subentries.values()
    assert subentry.subentry_type == "location"
    assert subentry.title == "Santiago de Compostela"
    assert dict(subentry.data) == {
        **SANTIAGO,
        "concello_id": 15078,
        "station_id": station_id,
        "station_weather": True,
        "camera_id": None,
    }


async def test_user_corrects_concello_and_skips_station(hass: HomeAssistant) -> None:
    result = await start(hass, SANTIAGO)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"concello_id": "15030"}
    )
    await hass.async_block_till_done()

    (subentry,) = result["result"].subentries.values()
    assert subentry.title == "A Coruña"
    assert subentry.data["concello_id"] == 15030
    assert subentry.data["station_id"] is None


async def test_outside_galicia(hass: HomeAssistant) -> None:
    result = await start(hass, MADRID)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "outside_galicia"}

    # Se puede corregir sin empezar de nuevo.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"location": SANTIAGO}
    )
    assert result["step_id"] == "confirm"


async def test_cannot_connect(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATIONS, exc=aiohttp.ClientConnectionError())

    result = await start(hass, SANTIAGO)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_single_instance(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, data={}).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


@pytest.fixture
async def entry(hass: HomeAssistant) -> MockConfigEntry:
    """MeteoGal ya configurado con Santiago."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="MeteoGal",
        data={},
        subentries_data=[
            ConfigSubentryData(
                subentry_type="location",
                title="Santiago de Compostela",
                data={**SANTIAGO, "concello_id": 15078, "station_id": None},
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_add_location(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "location"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "location"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"location": VIGO}
    )
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {"concello": "Vigo"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], suggested(result)
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Vigo"
    assert result["data"]["concello_id"] == 36057
    assert len(entry.subentries) == 2


async def test_add_same_location(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "location"), context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"location": SANTIAGO}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_location(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    (subentry,) = entry.subentries.values()
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "location"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert result["step_id"] == "location"
    assert suggested(result) == {"location": SANTIAGO}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"location": VIGO}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], suggested(result)
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    updated = entry.subentries[subentry.subentry_id]
    assert updated.title == "Vigo"
    assert updated.data["concello_id"] == 36057


async def test_reconfigure_keeps_station_in_same_concello(
    hass: HomeAssistant,
) -> None:
    stations = _parse_stations(load("listaEstacionsMeteo.json"))
    moved = {"latitude": 42.8780, "longitude": -8.5420}
    # Una estación de Santiago que no sea la más cercana: si no, el test no prueba nada.
    chosen = next(
        s
        for s in stations
        if s.concello == "SANTIAGO DE COMPOSTELA" and s.id != nearest_station_id(moved)
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[
            ConfigSubentryData(
                subentry_type="location",
                title="Santiago de Compostela",
                data={**SANTIAGO, "concello_id": 15078, "station_id": chosen.id},
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    (subentry,) = entry.subentries.values()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "location"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    # Se mueve el punto unos cientos de metros, dentro de Santiago.
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"location": moved}
    )

    assert suggested(result)["station_id"] == str(chosen.id)


async def test_add_location_when_disabled(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await hass.config_entries.async_unload(entry.entry_id)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "location"), context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_loaded"


async def reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, Any]:
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    return result


async def test_add_api_key(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock
) -> None:
    mock_meteosix(aioclient_mock)
    result = await reconfigure(hass, entry)
    assert result["description_placeholders"] == {"url": METEOSIX_KEY_URL}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": f"  {METEOSIX_KEY} "}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {"api_key": METEOSIX_KEY}
    # Las ubicaciones no se tocan.
    assert [s.title for s in entry.subentries.values()] == ["Santiago de Compostela"]
    assert entry.state is ConfigEntryState.LOADED


@pytest.mark.parametrize(
    ("api_key", "errors"),
    [
        (METEOSIX_BAD_KEY, {"api_key": "invalid_api_key"}),
        (METEOSIX_DOWN_KEY, {"base": "cannot_connect_meteosix"}),
    ],
    ids=["invalid", "cannot_connect"],
)
async def test_api_key_errors(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock,
    api_key: str,
    errors: dict[str, str],
) -> None:
    mock_meteosix(aioclient_mock)
    result = await reconfigure(hass, entry)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": api_key}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors
    assert entry.data == {}

    # Se puede corregir sin empezar de nuevo.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": METEOSIX_KEY}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {"api_key": METEOSIX_KEY}


@pytest.mark.parametrize("user_input", [{}, {"api_key": ""}, {"api_key": "  "}])
async def test_remove_api_key(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock, user_input: dict
) -> None:
    hass.config_entries.async_update_entry(entry, data={"api_key": METEOSIX_KEY})
    await hass.async_block_till_done()
    result = await reconfigure(hass, entry)
    # La clave guardada ya viene escrita (el campo la oculta).
    assert suggested(result) == {"api_key": METEOSIX_KEY}
    calls = aioclient_mock.call_count

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {}
    # Quitarla no necesita preguntar a MeteoSIX (sí recarga los datos públicos).
    assert not any(
        str(url).startswith(METEOSIX_FORECAST)
        for _, url, _, _ in aioclient_mock.mock_calls[calls:]
    )
    assert entry.state is ConfigEntryState.LOADED


async def test_reauth_new_key(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock
) -> None:
    mock_meteosix(aioclient_mock)
    hass.config_entries.async_update_entry(entry, data={"api_key": METEOSIX_BAD_KEY})
    await hass.async_block_till_done()

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    # La clave que ya no vale no se vuelve a mostrar.
    assert suggested(result) == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": METEOSIX_KEY}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {"api_key": METEOSIX_KEY}


async def test_reauth_remove_key(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    hass.config_entries.async_update_entry(entry, data={"api_key": METEOSIX_BAD_KEY})
    await hass.async_block_till_done()

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["reason"] == "reauth_successful"
    assert entry.data == {}


# Junto al puerto de A Coruña: la estación más cercana, Coruña-Dique, tiene cámara.
DIQUE = {"latitude": 43.3665, "longitude": -8.3735}


async def test_station_camera_suggested(hass: HomeAssistant) -> None:
    result = await start(hass, DIQUE)

    assert suggested(result) == {
        "concello_id": "15030",
        "station_id": "14000",
        "station_weather": True,
        "camera_id": "Corunha",
    }
    # Las cámaras, de la más cercana a la más lejana, con su concello y distancia.
    cameras = next(
        key for key in result["data_schema"].schema if str(key) == "camera_id"
    )
    options = result["data_schema"].schema[cameras].config["options"]
    assert options[0]["label"] == "Coruña-Dique (A Coruña) · 0.2 km"
    assert len(options) == 33


async def test_station_weather_off_and_other_camera(hass: HomeAssistant) -> None:
    result = await start(hass, DIQUE)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "concello_id": "15030",
            "station_id": "14000",
            "station_weather": False,
            "camera_id": "Ribadeoporto",
        },
    )
    await hass.async_block_till_done()

    (subentry,) = result["result"].subentries.values()
    assert subentry.data["station_weather"] is False
    assert subentry.data["camera_id"] == "Ribadeoporto"


async def test_reconfigure_keeps_camera_and_station_weather(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="MeteoGal",
        data={},
        subentries_data=[
            ConfigSubentryData(
                subentry_type="location",
                title="A Coruña",
                data={
                    **DIQUE,
                    "concello_id": 15030,
                    "station_id": 14000,
                    "station_weather": False,
                    "camera_id": 10900,  # como se guardaba antes: el identificador
                },
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    (subentry_id,) = entry.subentries

    result = await entry.start_subentry_reconfigure_flow(hass, subentry_id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"location": DIQUE}
    )

    assert suggested(result)["station_weather"] is False
    assert suggested(result)["camera_id"] == "Ribadeoporto"
