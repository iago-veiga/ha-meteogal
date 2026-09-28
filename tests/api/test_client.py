"""Tests del cliente con respuestas reales de MeteoGalicia (Santiago, 2026-09-26)."""

from datetime import date, datetime
from itertools import pairwise
from typing import Any

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.meteogal.api import (
    DayParts,
    MeteoGalClient,
    MeteoGalConnectionError,
    MeteoGalNotFoundError,
    MeteoGalResponseError,
    SkyProbability,
)
from custom_components.meteogal.api.client import TIMEZONE

from .conftest import (
    DAILY,
    MEDIUM_TERM,
    SANTIAGO,
    STATIONS,
    UNKNOWN,
    WARNINGS,
    load,
    mock_meteogalicia,
)


def override(
    aioclient_mock: AiohttpClientMocker, url: str, params=None, **response: Any
) -> None:
    """Cambia la respuesta de un endpoint y deja el resto como estaban."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(url, params=params, **response)
    mock_meteogalicia(aioclient_mock)


async def test_concellos(client: MeteoGalClient) -> None:
    concellos = await client.get_concellos()

    assert len(concellos) == 313
    assert concellos[0].id == 15001
    assert concellos[0].name == "Abegondo"
    assert len({c.id for c in concellos}) == 313


async def test_stations(client: MeteoGalClient) -> None:
    stations = await client.get_stations()

    assert len(stations) == 155
    first = stations[0]
    assert first.id == 10157
    assert first.name == "Coruña-Torre de Hércules"
    assert first.concello == "A CORUÑA"
    assert first.province == "A Coruña"
    assert first.latitude == pytest.approx(43.382763)
    assert first.longitude == pytest.approx(-8.409202)
    assert first.altitude == 21.0


async def test_daily_forecast(client: MeteoGalClient) -> None:
    days = await client.get_daily_forecast(SANTIAGO)

    assert [d.date for d in days] == [
        date(2026, 9, 26),
        date(2026, 9, 27),
        date(2026, 9, 28),
        date(2026, 9, 29),
    ]
    today = days[0]
    assert today.sky == 104
    assert today.sky_parts == DayParts(morning=103, afternoon=104, night=204)
    assert today.precipitation_probability == DayParts(5, 10, 10)
    assert today.wind == DayParts(302, 307, 302)
    assert today.temperature_max == 28
    assert today.temperature_min == 13
    assert today.temperature_max_parts == DayParts(24, 28, 22)
    assert today.temperature_min_parts == DayParts(14, 23, 16)
    assert today.uv_max == 5
    assert today.alert_level is None


async def test_hourly_forecast(client: MeteoGalClient) -> None:
    hours = await client.get_hourly_forecast(SANTIAGO)

    assert len(hours) == 96
    first = hours[0]
    assert first.time == datetime(2026, 9, 26, 0, 0, tzinfo=TIMEZONE)
    assert first.sky == 201
    assert first.wind == 302
    assert first.temperature == 16
    assert hours[-1].time == datetime(2026, 9, 29, 23, 0, tzinfo=TIMEZONE)
    assert all(a.time < b.time for a, b in pairwise(hours))


async def test_medium_term_forecast(client: MeteoGalClient) -> None:
    days = await client.get_medium_term_forecast(SANTIAGO)

    assert [d.day for d in days] == [4, 5, 6, 7]
    first = days[0]
    assert first.date == date(2026, 9, 30)
    assert first.sky == (
        SkyProbability(sky=101, probability=5),
        SkyProbability(sky=103, probability=5),
        SkyProbability(sky=117, probability=90),
    )
    assert first.wind == 306
    assert (
        first.temperature_max_low,
        first.temperature_max,
        first.temperature_max_high,
    ) == (18, 19, 19)
    assert (
        first.temperature_min_low,
        first.temperature_min,
        first.temperature_min_high,
    ) == (12, 13, 13)


async def test_concello_observation(client: MeteoGalClient) -> None:
    observation = await client.get_concello_observation(SANTIAGO)

    assert observation.concello_id == SANTIAGO
    assert observation.time == datetime(2026, 9, 26, 10, 56, tzinfo=TIMEZONE)
    assert observation.sky == 105
    assert observation.wind == 302
    assert observation.temperature == 15.8
    assert observation.apparent_temperature == 15.8


async def test_concello_observation_missing(client: MeteoGalClient) -> None:
    # Sin datos (o concello inexistente): lista vacía, no es un error.
    assert await client.get_concello_observation(UNKNOWN) is None


@pytest.mark.parametrize(
    "method",
    ["get_daily_forecast", "get_hourly_forecast", "get_medium_term_forecast"],
)
async def test_unknown_concello(client: MeteoGalClient, method: str) -> None:
    with pytest.raises(MeteoGalNotFoundError):
        await getattr(client, method)(UNKNOWN)


async def test_missing_values_are_none(client: MeteoGalClient, aioclient_mock) -> None:
    data = load("jsonPredConcellos_15078.json")
    day = data["predConcello"]["listaPredDiaConcello"][0]
    day["tMax"] = -9999
    day["ceo"]["tarde"] = -9999
    day["pchoiva"]["noite"] = -9999
    override(aioclient_mock, DAILY, {"idConc": SANTIAGO}, json=data)

    today = (await client.get_daily_forecast(SANTIAGO))[0]

    assert today.temperature_max is None
    assert today.sky_parts.afternoon is None
    assert today.precipitation_probability.night is None


async def test_missing_medium_term_sky_is_skipped(
    client: MeteoGalClient, aioclient_mock
) -> None:
    data = load("jsonPredMedioPrazo_15078.json")
    data["predMPrazo"]["listaPredDiaMPrazo"][0]["icoCeo2"] = -9999
    override(aioclient_mock, MEDIUM_TERM, {"idConc": SANTIAGO, "dia": -1}, json=data)

    first = (await client.get_medium_term_forecast(SANTIAGO))[0]

    assert [s.sky for s in first.sky] == [101, 117]


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({"status": 503}, MeteoGalResponseError),
        ({"text": "<html>Erro da petición</html>"}, MeteoGalResponseError),
        ({"json": {"otraCousa": []}}, MeteoGalResponseError),
        ({"exc": aiohttp.ClientConnectionError()}, MeteoGalConnectionError),
        ({"exc": TimeoutError()}, MeteoGalConnectionError),
    ],
    ids=["http_503", "html", "unexpected_format", "connection", "timeout"],
)
async def test_errors(
    client: MeteoGalClient, aioclient_mock, response: dict, error: type
) -> None:
    override(aioclient_mock, STATIONS, **response)

    with pytest.raises(error):
        await client.get_stations()


async def test_warnings(client: MeteoGalClient, aioclient_mock) -> None:
    override(
        aioclient_mock,
        WARNINGS,
        {"idConcello": SANTIAGO, "dia": -1},
        json=load("jsonAvisosConcellos_15053.json"),
    )

    wind, rain = await client.get_warnings(SANTIAGO)

    assert (wind.id, wind.type_id, wind.level) == (815130500, 8, 1)
    assert wind.start == datetime(2026, 9, 29, 12, 0, tzinfo=TIMEZONE)
    assert wind.end == datetime(2026, 9, 29, 18, 0, tzinfo=TIMEZONE)
    assert (rain.type_id, rain.end) == (4, datetime(2026, 9, 30, 0, 0, tzinfo=TIMEZONE))


async def test_no_warnings_and_unknown_concello(client: MeteoGalClient) -> None:
    # Sin avisos o con un concello inexistente: la misma respuesta, lista vacía.
    assert await client.get_warnings(UNKNOWN) == []


async def test_warning_in_two_days_counts_once(
    client: MeteoGalClient, aioclient_mock
) -> None:
    data = load("jsonAvisosConcellos_15053.json")
    days = data["listaDiaConcellos"]
    days[1]["listaAvisosConcellos"] = days[2]["listaAvisosConcellos"][:1]
    override(aioclient_mock, WARNINGS, {"idConcello": SANTIAGO, "dia": -1}, json=data)

    assert len(await client.get_warnings(SANTIAGO)) == 2


async def test_cameras_with_shared_id(client: MeteoGalClient) -> None:
    """Ons (playa y puerto) y Cíes (faro norte y sur) comparten identificador:
    la clave de cada cámara es la carpeta de su foto."""
    cameras = await client.get_cameras()

    assert len(cameras) == 33
    assert len({camera.key for camera in cameras}) == 33
    ons = sorted(camera.key for camera in cameras if camera.id == 10904)
    assert ons == ["Onsplaya", "Onspuerto"]
    dique = next(camera for camera in cameras if camera.key == "Corunha")
    assert (dique.id, dique.name) == (14000, "Coruña-Dique")
