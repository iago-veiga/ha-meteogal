"""Tests de la entidad del tiempo con respuestas reales (Santiago, 2026-09-26)."""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import aiohttp
from homeassistant.components.weather import DOMAIN as WEATHER_DOMAIN
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meteogal.api import MeteoSixHour
from custom_components.meteogal.api.client import (
    TIMEZONE,
    _parse_daily,
    _parse_hourly,
)
from custom_components.meteogal.api.meteosix import _parse_forecast
from custom_components.meteogal.const import ATTRIBUTION, DOMAIN
from custom_components.meteogal.coordinator import LocationData
from custom_components.meteogal.weather import daily_forecast, hourly_forecast

from .api.conftest import (
    DAILY,
    METEOSIX_DOWN_KEY,
    METEOSIX_KEY,
    OBSERVATION,
    SANTIAGO,
    load,
    mock_meteogalicia,
    mock_meteosix,
)

ENTITY_ID = "weather.santiago_de_compostela"

# Hora de las respuestas guardadas: la observación es de las 10:56.
pytestmark = pytest.mark.freeze_time("2026-09-26T11:00:00+02:00")


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
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
    return entry


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def forecasts(hass: HomeAssistant, kind: str) -> list[dict[str, Any]]:
    response = await hass.services.async_call(
        WEATHER_DOMAIN,
        "get_forecasts",
        {"entity_id": ENTITY_ID, "type": kind},
        blocking=True,
        return_response=True,
    )
    return response[ENTITY_ID]["forecast"]


async def test_current_weather(hass: HomeAssistant, entry, aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)
    await setup(hass, entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == "cloudy"  # observación: 105, muy nublado
    assert state.attributes["temperature"] == 15.8
    assert state.attributes["apparent_temperature"] == 15.8
    assert state.attributes["wind_bearing"] == 45.0  # 302: flojo del nordés
    assert state.attributes["attribution"] == ATTRIBUTION


async def test_device_and_unique_id(hass: HomeAssistant, entry, aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)
    await setup(hass, entry)
    (subentry,) = entry.subentries.values()

    entity = er.async_get(hass).async_get(ENTITY_ID)
    assert entity.unique_id == f"{subentry.subentry_id}_weather"
    assert entity.config_subentry_id == subentry.subentry_id
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device.name == "Santiago de Compostela"
    assert device.manufacturer == "MeteoGalicia"


async def test_daily_forecast(hass: HomeAssistant, entry, aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)
    await setup(hass, entry)

    days = await forecasts(hass, "daily")

    # 4 días de corto plazo + 4 de medio plazo.
    assert [d["datetime"][:10] for d in days] == [
        "2026-09-26",
        "2026-09-27",
        "2026-09-28",
        "2026-09-29",
        "2026-09-30",
        "2026-10-01",
        "2026-10-02",
        "2026-10-03",
    ]
    assert days[0] == {
        "datetime": "2026-09-26T00:00:00+02:00",
        "condition": "cloudy",  # 104, nublado 75 %
        "temperature": 28,
        "templow": 13,
        "precipitation_probability": 10,  # máximo de las franjas
        "uv_index": 5,
        "wind_bearing": 270.0,  # todas flojas: la de la tarde, 307 oeste
    }
    assert days[1]["condition"] == "rainy"  # 117, lluvia débil
    # Tarde variable (sin rumbo), mañana en calma, noche flojo del norte: la noche.
    assert days[1]["wind_bearing"] == 0.0
    assert days[3]["wind_bearing"] == 180.0  # 313, moderado del sur
    # Medio plazo: cielo más probable y suma de los que traen precipitación.
    assert days[4]["condition"] == "rainy"  # 117 al 90 %
    assert days[4]["precipitation_probability"] == 90
    assert days[4]["wind_bearing"] == 225.0  # 306, sudoeste
    assert days[6]["condition"] == "sunny"  # 101 al 60 %
    assert days[6]["precipitation_probability"] == 5


async def test_hourly_forecast(hass: HomeAssistant, entry, aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)
    await setup(hass, entry)

    hours = await forecasts(hass, "hourly")

    # Desde la hora en curso hasta el final del día 3: 96 - 11 horas.
    assert len(hours) == 85
    assert hours[0] == {
        "datetime": "2026-09-26T11:00:00+02:00",
        "condition": "sunny",  # 101, despejado
        "temperature": 20,
        "wind_bearing": 45.0,
    }
    assert hours[-1]["datetime"] == "2026-09-29T23:00:00+02:00"
    assert hours[-1]["condition"] == "rainy"  # 208 de noche: chubasco (75 %)


async def test_without_observation_uses_forecast(
    hass: HomeAssistant, entry, aioclient_mock
) -> None:
    aioclient_mock.get(
        OBSERVATION, params={"idConcello": SANTIAGO}, exc=aiohttp.ClientError()
    )
    mock_meteogalicia(aioclient_mock)
    await setup(hass, entry)

    state = hass.states.get(ENTITY_ID)
    # Previsión de las 11:00: 101 (despejado), 20 °C.
    assert state.state == "sunny"
    assert state.attributes["temperature"] == 20
    assert "apparent_temperature" not in state.attributes


async def test_forecast_unavailable_retries_setup(
    hass: HomeAssistant, entry, aioclient_mock
) -> None:
    aioclient_mock.get(DAILY, params={"idConc": SANTIAGO}, status=503)
    mock_meteogalicia(aioclient_mock)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert hass.states.get(ENTITY_ID) is None
    # El motivo, traducido (exception-translations).
    assert entry.reason is not None
    assert entry.reason.startswith("Could not update the forecast for Santiago de")


async def test_unavailable_after_failed_update(
    hass: HomeAssistant, entry, aioclient_mock, freezer
) -> None:
    mock_meteogalicia(aioclient_mock)
    await setup(hass, entry)

    aioclient_mock.clear_requests()
    aioclient_mock.get(DAILY, params={"idConc": SANTIAGO}, status=503)
    mock_meteogalicia(aioclient_mock)
    coordinator = entry.runtime_data.locations[next(iter(entry.subentries))]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


async def test_unload(hass: HomeAssistant, entry, aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)
    await setup(hass, entry)

    assert await hass.config_entries.async_unload(entry.entry_id)

    assert entry.state is ConfigEntryState.NOT_LOADED


# Con clave: hora de las respuestas guardadas de MeteoSIX (petición a las 11:09).
with_meteosix = pytest.mark.freeze_time("2026-09-27T11:10:00+02:00")


@pytest.fixture
def entry_with_key(hass: HomeAssistant, entry, aioclient_mock) -> MockConfigEntry:
    hass.config_entries.async_update_entry(entry, data={"api_key": METEOSIX_KEY})
    mock_meteogalicia(aioclient_mock)
    mock_meteosix(aioclient_mock)
    return entry


@with_meteosix
async def test_current_weather_with_meteosix(
    hass: HomeAssistant, entry_with_key
) -> None:
    await setup(hass, entry_with_key)

    state = hass.states.get(ENTITY_ID)
    # Cielo y temperatura siguen siendo los medidos.
    assert state.state == "cloudy"
    assert state.attributes["temperature"] == 15.8
    # El resto, de la hora de MeteoSIX más cercana (12:00).
    assert state.attributes["humidity"] == 57
    assert state.attributes["pressure"] == 1018
    assert state.attributes["cloud_coverage"] == 50
    # Velocidad y rumbo, los dos de MeteoSIX.
    assert state.attributes["wind_speed"] == 3.2  # 3,18: con un decimal
    assert state.attributes["wind_bearing"] == 38.93


@with_meteosix
async def test_hourly_forecast_with_meteosix(
    hass: HomeAssistant, entry_with_key
) -> None:
    await setup(hass, entry_with_key)

    hours = await forecasts(hass, "hourly")
    by_time = {h["datetime"]: h for h in hours}

    # La hora en curso, de la pública (MeteoSIX empieza a las 12:00).
    assert hours[0]["datetime"] == "2026-09-27T11:00:00+02:00"
    assert "humidity" not in hours[0]
    # Desde ahí, MeteoSIX: cielo, lluvia y nubosidad de la hora que empieza (dato
    # de las 13:00).
    assert hours[1] == {
        "datetime": "2026-09-27T12:00:00+02:00",
        "condition": "cloudy",  # CLOUDY a las 13:00
        "temperature": 21,
        "precipitation": 0.0,
        "wind_speed": 3.2,
        "wind_bearing": 38.93,
        "humidity": 57,
        "cloud_coverage": 80,  # con el cielo: la de las 13:00
        "pressure": 1018,
    }
    # De 15 a 16 caen 0,36 mm en chubascos débiles: icono y lluvia en la misma hora.
    afternoon = by_time["2026-09-27T15:00:00+02:00"]
    assert afternoon["condition"] == "rainy"
    assert afternoon["precipitation"] == 0.36
    assert by_time["2026-09-27T16:00:00+02:00"]["precipitation"] == 0
    # La hora más lluviosa: 6,4 mm de 21 a 22 el martes.
    assert by_time["2026-09-29T21:00:00+02:00"]["precipitation"] == 6.4
    # Despejado de noche.
    assert by_time["2026-09-29T00:00:00+02:00"]["condition"] == "clear-night"
    # Hasta la penúltima hora de MeteoSIX (la última no tiene cielo ni lluvia).
    assert hours[-1]["datetime"] == "2026-10-01T01:00:00+02:00"
    assert len(hours) == 1 + 86


@with_meteosix
async def test_daily_forecast_with_meteosix(
    hass: HomeAssistant, entry_with_key
) -> None:
    await setup(hass, entry_with_key)

    days = {d["datetime"][:10]: d for d in await forecasts(hass, "daily")}

    # Hoy, desde la hora en curso; el resto, días enteros.
    assert days["2026-09-27"]["precipitation"] == 0.7
    # El martes: 22,6 mm y viento de hasta 30,3 km/h del sur (rumbo de esa hora).
    tuesday = days["2026-09-29"]
    assert tuesday["precipitation"] == 22.6
    assert tuesday["wind_speed"] == 30.3
    assert tuesday["wind_bearing"] == 188.71
    # Lo demás sigue siendo de la previsión pública.
    assert tuesday["precipitation_probability"] == 95
    assert tuesday["uv_index"] == 5
    # También el medio plazo, si MeteoSIX cubre el día entero.
    assert days["2026-09-30"]["precipitation"] == 4.4
    # El 1 de octubre MeteoSIX llega solo hasta las 02:00: sin lluvia ni velocidad.
    assert "precipitation" not in days["2026-10-01"]
    assert "wind_speed" not in days["2026-10-01"]


@with_meteosix
async def test_meteosix_down_uses_public(
    hass: HomeAssistant, entry, aioclient_mock
) -> None:
    hass.config_entries.async_update_entry(entry, data={"api_key": METEOSIX_DOWN_KEY})
    mock_meteogalicia(aioclient_mock)
    mock_meteosix(aioclient_mock)
    await setup(hass, entry)

    state = hass.states.get(ENTITY_ID)
    assert state.state == "cloudy"
    assert "humidity" not in state.attributes
    hours = await forecasts(hass, "hourly")
    assert all("precipitation" not in h for h in hours)
    assert hours[-1]["datetime"] == "2026-09-29T23:00:00+02:00"
    days = await forecasts(hass, "daily")
    assert all("precipitation" not in d for d in days)


def test_stale_meteosix_falls_back_to_public() -> None:
    public = LocationData(
        observation=None,
        daily=[],
        hourly=_parse_hourly(load("jsonPredHorariaConcellos_15078.json")),
        medium_term=[],
    )
    meteosix = _parse_forecast(load("meteosix_forecast.json"))[0][:3]  # 12 a 14 h
    now = datetime(2026, 9, 27, 18, 30, tzinfo=TIMEZONE)

    hours = hourly_forecast(public, now, meteosix)

    assert hours[0]["datetime"] == "2026-09-27T18:00:00+02:00"
    assert all("native_precipitation" not in h for h in hours)


@pytest.mark.parametrize(
    ("day", "hours"),
    [(date(2026, 10, 25), 25), (date(2026, 3, 29), 23)],
    ids=["october", "march"],
)
def test_daily_rain_on_clock_change(day: date, hours: int) -> None:
    """El día del cambio de hora suma todas sus horas reales, ni una más."""
    public = LocationData(
        observation=None,
        daily=_parse_daily(load("jsonPredConcellos_15078.json")),
        hourly=[],
        medium_term=[],
    )
    # Cambia la fecha del primer día de la previsión pública al día del cambio.
    public.daily[0] = replace(public.daily[0], date=day)
    midnight = datetime.combine(day, time(), TIMEZONE).astimezone(UTC)
    meteosix = [
        MeteoSixHour(
            time=midnight + timedelta(hours=n), model_run=None, precipitation=1.0
        )
        for n in range(1, 30)
    ]

    (first, *_) = daily_forecast(
        public, datetime.combine(day, time(), TIMEZONE), meteosix
    )

    assert first["native_precipitation"] == hours
