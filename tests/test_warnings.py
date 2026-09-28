"""Avisos meteorológicos: sensores de nivel, contadores y acción `get_warnings`.

Respuesta real de Muxía (2026-09-27): dos avisos amarillos el martes 29, racha
máxima de viento de 12 a 18 h y lluvia en 12 horas de 12 a 24 h.
"""

from datetime import datetime

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceNotSupported
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.meteogal.api import WeatherWarning
from custom_components.meteogal.api.client import TIMEZONE
from custom_components.meteogal.const import DOMAIN
from custom_components.meteogal.sensor import WarningLevelSensor
from custom_components.meteogal.warnings import (
    active,
    highest_level,
    next_change,
    sort_warnings,
    upcoming,
)

from .api.conftest import SANTIAGO, WARNINGS, load, mock_meteogalicia

LEVEL = "sensor.santiago_de_compostela_warning_level"
UPCOMING_LEVEL = "sensor.santiago_de_compostela_upcoming_warning_level"
ACTIVE_COUNT = "sensor.santiago_de_compostela_active_warnings"
UPCOMING_COUNT = "sensor.santiago_de_compostela_upcoming_warnings"


def at(day: int, hour: int) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=TIMEZONE)


def warning(id_: int, level: int, start: datetime, end: datetime, type_id=8):
    return WeatherWarning(id=id_, type_id=type_id, level=level, start=start, end=end)


@pytest.fixture(autouse=True)
def services(aioclient_mock) -> None:
    # Los avisos de Muxía para la ubicación de Santiago; el resto, Santiago.
    aioclient_mock.get(
        WARNINGS,
        params={"idConcello": SANTIAGO, "dia": -1},
        json=load("jsonAvisosConcellos_15053.json"),
    )
    mock_meteogalicia(aioclient_mock)


async def setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="MeteoGal",
        data={},
        subentries_data=[
            ConfigSubentryData(
                subentry_type="location",
                title="Santiago de Compostela",
                data={
                    "latitude": 42.8805,
                    "longitude": -8.5456,
                    "concello_id": SANTIAGO,
                    "station_id": None,
                },
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def move_to(hass: HomeAssistant, freezer, when: str) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.freeze_time("2026-09-29T10:00:00+02:00")
async def test_warnings_through_the_day(hass: HomeAssistant, freezer) -> None:
    entry = await setup(hass)
    registry = er.async_get(hass)
    for entity_id in (ACTIVE_COUNT, UPCOMING_COUNT):
        registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    # 10:00: los dos avisos están emitidos pero aún no empezaron.
    assert hass.states.get(LEVEL).state == "none"
    assert hass.states.get(LEVEL).attributes.get("type") is None
    upcoming_level = hass.states.get(UPCOMING_LEVEL)
    assert upcoming_level.state == "yellow"
    # A igual nivel, el principal es el que acaba antes: el viento (18 h).
    assert upcoming_level.attributes["type"] == "wind_gust"
    assert upcoming_level.attributes["level"] == "yellow"
    assert upcoming_level.attributes["start"] == "2026-09-29T12:00:00+02:00"
    assert upcoming_level.attributes["end"] == "2026-09-29T18:00:00+02:00"
    assert upcoming_level.attributes["warning_id"] == 815130500
    assert hass.states.get(ACTIVE_COUNT).state == "0"
    assert hass.states.get(UPCOMING_COUNT).state == "2"

    # 12:00 en punto: empiezan los dos.
    await move_to(hass, freezer, "2026-09-29T12:00:00+02:00")
    level = hass.states.get(LEVEL)
    assert level.state == "yellow"
    assert level.attributes["type"] == "wind_gust"
    assert hass.states.get(UPCOMING_LEVEL).state == "none"
    assert hass.states.get(ACTIVE_COUNT).state == "2"

    # 18:00 en punto: acaba el viento, sigue la lluvia.
    await move_to(hass, freezer, "2026-09-29T18:00:00+02:00")
    level = hass.states.get(LEVEL)
    assert level.state == "yellow"
    assert level.attributes["type"] == "rain_12h"
    assert hass.states.get(ACTIVE_COUNT).state == "1"

    # Medianoche: sin avisos.
    await move_to(hass, freezer, "2026-09-30T00:00:00+02:00")
    assert hass.states.get(LEVEL).state == "none"
    assert hass.states.get(ACTIVE_COUNT).state == "0"


@pytest.mark.freeze_time("2026-09-29T11:59:00+02:00")
async def test_change_on_time_without_new_data(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    await setup(hass)
    calls = aioclient_mock.call_count

    # Un minuto después (lejos del siguiente refresco): el estado cambia solo.
    await move_to(hass, freezer, "2026-09-29T12:00:00+02:00")

    assert hass.states.get(LEVEL).state == "yellow"
    assert aioclient_mock.call_count == calls


@pytest.mark.freeze_time("2026-09-29T13:00:00+02:00")
async def test_get_warnings_action(hass: HomeAssistant) -> None:
    await setup(hass)

    response = await hass.services.async_call(
        DOMAIN,
        "get_warnings",
        target={"entity_id": LEVEL},
        blocking=True,
        return_response=True,
    )

    assert response == {
        LEVEL: {
            "warnings": [
                {
                    "type": "wind_gust",
                    "level": "yellow",
                    "start": "2026-09-29T12:00:00+02:00",
                    "end": "2026-09-29T18:00:00+02:00",
                    "warning_id": 815130500,
                    "active": True,
                },
                {
                    "type": "rain_12h",
                    "level": "yellow",
                    "start": "2026-09-29T12:00:00+02:00",
                    "end": "2026-09-30T00:00:00+02:00",
                    "warning_id": 1360271719,
                    "active": True,
                },
            ]
        }
    }


@pytest.mark.freeze_time("2026-09-27T12:00:00+02:00")
async def test_no_warnings(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        WARNINGS,
        params={"idConcello": SANTIAGO, "dia": -1},
        json=load("jsonAvisosConcellos_unknown.json"),
    )
    mock_meteogalicia(aioclient_mock)
    await setup(hass)

    assert hass.states.get(LEVEL).state == "none"
    assert hass.states.get(UPCOMING_LEVEL).state == "none"
    assert hass.states.get(LEVEL).attributes.get("type") is None


@pytest.mark.freeze_time("2026-09-29T13:00:00+02:00")
async def test_failed_update_keeps_warnings(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await setup(hass)

    aioclient_mock.clear_requests()
    aioclient_mock.get(WARNINGS, params={"idConcello": SANTIAGO, "dia": -1}, status=503)
    mock_meteogalicia(aioclient_mock)
    await entry.runtime_data.locations[next(iter(entry.subentries))].async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(LEVEL).state == "yellow"


@pytest.mark.freeze_time("2026-09-29T13:00:00+02:00")
async def test_entities(hass: HomeAssistant) -> None:
    entry = await setup(hass)
    (subentry_id,) = entry.subentries
    registry = er.async_get(hass)

    weather = registry.async_get("weather.santiago_de_compostela")
    for entity_id, key, enabled in (
        (LEVEL, "warning_level", True),
        (UPCOMING_LEVEL, "upcoming_warning_level", True),
        (ACTIVE_COUNT, "active_warnings", False),
        (UPCOMING_COUNT, "upcoming_warnings", False),
    ):
        entity = registry.async_get(entity_id)
        assert entity.unique_id == f"{subentry_id}_{key}"
        assert entity.device_id == weather.device_id
        assert (entity.disabled_by is None) is enabled
    level = hass.states.get(LEVEL)
    assert level.attributes["device_class"] == "enum"
    assert level.attributes["options"] == ["none", "yellow", "orange", "red"]
    # Los atributos no se guardan en la base de datos.
    assert WarningLevelSensor._unrecorded_attributes == frozenset({MATCH_ALL})


def test_sorting_and_levels() -> None:
    now = at(29, 13)
    wind = warning(1, 1, at(29, 12), at(29, 18))
    rain = warning(2, 1, at(29, 12), at(30, 0), type_id=4)
    red_waves = warning(3, 3, at(29, 12), at(30, 12), type_id=10)
    tomorrow = warning(4, 2, at(30, 6), at(30, 12))

    # El más grave primero, aunque acabe más tarde.
    assert sort_warnings([wind, rain, red_waves]) == [red_waves, wind, rain]
    assert active([wind, rain, red_waves, tomorrow], now) == [red_waves, wind, rain]
    assert upcoming([wind, tomorrow], now) == [tomorrow]
    assert highest_level([wind, red_waves]) == "red"
    assert highest_level([]) == "none"
    assert next_change([wind, rain, tomorrow], now) == at(29, 18)
    assert next_change([], now) is None


@pytest.mark.freeze_time("2026-09-29T13:00:00+02:00")
async def test_get_warnings_only_on_warning_level(hass: HomeAssistant) -> None:
    """Un sensor que no es de nivel de aviso da el error estándar de HA."""
    entry = await setup(hass)
    er.async_get(hass).async_update_entity(ACTIVE_COUNT, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceNotSupported):
        await hass.services.async_call(
            DOMAIN,
            "get_warnings",
            target={"entity_id": ACTIVE_COUNT},
            blocking=True,
            return_response=True,
        )
