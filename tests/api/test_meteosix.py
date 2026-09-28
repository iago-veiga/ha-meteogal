"""Tests del cliente de MeteoSIX.

Respuestas reales del 2026-09-27 (pasada del modelo de las 02:00): Santiago, la costa
de A Coruña y un punto en Estados Unidos, sin datos. El resto de errores siguen el
formato del manual de MeteoSIX v5.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from itertools import pairwise

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.meteogal.api import (
    MeteoGalConnectionError,
    MeteoGalResponseError,
    MeteoSixAuthError,
    MeteoSixClient,
    MeteoSixError,
    MeteoSixHour,
)
from custom_components.meteogal.api.client import TIMEZONE
from custom_components.meteogal.api.meteosix import BASE_URL, MAX_POINTS

from .conftest import load

FORECAST = f"{BASE_URL}/getNumericForecastInfo"
KEY = "clave-secreta-de-prueba"
SANTIAGO = (42.8782, -8.5448)
CORUNA_COAST = (43.37, -8.4)
OUTSIDE = (40.0, -80.0)
CEST = timezone(timedelta(hours=2))


@pytest.fixture
async def meteosix(
    aioclient_mock: AiohttpClientMocker,
) -> AsyncIterator[MeteoSixClient]:
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield MeteoSixClient(session, KEY)
    await session.close()


def exception(code: str, message: str = "Erro") -> dict:
    return {"exception": {"code": code, "message": message}}


async def test_request(meteosix: MeteoSixClient, aioclient_mock) -> None:
    aioclient_mock.get(FORECAST, json={"type": "FeatureCollection", "features": []})

    # Sin features para el punto pedido: la respuesta no cuadra.
    with pytest.raises(MeteoGalResponseError):
        await meteosix.get_forecast([SANTIAGO, (43.37, -8.4)], ["temperature"])

    _, url, _, _ = aioclient_mock.mock_calls[0]
    # Longitud antes que latitud, y la clave como parámetro.
    assert url.query["coords"] == "-8.5448,42.8782;-8.4000,43.3700"
    assert url.query["variables"] == "temperature"
    assert url.query["API_KEY"] == KEY


async def test_forecast(meteosix: MeteoSixClient, aioclient_mock) -> None:
    aioclient_mock.get(FORECAST, json=load("meteosix_forecast.json"))

    santiago, coast, outside = await meteosix.get_forecast(
        [SANTIAGO, CORUNA_COAST, OUTSIDE]
    )

    # Desde la hora siguiente a la petición (11:09) hasta el día +4 a las 02:00.
    assert len(santiago) == len(coast) == 87
    assert santiago[0] == MeteoSixHour(
        time=datetime(2026, 9, 27, 12, tzinfo=CEST),
        model_run=datetime(2026, 9, 27, 2, tzinfo=CEST),
        sky="PARTLY_CLOUDY",
        night=False,
        temperature=21,
        precipitation=0,
        wind_speed=3.18,
        wind_bearing=38.93,
        humidity=57.24,
        cloud_coverage=50,
        pressure=1018,
        snow_level=2592,
    )
    assert santiago[-1].time == datetime(2026, 10, 1, 2, tzinfo=CEST)
    assert all(b.time - a.time == timedelta(hours=1) for a, b in pairwise(santiago))
    # La hora más lluviosa en Santiago: 6,4 mm el martes 29 a las 22:00.
    wettest = max(santiago, key=lambda hour: hour.precipitation)
    assert wettest.time == datetime(2026, 9, 29, 22, tzinfo=CEST)
    assert wettest.precipitation == 6.4
    assert wettest.sky == "OVERCAST_AND_SHOWERS"
    assert coast[0].sky == "CLOUDY"
    # Fuera de los límites: sin datos solo para ese punto.
    assert outside is None


async def test_last_hour_of_the_day(meteosix: MeteoSixClient, aioclient_mock) -> None:
    """Respuesta real de las 23:07 (2026-09-27): el día de hoy llega sin variables."""
    data = load("meteosix_last_hour_of_day.json")
    assert data["features"][0]["properties"]["days"][0]["variables"] is None
    aioclient_mock.get(FORECAST, json=data)

    (hours,) = await meteosix.get_forecast([(43.3623, -8.4115)])

    # Desde las 00:00 de mañana hasta las 02:00 del 1 de octubre.
    assert hours[0].time == datetime(2026, 9, 28, 0, tzinfo=CEST)
    assert hours[-1].time == datetime(2026, 10, 1, 2, tzinfo=CEST)
    assert len(hours) == 75


async def test_hour_without_data(meteosix: MeteoSixClient, aioclient_mock) -> None:
    data = load("meteosix_forecast.json")
    variables = data["features"][0]["properties"]["days"][0]["variables"]
    for variable in variables:
        first = variable["values"][0]
        for field in ("modelRun", "value", "moduleValue", "directionValue"):
            if field in first:
                first[field] = None
    aioclient_mock.get(FORECAST, json=data)

    santiago, *_ = await meteosix.get_forecast([SANTIAGO, CORUNA_COAST, OUTSIDE])

    empty = santiago[0]
    assert empty.time == datetime(2026, 9, 27, 12, tzinfo=CEST)
    assert empty.model_run is None
    assert empty.sky is empty.temperature is empty.wind_speed is None
    assert santiago[1].temperature is not None


async def test_only_point_outside(meteosix: MeteoSixClient, aioclient_mock) -> None:
    # Con un solo punto fuera, la excepción 217 viene para toda la respuesta.
    aioclient_mock.get(FORECAST, json=load("meteosix_out_of_bounds.json"))

    assert await meteosix.get_forecast([OUTSIDE]) == [None]


async def test_check_key(meteosix: MeteoSixClient, aioclient_mock) -> None:
    data = load("meteosix_forecast.json")
    data["features"] = data["features"][:1]
    aioclient_mock.get(FORECAST, json=data)

    await meteosix.check_key()

    _, url, _, _ = aioclient_mock.mock_calls[0]
    # endTime en el futuro: uno anterior a la petición da la excepción 318.
    end = datetime.fromisoformat(url.query["endTime"]).replace(tzinfo=TIMEZONE)
    assert end > datetime.now(TIMEZONE)
    assert url.query["variables"] == "temperature"


async def test_invalid_key(meteosix: MeteoSixClient, aioclient_mock) -> None:
    aioclient_mock.get(FORECAST, json=load("meteosix_invalid_key.json"))

    with pytest.raises(MeteoSixAuthError) as err:
        await meteosix.check_key()

    assert err.value.code == "006"


async def test_missing_key(meteosix: MeteoSixClient, aioclient_mock) -> None:
    aioclient_mock.get(FORECAST, json=exception("005"))

    with pytest.raises(MeteoSixAuthError):
        await meteosix.get_forecast([SANTIAGO])


@pytest.mark.parametrize("code", ["216", "217"])
async def test_no_data_is_not_an_error(
    meteosix: MeteoSixClient, aioclient_mock, code: str
) -> None:
    aioclient_mock.get(FORECAST, json=exception(code))

    assert await meteosix.get_forecast([SANTIAGO, SANTIAGO]) == [None, None]


async def test_other_exception(meteosix: MeteoSixClient, aioclient_mock) -> None:
    aioclient_mock.get(FORECAST, json=exception("000", "Erro interno"))

    with pytest.raises(MeteoSixError) as err:
        await meteosix.get_forecast([SANTIAGO])

    assert not isinstance(err.value, MeteoSixAuthError)
    assert err.value.code == "000"


@pytest.mark.parametrize("count", [0, MAX_POINTS + 1])
async def test_point_limit(meteosix: MeteoSixClient, count: int) -> None:
    with pytest.raises(ValueError):
        await meteosix.get_forecast([SANTIAGO] * count)


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({"status": 503}, MeteoGalResponseError),
        ({"text": "<html>Erro</html>"}, MeteoGalResponseError),
        (
            {"exc": aiohttp.ClientConnectionError(f"?API_KEY={KEY}")},
            MeteoGalConnectionError,
        ),
        ({"exc": TimeoutError()}, MeteoGalConnectionError),
    ],
    ids=["http_503", "html", "connection", "timeout"],
)
async def test_errors_never_show_the_key(
    meteosix: MeteoSixClient, aioclient_mock, response: dict, error: type
) -> None:
    aioclient_mock.get(FORECAST, **response)

    with pytest.raises(error) as err:
        await meteosix.get_forecast([SANTIAGO])

    assert KEY not in str(err.value)
    assert err.value.__cause__ is None
