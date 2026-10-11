"""Estación y cámara de una ubicación, con lecturas reales del 2026-09-27.

- Coruña-Dique (14000), 21:40Z: mide viento, presión y temperatura del agua, pero
  esa lectura trae el viento todo a cero (fallo del dato, no calma).
- Santiago-EOAS (10124), 21:30Z: la estación más completa, con viento válido.
"""

from datetime import UTC, date, datetime

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meteogal.api import StationDay, StationHour
from custom_components.meteogal.api.client import TIMEZONE, _parse_station_readings
from custom_components.meteogal.const import DOMAIN
from custom_components.meteogal.station import (
    NO_DATA,
    NO_PRESSURE,
    NO_WIND,
    local_day,
    station_gaps,
)

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
    """A las 00:03 locales aún no hay datos del día ni ninguna hora entera: los
    sensores de hoy se crean igual (por lo que mide la estación) y la lluvia de hoy
    es 0, no «Desconocido»."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATION_NOW, json=load("ultimos10minEstacionsMeteo_14000.json"))
    aioclient_mock.get(STATION_DAY, json={"listDatosDiarios": []})
    mock_meteogalicia(aioclient_mock)
    mock_meteogalicia(aioclient_mock, concello=15030)

    await setup(hass)

    assert state(hass, "rain_today") == "0.0"
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


def test_station_gaps() -> None:
    """Qué le falta a cada estación, con la lectura real de todas (15:30Z)."""
    readings = _parse_station_readings(load("ultimos10minEstacionsMeteo.json"))

    gaps = station_gaps(readings, [14000, 10157, 19005, 10906, 12345])

    assert gaps == {
        14000: frozenset(),  # Coruña-Dique: todo
        10157: {NO_WIND, NO_PRESSURE},  # Torre de Hércules
        19005: {NO_WIND},  # Guísamo
        10906: {NO_PRESSURE},  # Cangas-Porto
        12345: {NO_DATA},  # no está en la lectura
    }


def test_station_gaps_old_reading() -> None:
    """Sin datos: más de 1 h por detrás de la lectura más reciente de todas, no
    del reloj (Marroxo lleva desde el 19 sin enviar)."""
    readings = _parse_station_readings(load("ultimos10minEstacionsMeteo.json"))
    marroxo = next(r for r in readings if r.time < datetime(2026, 9, 20, tzinfo=UTC))

    assert station_gaps(readings, [marroxo.station_id]) == {
        marroxo.station_id: {NO_DATA}
    }
    assert station_gaps([], [14000]) == {}


@pytest.mark.freeze_time("2026-10-07T08:45:00+00:00")
async def test_rain_today_real_day(hass: HomeAssistant, aioclient_mock) -> None:
    """Día real: 17 mm entre las 01:30Z y las 03:40Z, ya dentro del día UTC; la
    tarde UTC anterior (22-24Z, ya del día local) fue seca."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        STATION_DAY, json=load("datosDiariosEstacionsMeteo_14000_20261007.json")
    )
    mock_meteogalicia(aioclient_mock)
    mock_meteogalicia(aioclient_mock, concello=15030)

    await setup(hass)

    assert state(hass, "rain_today") == "17.0"


@pytest.mark.freeze_time("2026-10-06T23:30:00+00:00")
async def test_rain_today_before_the_utc_day(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """A la 01:30 local MeteoGalicia aún da el día UTC anterior: la lluvia de hoy
    sale de la hora de 22 a 23Z, no queda «Desconocido»."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATION_DAY, json={"listDatosDiarios": []})
    mock_meteogalicia(aioclient_mock)
    mock_meteogalicia(aioclient_mock, concello=15030)

    await setup(hass)

    # Sin las horas sería «Desconocido».
    assert state(hass, "rain_today") == "0.0"


# Medianoche local del 7 de octubre (horario de verano, UTC+2) y del 7 de
# diciembre (invierno, UTC+1).
SUMMER = datetime(2026, 10, 7, tzinfo=TIMEZONE)
WINTER = datetime(2026, 12, 7, tzinfo=TIMEZONE)


def hour(day: int, at: int, rain: float, high: float, low: float, month: int = 10):
    return StationHour(
        time=datetime(2026, month, day, at, tzinfo=UTC),
        values={"PP_SUM_1.5m": rain, "TA_MAX_1.5m": high, "TA_MIN_1.5m": low},
    )


def utc_day(when: date, rain: float, high: float, low: float, **extra) -> StationDay:
    return StationDay(
        station_id=14000,
        date=when,
        values={
            "PP_SUM_1.5m": rain,
            "TA_MAX_1.5m": high,
            "TA_MIN_1.5m": low,
            "VV_MAX_10m": 6.9,
            **extra,
        },
    )


def test_local_day_adds_the_utc_evening() -> None:
    """Verano: las horas que acaban a las 23 y a las 24Z del día anterior son del
    día local; la de las 22Z, no."""
    hours = [
        hour(6, 22, 5.0, 25.0, 1.0),  # 23:00-00:00 locales del día 6: fuera
        hour(6, 23, 1.2, 18.0, 15.5),
        hour(7, 0, 0.8, 17.5, 15.0),
    ]
    day = utc_day(date(2026, 10, 7), 3.0, 21.0, 16.0)

    today = local_day(day, hours, SUMMER, datetime(2026, 10, 7, 12, tzinfo=UTC))

    assert today == {
        "PP_SUM_1.5m": 5.0,
        "TA_MAX_1.5m": 21.0,
        "TA_MIN_1.5m": 15.0,
        "VV_MAX_10m": 6.9,  # sin horas: el del día UTC
        "HSOL_SUM_1.5m": 0.0,
        "ET0_SUM_1.5m": 0.0,
    }


def test_local_day_in_winter() -> None:
    """Invierno: solo la hora que acaba a las 24Z."""
    hours = [hour(6, 23, 1.2, 18.0, 15.5, 12), hour(7, 0, 0.8, 17.5, 15.0, 12)]
    day = utc_day(date(2026, 12, 7), 3.0, 21.0, 16.0)

    today = local_day(day, hours, WINTER, datetime(2026, 12, 7, 12, tzinfo=UTC))

    assert today["PP_SUM_1.5m"] == 3.8


def test_local_day_before_the_utc_day() -> None:
    """De 00:00 a ~02:24 locales MeteoGalicia aún da el día UTC anterior: solo
    cuentan las horas enteras ya del día local, y no las que aún no han pasado."""
    hours = [hour(6, 23, 1.2, 18.0, 15.5), hour(7, 0, 0.8, 17.5, 15.0)]
    yesterday = utc_day(date(2026, 10, 6), 9.0, 25.0, 12.0, **{"HSOL_SUM_1.5m": 8.0})

    now = datetime(2026, 10, 6, 23, 30, tzinfo=UTC)

    today = local_day(yesterday, hours, SUMMER, now)

    assert today == {
        "PP_SUM_1.5m": 1.2,
        "TA_MAX_1.5m": 18.0,
        "TA_MIN_1.5m": 15.5,
        "HSOL_SUM_1.5m": 0.0,
        "ET0_SUM_1.5m": 0.0,
    }


def test_local_day_without_whole_hours() -> None:
    """Recién pasada la medianoche no hay ninguna hora entera: lluvia 0, sin
    máxima ni mínima."""
    today = local_day(None, [], SUMMER, datetime(2026, 10, 6, 22, 5, tzinfo=UTC))

    assert today == {"PP_SUM_1.5m": 0.0, "HSOL_SUM_1.5m": 0.0, "ET0_SUM_1.5m": 0.0}


def test_local_day_without_hours() -> None:
    """Si no se pudieron pedir las horas, el día UTC tal cual; y sin él, nada."""
    day = utc_day(date(2026, 10, 7), 3.0, 21.0, 16.0)
    now = datetime(2026, 10, 7, 12, tzinfo=UTC)

    assert local_day(day, None, SUMMER, now) == day.values
    assert local_day(None, None, SUMMER, now) is None


async def test_station_position(hass: HomeAssistant) -> None:
    """Todas las entidades de la estación llevan su posición, para un mapa."""
    await setup(hass)

    for entity_id in (PREFIX + "temperature", PREFIX + "station_last_reading"):
        attributes = hass.states.get(entity_id).attributes
        assert attributes["latitude"] == 43.36506, entity_id
        assert attributes["longitude"] == -8.374706, entity_id
