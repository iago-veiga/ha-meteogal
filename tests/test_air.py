"""Calidad del aire con respuestas reales del 2026-09-29 (~08:00 hora local).

- Torre Hércules (14): ICA 1,8 «Fair» por PM10 a las 08:00; medidas de las 07:00
  (PM2,5 10, PM10 18, NO₂ 20, O₃ 36 µg/m³…).
- Gómez Franqueira (9): ICA 2,0 pero «Fair»: el número llega redondeado.
- CHIMERE del 2026-09-28 00Z en Santiago: ICA 1,5 a las 06:00Z.
- Predicción de Santiago: hoy 1,8 por O₃ (máximo a las 21:00) y dos días más.
"""

import asyncio
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meteogal.air import (
    SOURCE_FORECAST,
    SOURCE_MODEL,
    SOURCE_STATION,
    current_air,
    level,
    station_level,
)
from custom_components.meteogal.api import (
    AirDayForecast,
    AirModelHour,
    AirStationIndex,
    MeteoGalClient,
)
from custom_components.meteogal.api.chimere import _parse_point
from custom_components.meteogal.const import DOMAIN

from .api.conftest import CHIMERE_POINT, FIXTURES, load, mock_meteogalicia

MADRID = ZoneInfo("Europe/Madrid")
AIR = "sensor.a_coruna_air_quality"

pytestmark = pytest.mark.freeze_time("2026-09-29T06:30:00+00:00")


def location(**extra) -> ConfigSubentryData:
    return ConfigSubentryData(
        subentry_type="location",
        title="A Coruña",
        data={
            "latitude": 43.3665,
            "longitude": -8.3735,
            "concello_id": 15030,
            "station_id": None,
            "air_station_id": 14,
            "air_station_use": True,
            **extra,
        },
        unique_id=None,
    )


async def setup(hass: HomeAssistant, aioclient_mock, **extra) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Madrid")
    mock_meteogalicia(aioclient_mock)
    mock_meteogalicia(aioclient_mock, concello=15030)
    entry = MockConfigEntry(
        domain=DOMAIN, title="MeteoGal", data={}, subentries_data=[location(**extra)]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# --- Sin HA ---


def test_levels() -> None:
    assert [level(x) for x in (0.0, 0.99, 1.0, 1.8, 2.0, 3.5, 4.2, 5.9, 6.0)] == [
        "good",
        "good",
        "fair",
        "fair",
        "moderate",
        "poor",
        "very_poor",
        "extremely_poor",
        "extremely_poor",
    ]
    assert level(None) is None


def test_station_level_prefers_label() -> None:
    def index(value: float, label: str | None) -> AirStationIndex:
        return AirStationIndex(
            station_id=9,
            time=datetime(2026, 9, 29, 8, tzinfo=MADRID),
            index=value,
            label=label,
        )

    # Gómez Franqueira: 2,0 redondeado y «Fair».
    assert station_level(index(2.0, "Fair")) == "fair"
    assert station_level(index(3.2, "Very poor")) == "very_poor"
    # Texto desconocido o sin texto: del número.
    assert station_level(index(2.0, "Mala")) == "moderate"
    assert station_level(index(0.5, None)) == "good"


def test_current_air_order() -> None:
    now = datetime(2026, 9, 29, 8, 30, tzinfo=MADRID)
    station = AirStationIndex(
        station_id=14,
        time=datetime(2026, 9, 29, 8, tzinfo=MADRID),
        index=1.8,
        pollutant="PM10",
        label="Fair",
    )
    model = [AirModelHour(time=datetime(2026, 9, 29, 6, tzinfo=UTC), index=2.5)]
    forecast = [
        AirDayForecast(date=date(2026, 9, 29), index=0.4, pollutant="O3", peak=None)
    ]

    assert current_air(station, model, forecast, now).source == SOURCE_STATION
    # Sin estación, o con su dato de hace más de 3 horas: el modelo.
    assert current_air(None, model, forecast, now).source == SOURCE_MODEL
    later = datetime(2026, 9, 29, 11, 30, tzinfo=MADRID)
    model_later = [AirModelHour(time=datetime(2026, 9, 29, 9, tzinfo=UTC), index=2.5)]
    result = current_air(station, model_later, forecast, later)
    assert result.source == SOURCE_MODEL
    assert result.level == "moderate"
    assert result.pollutant is None
    # Sin modelo para esta hora: lo previsto para hoy.
    result = current_air(None, [], forecast, now)
    assert (result.source, result.level, result.pollutant) == (
        SOURCE_FORECAST,
        "good",
        "o3",
    )
    assert current_air(None, [], [], now) is None


def test_chimere_parse() -> None:
    hours = _parse_point((FIXTURES / "chimere_point_santiago.csv").read_text())
    assert len(hours) == 76
    assert hours[0].time == datetime(2026, 9, 28, 0, tzinfo=UTC)
    assert hours[0].index == 2.5
    assert hours[-1].time == datetime(2026, 10, 1, 3, tzinfo=UTC)


async def test_client_air(aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    client = MeteoGalClient(session)
    indexes = {i.station_id: i for i in await client.get_air_indexes()}
    assert indexes[14].index == 1.8
    assert indexes[14].pollutant == "PM10"
    assert indexes[14].label == "Fair"
    assert indexes[14].time == datetime(2026, 9, 29, 8, tzinfo=MADRID)
    # «Sin datos»: la API da -1.
    assert [i.index for i in indexes.values() if i.label == "No data"] == [None, None]

    measurements = await client.get_air_measurements(14)
    assert measurements is not None
    assert measurements.time == datetime(2026, 9, 29, 7, tzinfo=MADRID)
    assert measurements.values["PM25"] == 10.0
    assert measurements.values["CO"] == 0.43

    forecast = await client.get_air_forecast(15078)
    assert [d.date for d in forecast] == [
        date(2026, 9, 29),
        date(2026, 9, 30),
        date(2026, 10, 1),
    ]
    assert forecast[0].index == 1.8
    assert forecast[0].pollutant == "O3"
    assert forecast[0].peak == datetime(2026, 9, 29, 21, tzinfo=MADRID)

    stations = {s.id: s for s in await client.get_air_stations()}
    assert stations[14].kind == "Fondo"
    assert stations[12].kind == "Tráfico"
    await session.close()


def test_measurement_flags() -> None:
    from custom_components.meteogal.api.client import _parse_air_measurements

    data = load("caire_jsonDatosActualesEstacion_14.json")
    data["datosEstacion"][0]["parametros"][0]["flag"] = "M"  # SO2 en mantenimiento
    data["datosEstacion"][0]["parametros"][1]["flag"] = "D"  # NO desactivado
    measurements = _parse_air_measurements(data)
    assert measurements is not None
    assert "SO2" not in measurements.values
    assert "NO" not in measurements.values
    assert measurements.values["NO2"] == 20.0


# --- En HA ---


async def test_station_source(hass: HomeAssistant, aioclient_mock) -> None:
    await setup(hass, aioclient_mock)

    state = hass.states.get(AIR)
    assert state.state == "fair"
    assert state.attributes["source"] == "station"
    assert state.attributes["main_pollutant"] == "pm10"
    assert state.attributes["options"] == [
        "good",
        "fair",
        "moderate",
        "poor",
        "very_poor",
        "extremely_poor",
    ]
    assert hass.states.get("sensor.a_coruna_pm2_5").state == "10.0"
    assert hass.states.get("sensor.a_coruna_pm10").state == "18.0"
    assert hass.states.get("sensor.a_coruna_nitrogen_dioxide").state == "20.0"
    assert hass.states.get("sensor.a_coruna_ozone").state == "36.0"
    updated = hass.states.get("sensor.a_coruna_air_station_last_measurement")
    assert updated.state == "2026-09-29T05:00:00+00:00"
    assert updated.attributes["station_name"] == "Torre Hércules"
    assert updated.attributes["station_type"] == "background"
    assert updated.attributes["distance"] == 3.4

    registry = er.async_get(hass)
    for entity_id in (
        "sensor.a_coruna_air_quality_index",
        "sensor.a_coruna_sulphur_dioxide",
        "sensor.a_coruna_carbon_monoxide",
        "sensor.a_coruna_nitrogen_monoxide",
    ):
        entity = registry.async_get(entity_id)
        assert entity is not None, entity_id
        assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_model_without_station(hass: HomeAssistant, aioclient_mock) -> None:
    await setup(hass, aioclient_mock, air_station_id=None)

    state = hass.states.get(AIR)
    assert state.state == "fair"  # CHIMERE 1,5 a las 06:00Z
    assert state.attributes["source"] == "model"
    assert state.attributes["main_pollutant"] is None
    assert hass.states.get("sensor.a_coruna_pm2_5") is None


async def test_station_not_used(hass: HomeAssistant, aioclient_mock) -> None:
    """«Usar la estación» desmarcado: el nivel del modelo, los sensores siguen."""
    await setup(hass, aioclient_mock, air_station_use=False)

    assert hass.states.get(AIR).attributes["source"] == "model"
    assert hass.states.get("sensor.a_coruna_pm2_5").state == "10.0"


@pytest.mark.freeze_time("2026-09-29T12:00:00+00:00")
async def test_station_stale(hass: HomeAssistant, aioclient_mock) -> None:
    """Dato de la estación de hace 6 horas: el modelo, y las medidas desconocidas."""
    await setup(hass, aioclient_mock)

    assert hass.states.get(AIR).attributes["source"] == "model"
    assert hass.states.get("sensor.a_coruna_pm2_5").state == "unknown"


async def test_forecast_when_no_model(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(CHIMERE_POINT, status=500)
    await setup(hass, aioclient_mock, air_station_id=None)

    state = hass.states.get(AIR)
    assert state.state == "fair"
    assert state.attributes["source"] == "forecast"
    assert state.attributes["main_pollutant"] == "o3"


async def test_get_air_quality(hass: HomeAssistant, aioclient_mock) -> None:
    await setup(hass, aioclient_mock)

    response = await hass.services.async_call(
        DOMAIN,
        "get_air_quality",
        target={"entity_id": AIR},
        blocking=True,
        return_response=True,
    )

    result = response[AIR]
    assert result["now"] == {
        "level": "fair",
        "index": 1.8,
        "main_pollutant": "pm10",
        "source": "station",
    }
    # Desde la hora en curso hasta el final de la pasada (03:00Z del 1 de octubre).
    assert result["hourly"][0] == {
        "datetime": "2026-09-29T08:00:00+02:00",
        "level": "fair",
        "index": 1.5,
    }
    assert result["hourly"][-1]["datetime"] == "2026-10-01T05:00:00+02:00"
    assert result["daily"][0] == {
        "date": "2026-09-29",
        "level": "fair",
        "index": 1.8,
        "main_pollutant": "o3",
        "peak": "2026-09-29T21:00:00+02:00",
    }
    assert len(result["daily"]) == 3


async def test_actions_on_the_wrong_sensor(hass: HomeAssistant, aioclient_mock) -> None:
    await setup(hass, aioclient_mock)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "get_air_quality",
            target={"entity_id": "sensor.a_coruna_warning_level"},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "not_air_quality"
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "get_warnings",
            target={"entity_id": AIR},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "not_warning_level"
