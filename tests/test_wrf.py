"""WRF de 4 km: cliente, coordinador y su uso en la entidad del tiempo.

Respuestas reales del THREDDS: la pasada de las 00 UTC del 2026-09-27 en un punto de
Santiago (42,8805 N, 8,5456 O), 96 horas desde las 01:00Z de ese día hasta las 00:00Z
del 1 de octubre.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
import re
from typing import Any

import aiohttp
from homeassistant.components.weather import DOMAIN as WEATHER_DOMAIN
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meteogal.api import (
    DailyForecast,
    DayParts,
    HourlyForecast,
    MeteoGalConnectionError,
    MeteoGalResponseError,
    MeteoSixHour,
    WrfClient,
    WrfHour,
)
from custom_components.meteogal.api.client import TIMEZONE
from custom_components.meteogal.api.wrf import _parse_point
from custom_components.meteogal.const import DOMAIN
from custom_components.meteogal.coordinator import (
    LocationData,
    WrfCoordinator,
    wrf_run_start,
)
from custom_components.meteogal.weather import daily_forecast, hourly_forecast

from .api.conftest import (
    FIXTURES,
    METEOSIX_KEY,
    SANTIAGO,
    STATION_NOW,
    WRF_CATALOG,
    WRF_POINT,
    load,
    mock_meteogalicia,
    mock_meteosix,
    mock_wrf,
)

RUN = "wrf_2d_04km/fmrc/files/20260927/wrf_arw_det_history_d03_20260927_0000.nc4"
ENTITY_ID = "weather.santiago_de_compostela"
# Hora de la petición de MeteoSIX (11:09); la pública cubre del 26 al 29.
pytestmark = pytest.mark.freeze_time("2026-09-27T11:10:00+02:00")

CATALOG = (FIXTURES / "wrf_catalog.xml").read_text()
POINT = (FIXTURES / "wrf_point_santiago.csv").read_text()
HOURS = {hour.time: hour for hour in _parse_point(POINT)}


def catalog_with_noon_run() -> str:
    """El catálogo de la fixture con la pasada de las 12 UTC añadida."""
    start = CATALOG.index('    <dataset name="20260927/')
    end = CATALOG.rindex("  </dataset>")
    return CATALOG[:end] + CATALOG[start:end].replace("_0000", "_1200") + CATALOG[end:]


@pytest.fixture
async def session(aioclient_mock):
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield session
    await session.close()


# --- Cliente ---


async def test_latest_run(aioclient_mock, session) -> None:
    mock_wrf(aioclient_mock)
    assert await WrfClient(session).get_latest_run() == RUN


async def test_latest_run_is_the_newest(aioclient_mock, session) -> None:
    aioclient_mock.get(WRF_CATALOG, text=catalog_with_noon_run())
    run = await WrfClient(session).get_latest_run()
    assert run.endswith("wrf_arw_det_history_d03_20260927_1200.nc4")


async def test_latest_run_without_files(aioclient_mock, session) -> None:
    aioclient_mock.get(WRF_CATALOG, text="<catalog></catalog>")
    with pytest.raises(MeteoGalResponseError):
        await WrfClient(session).get_latest_run()


async def test_get_point(aioclient_mock, session) -> None:
    mock_wrf(aioclient_mock)
    hours = await WrfClient(session).get_point(RUN, 42.8805, -8.5456)

    assert len(hours) == 96
    assert hours[0] == WrfHour(
        time=datetime(2026, 9, 27, 1, tzinfo=UTC),
        gust=2.7,  # 0,745 m/s
        wind_speed=1.3,  # 0,361 m/s
        wind_bearing=11.6,
        humidity=69.9,  # fracción 0,699
        pressure=1018.7,  # 101865,79 Pa
    )
    assert hours[-1].time == datetime(2026, 10, 1, 0, tzinfo=UTC)
    # Una sola petición con todas las variables y el punto.
    (_, url, *_) = aioclient_mock.mock_calls[0]
    assert url.query["var"] == "wind_gust,mod,dir,rh,mslp"
    assert url.query["temporal"] == "all"
    assert url.query["latitude"] == "42.8805"
    assert url.query["longitude"] == "-8.5456"


def test_parse_point_missing_values() -> None:
    text = (
        'time,station,latitude[unit="degrees_north"],longitude[unit="degrees_east"],'
        'wind_gust[unit="m s-1"],mod[unit="m s-1"],dir[unit="degree"],rh[unit="1"],'
        'mslp[unit="Pa"]\n'
        "2026-09-27T01:00:00Z,P,42.9,-8.5,NaN,2.0,90.0,1.2,NaN\n"
    )
    (hour,) = _parse_point(text)
    assert hour.gust is None
    assert hour.pressure is None
    assert hour.wind_speed == 7.2
    assert hour.humidity == 100.0  # nunca por encima de 100


@pytest.mark.parametrize("text", ["", "<html>no es csv</html>", "time,x\nbasura\n"])
def test_parse_point_garbage(text: str) -> None:
    with pytest.raises((ValueError, KeyError, IndexError)):
        _parse_point(text)


async def test_http_error(aioclient_mock, session) -> None:
    aioclient_mock.get(WRF_POINT, status=500)
    with pytest.raises(MeteoGalResponseError):
        await WrfClient(session).get_point(RUN, 42.88, -8.54)


async def test_bad_csv(aioclient_mock, session) -> None:
    aioclient_mock.get(WRF_POINT, text="<html>no es csv</html>")
    with pytest.raises(MeteoGalResponseError):
        await WrfClient(session).get_point(RUN, 42.88, -8.54)


async def test_connection_error(aioclient_mock, session) -> None:
    aioclient_mock.get(WRF_CATALOG, exc=aiohttp.ClientConnectionError())
    with pytest.raises(MeteoGalConnectionError):
        await WrfClient(session).get_latest_run()


def test_run_start() -> None:
    assert wrf_run_start(RUN) == datetime(2026, 9, 27, 0, tzinfo=UTC)
    assert wrf_run_start(RUN.replace("_0000", "_1200")) == datetime(
        2026, 9, 27, 12, tzinfo=UTC
    )
    assert wrf_run_start("otro.nc4") is None


# --- Coordinador ---


def location(**extra: Any) -> ConfigSubentryData:
    return ConfigSubentryData(
        subentry_type="location",
        title="Santiago de Compostela",
        data={
            "latitude": 42.8805,
            "longitude": -8.5456,
            "concello_id": SANTIAGO,
            "station_id": None,
            **extra,
        },
        unique_id=None,
    )


def point_calls(aioclient_mock) -> int:
    return sum(1 for call in aioclient_mock.mock_calls if "ncss/grid" in str(call[1]))


def make_coordinator(hass: HomeAssistant) -> WrfCoordinator:
    entry = MockConfigEntry(
        domain=DOMAIN, title="MeteoGal", data={}, subentries_data=[location()]
    )
    entry.add_to_hass(hass)
    return WrfCoordinator(
        hass,
        entry,
        list(entry.subentries.values()),
        WrfClient(async_get_clientsession(hass)),
    )


async def test_coordinator_loads_once_per_run(
    hass: HomeAssistant, aioclient_mock
) -> None:
    mock_wrf(aioclient_mock)
    coordinator = make_coordinator(hass)

    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data.run == RUN
    (hours,) = coordinator.data.hours.values()
    assert len(hours) == 96
    assert point_calls(aioclient_mock) == 1

    # Misma pasada: solo se mira el catálogo.
    await coordinator.async_refresh()
    assert point_calls(aioclient_mock) == 1


async def test_coordinator_new_run(hass: HomeAssistant, aioclient_mock) -> None:
    mock_wrf(aioclient_mock)
    coordinator = make_coordinator(hass)
    await coordinator.async_refresh()

    aioclient_mock.clear_requests()
    aioclient_mock.get(WRF_CATALOG, text=catalog_with_noon_run())
    aioclient_mock.get(WRF_POINT, text=POINT)
    await coordinator.async_refresh()

    assert coordinator.data.run.endswith("20260927_1200.nc4")
    assert point_calls(aioclient_mock) == 1


async def test_coordinator_partial_run_is_requested_again(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Una pasada a medio escribir (pocas horas) se usa, pero se vuelve a pedir."""
    aioclient_mock.get(WRF_CATALOG, text=CATALOG)
    aioclient_mock.get(WRF_POINT, text="\n".join(POINT.splitlines()[:30]) + "\n")
    coordinator = make_coordinator(hass)

    await coordinator.async_refresh()
    assert coordinator.data.run is None  # no se da por buena
    (hours,) = coordinator.data.hours.values()
    assert len(hours) == 29  # pero se usa lo que hay

    aioclient_mock.clear_requests()
    mock_wrf(aioclient_mock)
    await coordinator.async_refresh()
    assert coordinator.data.run == RUN
    assert len(next(iter(coordinator.data.hours.values()))) == 96


async def test_coordinator_keeps_the_last_good_run(
    hass: HomeAssistant, aioclient_mock
) -> None:
    mock_wrf(aioclient_mock)
    coordinator = make_coordinator(hass)
    await coordinator.async_refresh()
    before = coordinator.data

    aioclient_mock.clear_requests()
    aioclient_mock.get(WRF_CATALOG, exc=aiohttp.ClientConnectionError())
    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert coordinator.data == before


async def test_coordinator_without_data_fails(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.get(WRF_CATALOG, status=500)
    coordinator = make_coordinator(hass)

    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    assert isinstance(coordinator.last_exception, UpdateFailed)


# --- Previsión: funciones ---


def wrf_hours(
    start: datetime, count: int = 80, **values: float | None
) -> list[WrfHour]:
    fields = {
        "gust": 20.0,
        "wind_speed": 10.0,
        "wind_bearing": 200.0,
        "humidity": 70.0,
        "pressure": 1015.0,
    }
    fields.update(values)
    return [WrfHour(time=start + timedelta(hours=n), **fields) for n in range(count)]


def public_data() -> LocationData:
    hours = [
        HourlyForecast(
            time=datetime(2026, 9, 27, hour, tzinfo=TIMEZONE),
            sky=101,
            temperature=18,
            wind=300,
        )
        for hour in range(24)
    ]
    return LocationData(daily=[], medium_term=[], hourly=hours, observation=None)


def daily(day: int) -> DailyForecast:
    parts = DayParts(101, 101, 101)
    return DailyForecast(
        date=date(2026, 9, day),
        sky=101,
        sky_parts=parts,
        precipitation_probability=DayParts(0, 0, 0),
        wind=DayParts(300, 300, 300),
        temperature_max=20,
        temperature_min=12,
        temperature_max_parts=DayParts(20, 20, 20),
        temperature_min_parts=DayParts(12, 12, 12),
        uv_max=4,
        alert_level=None,
    )


NOW = datetime(2026, 9, 27, 11, 10, tzinfo=TIMEZONE)


def test_hourly_adds_gust_and_fallback_without_meteosix() -> None:
    items = hourly_forecast(
        public_data(), NOW, None, wrf_hours(datetime(2026, 9, 27, tzinfo=UTC))
    )

    first = items[0]
    assert first["datetime"] == "2026-09-27T11:00:00+02:00"
    # Sin MeteoSIX: viento, humedad y presión del WRF; la racha, la suya.
    assert first["native_wind_speed"] == 10.0
    assert first["native_wind_gust_speed"] == 20.0
    assert first["humidity"] == 70.0
    assert first["native_pressure"] == 1015.0
    # Cielo y temperatura siguen siendo los de la pública; nunca lluvia.
    assert first["condition"] == "sunny"
    assert first["native_temperature"] == 18
    assert "native_precipitation" not in first


def test_hourly_gust_never_below_the_mean_wind() -> None:
    start = datetime(2026, 9, 27, tzinfo=UTC)
    items = hourly_forecast(
        public_data(), NOW, None, wrf_hours(start, gust=5.0, wind_speed=9.0)
    )
    assert items[0]["native_wind_gust_speed"] == 9.0


def test_hourly_without_wrf_is_unchanged() -> None:
    plain = hourly_forecast(public_data(), NOW)
    assert "native_wind_gust_speed" not in plain[0]
    assert plain == hourly_forecast(public_data(), NOW, None, [])


def test_hourly_hours_outside_the_wrf_are_left_alone() -> None:
    # El WRF empieza a las 12:00 locales (10:00Z): la hora en curso queda como estaba.
    start = datetime(2026, 9, 27, 10, tzinfo=UTC)
    items = hourly_forecast(public_data(), NOW, None, wrf_hours(start, 5))
    assert "native_wind_gust_speed" not in items[0]
    assert items[1]["native_wind_gust_speed"] == 20.0
    assert "native_wind_gust_speed" not in items[-1]


def test_hourly_meteosix_hours_keep_their_values() -> None:
    sixes = [
        MeteoSixHour(
            time=datetime(2026, 9, 27, 10, tzinfo=UTC) + timedelta(hours=n),
            model_run=None,
            sky="SUNNY",
            temperature=21,
            precipitation=0.0,
            wind_speed=14.0,
            humidity=55,
            pressure=1019,
        )
        for n in range(6)
    ]
    items = hourly_forecast(
        public_data(), NOW, sixes, wrf_hours(datetime(2026, 9, 27, tzinfo=UTC))
    )
    meteosix_item = items[1]  # 12:00 locales, de MeteoSIX
    assert meteosix_item["native_wind_speed"] == 14.0
    assert meteosix_item["humidity"] == 55
    assert meteosix_item["native_pressure"] == 1019
    assert meteosix_item["native_wind_gust_speed"] == 20.0  # la del WRF


def test_daily_gust_needs_the_whole_day() -> None:
    data = LocationData(
        daily=[daily(27), daily(28), daily(29)],
        medium_term=[],
        hourly=[],
        observation=None,
    )
    # El WRF cubre hoy (desde las 11:00 locales) y mañana entero, y se acaba a media
    # tarde del 29.
    hours = wrf_hours(datetime(2026, 9, 27, 9, tzinfo=UTC), 39, gust=30.0)
    hours[5] = WrfHour(time=hours[5].time, gust=55.0, wind_speed=40.0)
    days = daily_forecast(data, NOW, None, hours)

    assert days[0]["native_wind_gust_speed"] == 55.0  # lo máximo de lo que queda de hoy
    assert days[0]["native_wind_speed"] == 40.0
    assert days[1]["native_wind_gust_speed"] == 30.0  # día entero
    assert "native_wind_gust_speed" not in days[2]  # el WRF no llega


def test_daily_keeps_the_wind_of_meteosix_and_raises_the_gust() -> None:
    data = LocationData(daily=[daily(28)], medium_term=[], hourly=[], observation=None)
    midnight = datetime(2026, 9, 28, tzinfo=TIMEZONE).astimezone(UTC)
    sixes = [
        MeteoSixHour(
            time=midnight + timedelta(hours=n),
            model_run=None,
            wind_speed=45.0,
            precipitation=0.0,
        )
        for n in range(26)
    ]
    hours = wrf_hours(midnight - timedelta(hours=24), 80, gust=30.0, wind_speed=12.0)
    days = daily_forecast(data, NOW, sixes, hours)

    assert days[0]["native_wind_speed"] == 45.0  # el de MeteoSIX
    assert days[0]["native_wind_gust_speed"] == 45.0  # la racha, al menos el viento


# --- En Home Assistant ---


@pytest.fixture
def entry(hass: HomeAssistant, aioclient_mock) -> MockConfigEntry:
    mock_wrf(aioclient_mock)
    mock_meteogalicia(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN, title="MeteoGal", data={}, subentries_data=[location()]
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


async def test_current_weather_falls_back_to_the_wrf(
    hass: HomeAssistant, entry
) -> None:
    """Sin estación ni MeteoSIX: viento, racha, humedad y presión del WRF (09:00Z)."""
    await setup(hass, entry)

    attributes = hass.states.get(ENTITY_ID).attributes
    wrf = HOURS[datetime(2026, 9, 27, 9, tzinfo=UTC)]
    assert attributes["wind_speed"] == wrf.wind_speed
    assert attributes["wind_bearing"] == wrf.wind_bearing
    assert attributes["wind_gust_speed"] == max(wrf.gust, wrf.wind_speed)
    assert attributes["humidity"] == round(wrf.humidity)  # HA la da entera
    assert attributes["pressure"] == wrf.pressure


async def test_hourly_forecast_with_the_wrf(hass: HomeAssistant, entry) -> None:
    await setup(hass, entry)

    by_time = {h["datetime"]: h for h in await forecasts(hass, "hourly")}
    noon = by_time["2026-09-27T14:00:00+02:00"]  # las 12:00Z
    wrf = HOURS[datetime(2026, 9, 27, 12, tzinfo=UTC)]
    assert noon["wind_speed"] == wrf.wind_speed
    assert noon["wind_gust_speed"] == max(wrf.gust, wrf.wind_speed)
    assert noon["humidity"] == round(wrf.humidity)
    assert noon["pressure"] == wrf.pressure
    # Lo de la previsión pública, igual: cielo y temperatura; la lluvia, nada.
    assert "condition" in noon
    assert "temperature" in noon
    assert "precipitation" not in noon


async def test_daily_forecast_with_the_wrf(hass: HomeAssistant, entry) -> None:
    await setup(hass, entry)

    days = {d["datetime"][:10]: d for d in await forecasts(hass, "daily")}
    # El WRF cubre hoy (desde las 11:00 locales) y los tres días siguientes enteros
    # (acaba a las 00:00Z del 1 de octubre, las 02:00 locales).
    for day in ("2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30"):
        assert days[day]["wind_gust_speed"] >= days[day]["wind_speed"] > 0
    assert "wind_gust_speed" not in days["2026-10-01"]  # no llega al final del día


def station_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="MeteoGal",
        data={},
        subentries_data=[location(station_id=14000, station_weather=True)],
    )
    entry.add_to_hass(hass)
    return entry


async def test_station_without_gust_falls_back_to_the_wrf(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """La lectura de Coruña-Dique de la fixture tiene el viento todo a cero (se toma
    como dato ausente): sin racha medida, la del WRF."""
    mock_wrf(aioclient_mock)
    mock_meteogalicia(aioclient_mock)
    await setup(hass, station_entry(hass))

    wrf = HOURS[datetime(2026, 9, 27, 9, tzinfo=UTC)]
    attributes = hass.states.get(ENTITY_ID).attributes
    assert attributes["wind_gust_speed"] == max(wrf.gust, wrf.wind_speed)


async def test_station_gust_wins_over_the_wrf(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Con una racha medida (aquí 5 m/s = 18 km/h), manda la de la estación."""
    reading = load("ultimos10minEstacionsMeteo_14000.json")
    for measure in reading["listUltimos10min"][0]["listaMedidas"]:
        if measure["codigoParametro"] == "VV_RACHA_10m":
            measure["valor"] = 5.0
        if measure["codigoParametro"] == "VV_AVG_10m":
            measure["valor"] = 2.0
    aioclient_mock.get(re.compile(re.escape(STATION_NOW) + r"\?idEst="), json=reading)
    mock_wrf(aioclient_mock)
    mock_meteogalicia(aioclient_mock)
    await setup(hass, station_entry(hass))

    attributes = hass.states.get(ENTITY_ID).attributes
    assert attributes["wind_gust_speed"] == 18.0


async def test_meteosix_wind_stays_and_gets_a_gust(
    hass: HomeAssistant, entry, aioclient_mock
) -> None:
    """Con clave: viento, humedad y presión siguen siendo de MeteoSIX."""
    hass.config_entries.async_update_entry(entry, data={"api_key": METEOSIX_KEY})
    mock_meteosix(aioclient_mock)
    await setup(hass, entry)

    attributes = hass.states.get(ENTITY_ID).attributes
    assert attributes["wind_speed"] == 3.2  # el de MeteoSIX (12:00 locales)
    assert attributes["humidity"] == 57
    assert attributes["pressure"] == 1018
    # La racha, la del WRF de la hora más cercana (09:00Z), nunca por debajo del viento.
    wrf = HOURS[datetime(2026, 9, 27, 9, tzinfo=UTC)]
    assert attributes["wind_gust_speed"] == max(wrf.gust, 3.2)


async def test_without_the_wrf_nothing_changes(
    hass: HomeAssistant, aioclient_mock
) -> None:
    mock_meteogalicia(aioclient_mock)
    aioclient_mock.get(WRF_CATALOG, status=500)
    entry = MockConfigEntry(
        domain=DOMAIN, title="MeteoGal", data={}, subentries_data=[location()]
    )
    entry.add_to_hass(hass)
    await setup(hass, entry)

    attributes = hass.states.get(ENTITY_ID).attributes
    assert "wind_gust_speed" not in attributes
    assert "wind_speed" not in attributes
    assert all("wind_gust_speed" not in h for h in await forecasts(hass, "hourly"))
