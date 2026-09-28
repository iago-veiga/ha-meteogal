"""Cliente del radar (THREDDS de MeteoGalicia), con respuestas reales del
2026-09-27."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.meteogal.api import (
    MeteoGalConnectionError,
    MeteoGalResponseError,
)
from custom_components.meteogal.api.radar import BASE_URL, BBox, RadarClient

from .conftest import RADAR_FRAME, load

FILE = f"{BASE_URL}/PPI_20260927_10m.nc"
BOX = BBox(south=42.4, west=-9.6, north=44.3, east=-7.2)


@pytest.fixture
async def radar(aioclient_mock: AiohttpClientMocker) -> AsyncIterator[RadarClient]:
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield RadarClient(session)
    await session.close()


async def test_times(radar: RadarClient, aioclient_mock) -> None:
    aioclient_mock.get(FILE, json=load("radar_timesteps_20260927.json"))

    times = await radar.get_times(date(2026, 9, 27))

    assert len(times) == 125
    assert times[0] == datetime(2026, 9, 27, 0, 5, tzinfo=UTC)
    assert times[-1] == datetime(2026, 9, 27, 20, 45, tzinfo=UTC)
    _, url, _, _ = aioclient_mock.mock_calls[0]
    assert url.query["item"] == "timesteps"
    assert url.query["day"] == "2026-09-27"


async def test_frame(radar: RadarClient, aioclient_mock) -> None:
    aioclient_mock.get(
        FILE,
        content=RADAR_FRAME.read_bytes(),
        headers={"Content-Type": "image/png;charset=UTF-8"},
    )

    png = await radar.get_frame(datetime(2026, 9, 27, 20, 5, tzinfo=UTC), BOX, 120, 90)

    assert png == RADAR_FRAME.read_bytes()
    _, url, _, _ = aioclient_mock.mock_calls[0]
    assert url.query["request"] == "GetMap"
    # WMS 1.3.0 con EPSG:4326: latitud antes que longitud.
    assert url.query["bbox"] == "42.4,-9.6,44.3,-7.2"
    assert url.query["time"] == "2026-09-27T20:05:00Z"
    assert (url.query["width"], url.query["height"]) == ("120", "90")
    assert url.query["styles"] == "default-scalar/seq-GreysRev"
    assert url.query["colorscalerange"] == "10,70"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        # Así responde el THREDDS cuando el fichero del día aún no existe.
        (
            {"status": 500, "text": "<html>HTTP Status 500</html>"},
            MeteoGalResponseError,
        ),
        (
            {"text": "<html>Error</html>", "headers": {"Content-Type": "text/html"}},
            MeteoGalResponseError,
        ),
        ({"exc": aiohttp.ClientConnectionError()}, MeteoGalConnectionError),
        ({"exc": TimeoutError()}, MeteoGalConnectionError),
    ],
    ids=["missing_day", "not_png", "connection", "timeout"],
)
async def test_frame_errors(
    radar: RadarClient, aioclient_mock, response: dict, error: type
) -> None:
    aioclient_mock.get(FILE, **response)

    with pytest.raises(error):
        await radar.get_frame(datetime(2026, 9, 27, 20, 5, tzinfo=UTC), BOX, 10, 10)
