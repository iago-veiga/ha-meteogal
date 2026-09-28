"""Estación y cámara de una ubicación, con lecturas reales del 2026-09-27.

- Coruña-Dique (14000), 21:40Z: mide viento, presión y temperatura del agua, pero
  esa lectura trae el viento todo a cero (fallo del dato, no calma).
- Santiago-EOAS (10124), 21:30Z: la estación más completa, con viento válido.
"""

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meteogal.const import DOMAIN

from .api.conftest import (
    STATION_DAY,
    STATION_NOW,
    load,
    mock_meteogalicia,
)

WEATHER = "weather.a_coruna"
PREFIX = "sensor.a_coruna_"

pytestmark = pytest.mark.freeze_time("2026-09-27T21:45:00+00:00")


def location(**extra) -> ConfigSubentryData:
    return ConfigSubentryData(
        subentry_type="location",
        title="A Coruña",
        data={
            "latitude": 43.3665,
            "longitude": -8.3735,
            "concello_id": 15030,
            "station_id": 14000,
            "station_weather": True,
            "camera_id": "Corunha",
            **extra,
        },
        unique_id=None,
    )


async def setup(hass: HomeAssistant, **extra) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="MeteoGal", data={}, subentries_data=[location(**extra)]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture(autouse=True)
def services(aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)
    mock_meteogalicia(aioclient_mock, concello=15030)


def state(hass: HomeAssistant, key: str) -> str | None:
    current = hass.states.get(PREFIX + key)
    return current.state if current else None


async def test_station_sensors(hass: HomeAssistant) -> None:
    await setup(hass)

    assert state(hass, "temperature") == "17.03"
    assert state(hass, "humidity") == "98.0"
    assert state(hass, "rain_last_10_min") == "0.0"
    assert state(hass, "rain_today") == "6.4"
    assert state(hass, "pressure") == "1016.93"
    assert state(hass, "water_temperature") == "17.062"
    # El viento de esa lectura viene todo a cero: dato ausente, no calma.
    assert state(hass, "wind_speed") == "unknown"
    assert state(hass, "wind_gust") == "unknown"


async def test_only_what_the_station_measures(hass: HomeAssistant) -> None:
    await setup(hass)
    registry = er.async_get(hass)

    # Coruña-Dique no mide radiación ni horas de sol: no hay sensor.
    assert registry.async_get(PREFIX + "solar_radiation") is None
    assert registry.async_get(PREFIX + "sunshine_hours_today") is None
    # Lo que mide pero no se mira a diario, desactivado.
    for key in ("wind_direction", "dew_point", "maximum_temperature_today"):
        entity = registry.async_get(PREFIX + key)
        assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION, key
    weather = registry.async_get(WEATHER)
    assert registry.async_get(PREFIX + "temperature").device_id == weather.device_id


async def test_diagnostic(hass: HomeAssistant) -> None:
    await setup(hass)

    updated = hass.states.get(PREFIX + "station_last_reading")
    assert updated.state == "2026-09-27T21:40:00+00:00"
    assert updated.attributes["station_name"] == "Coruña-Dique"
    assert updated.attributes["station_id"] == 14000
    assert 0 < updated.attributes["distance"] < 1
    entity = er.async_get(hass).async_get(PREFIX + "station_last_reading")
    assert entity.entity_category == "diagnostic"


async def test_weather_uses_station(hass: HomeAssistant) -> None:
    await setup(hass)

    weather = hass.states.get(WEATHER).attributes
    # Medido en la estación (la observación del concello da 15,8).
    assert weather["temperature"] == 17.0
    assert weather["humidity"] == 98
    assert weather["pressure"] == 1016.93
    assert weather["dew_point"] == 16.7
    # Sin viento válido en la estación: rumbo de la observación, sin velocidad.
    assert weather["wind_bearing"] == 45.0
    assert "wind_speed" not in weather or weather["wind_speed"] is None
    assert weather.get("wind_gust_speed") is None


async def test_weather_without_station(hass: HomeAssistant) -> None:
    await setup(hass, station_weather=False)

    weather = hass.states.get(WEATHER).attributes
    assert weather["temperature"] == 15.8  # observación del concello
    assert "humidity" not in weather
    # Los sensores de la estación siguen.
    assert state(hass, "temperature") == "17.03"


async def test_weather_wind_from_station(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATION_NOW, json=load("ultimos10minEstacionsMeteo_10124.json"))
    aioclient_mock.get(STATION_DAY, json=load("datosDiariosEstacionsMeteo_10124.json"))
    mock_meteogalicia(aioclient_mock)
    mock_meteogalicia(aioclient_mock, concello=15030)
    reading = load("ultimos10minEstacionsMeteo_10124.json")["listUltimos10min"][0]
    values = {m["codigoParametro"]: m["valor"] for m in reading["listaMedidas"]}

    await setup(hass, station_id=10124)

    weather = hass.states.get(WEATHER).attributes
    assert weather["wind_speed"] == round(values["VV_AVG_10m"] * 3.6, 1)
    assert weather["wind_bearing"] == values["DV_AVG_10m"]
    assert weather["wind_gust_speed"] == round(values["VV_RACHA_10m"] * 3.6, 1)


@pytest.mark.freeze_time("2026-09-27T23:00:00+00:00")
async def test_old_reading_is_ignored(hass: HomeAssistant) -> None:
    # Lectura de las 21:40Z a las 23:00Z: la estación ha dejado de enviar.
    await setup(hass)

    assert state(hass, "temperature") == "unknown"
    assert hass.states.get(WEATHER).attributes["temperature"] == 15.8


async def test_station_down(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATION_NOW, status=503)
    aioclient_mock.get(STATION_DAY, status=503)
    mock_meteogalicia(aioclient_mock)
    mock_meteogalicia(aioclient_mock, concello=15030)

    await setup(hass)

    # Sin datos al arrancar: no se crean todavía (no se sabe qué mide) y la
    # entidad del tiempo sigue con el concello.
    assert er.async_get(hass).async_get(PREFIX + "temperature") is None
    assert hass.states.get(WEATHER).attributes["temperature"] == 15.8


async def test_camera(hass: HomeAssistant) -> None:
    entry = await setup(hass)

    camera = hass.states.get("image.a_coruna_camera")
    assert camera.state == "2026-09-27T23:38:00+02:00"  # hora de la foto
    assert camera.attributes["camera_name"] == "Coruña-Dique"
    (subentry_id,) = entry.subentries
    entity = er.async_get(hass).async_get("image.a_coruna_camera")
    assert entity.unique_id == f"{subentry_id}_camera"


async def test_no_camera(hass: HomeAssistant) -> None:
    await setup(hass, camera_id=None)

    assert hass.states.get("image.a_coruna_camera") is None


@pytest.mark.freeze_time("2026-09-27T22:03:00+00:00")
async def test_after_midnight_without_today_data(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A las 00:03 locales aún no hay datos del día: los sensores de hoy se crean
    igual (por lo que mide la estación) y quedan en «Desconocido»."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATION_NOW, json=load("ultimos10minEstacionsMeteo_14000.json"))
    aioclient_mock.get(STATION_DAY, json={"listDatosDiarios": []})
    mock_meteogalicia(aioclient_mock)
    mock_meteogalicia(aioclient_mock, concello=15030)

    await setup(hass)

    assert state(hass, "rain_today") == "unknown"
    registry = er.async_get(hass)
    assert registry.async_get(PREFIX + "maximum_temperature_today") is not None
    # Coruña-Dique no mide horas de sol: tampoco de hoy.
    assert registry.async_get(PREFIX + "sunshine_hours_today") is None


async def test_camera_saved_with_old_numeric_id(hass: HomeAssistant) -> None:
    """Antes se guardaba el identificador (14000); sigue encontrando la cámara."""
    await setup(hass, camera_id=14000)

    camera = hass.states.get("image.a_coruna_camera")
    assert camera.state == "2026-09-27T23:38:00+02:00"
    assert camera.attributes["camera_name"] == "Coruña-Dique"
