"""Lluvia prevista del WRF en imagen: cliente, coordinador y entidad.

El THREDDS se simula con el catálogo real de la pasada de las 00 UTC del 2026-09-27 y
un mapa real de la lluvia en grises (100 km alrededor de Santiago, 2026-11-02) para
todas las horas.
"""

import asyncio
from datetime import UTC, datetime
import io

import aiohttp
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from PIL import Image
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.meteogal.api import (
    MeteoGalConnectionError,
    MeteoGalResponseError,
    WrfClient,
)
from custom_components.meteogal.api.radar import BBox
from custom_components.meteogal.const import DOMAIN
from custom_components.meteogal.radar import (
    Marker,
    RadarRenderer,
    area_around,
)

from .api.conftest import (
    SANTIAGO,
    WRF_RAIN,
    WRF_RAIN_FRAME,
    mock_meteogalicia,
    mock_radar,
    mock_wrf,
    mock_wrf_rain,
    radar_steps,
)

RUN = "wrf_2d_04km/fmrc/files/20260927/wrf_arw_det_history_d03_20260927_0000.nc4"
ENTITY_ID = "image.santiago_de_compostela_rain_forecast"
BOX = BBox(south=42.4, west=-9.6, north=44.3, east=-7.2)
# 11:10 locales (09:10Z): la animación cubre de 10:00Z a 16:00Z.
pytestmark = pytest.mark.freeze_time("2026-09-27T11:10:00+02:00")


def location() -> ConfigSubentryData:
    return ConfigSubentryData(
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


async def setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="MeteoGal",
        data={},
        options={},
        subentries_data=[location()],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def get_maps(aioclient_mock) -> list:
    return [
        url
        for _, url, _, _ in aioclient_mock.mock_calls
        if "/wms/wrf_2d_04km/" in str(url)
    ]


@pytest.fixture(autouse=True)
def services(aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)
    mock_wrf(aioclient_mock)
    # El radar también se actualiza cuando avanza el reloj.
    mock_radar(aioclient_mock, {"20260927": radar_steps("00:05", "20:45")})


@pytest.fixture
async def wrf(aioclient_mock):
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield WrfClient(session)
    await session.close()


async def test_client_frame(wrf: WrfClient, aioclient_mock) -> None:
    mock_wrf_rain(aioclient_mock)

    png = await wrf.get_rain_frame(
        RUN, datetime(2026, 9, 27, 12, 0, tzinfo=UTC), BOX, 480, 480
    )

    assert png.startswith(b"\x89PNG")
    (query,) = [url.query for url in get_maps(aioclient_mock)]
    assert query["layers"] == "prec"
    assert query["time"] == "2026-09-27T12:00:00Z"
    assert query["bbox"] == "42.4,-9.6,44.3,-7.2"
    assert query["colorscalerange"] == "0.1,30"


async def test_client_errors(wrf: WrfClient, aioclient_mock) -> None:
    when = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    mock_wrf_rain(aioclient_mock, status=500)
    with pytest.raises(MeteoGalResponseError, match="500"):
        await wrf.get_rain_frame(RUN, when, BOX, 480, 480)

    aioclient_mock.clear_requests()
    aioclient_mock.get(WRF_RAIN, text="<html/>", headers={"Content-Type": "text/html"})
    with pytest.raises(MeteoGalResponseError, match="no es PNG"):
        await wrf.get_rain_frame(RUN, when, BOX, 480, 480)

    aioclient_mock.clear_requests()
    aioclient_mock.get(WRF_RAIN, exc=aiohttp.ClientConnectionError("sin red"))
    with pytest.raises(MeteoGalConnectionError):
        await wrf.get_rain_frame(RUN, when, BOX, 480, 480)


async def test_rain_forecast_image(
    hass: HomeAssistant, aioclient_mock, hass_client
) -> None:
    mock_wrf_rain(aioclient_mock)
    entry = await setup(hass)
    (subentry_id,) = entry.subentries

    # Las 6 horas siguientes: la lluvia de 09-10Z (frame de las 10:00Z) a la de 14-15Z.
    maps = get_maps(aioclient_mock)
    assert [m.query["time"] for m in maps] == [
        f"2026-09-27T{h}:00:00Z" for h in ("10", "11", "12", "13", "14", "15")
    ]
    assert maps[0].path.endswith(RUN)

    state = hass.states.get(ENTITY_ID)
    assert state.state == "2026-09-27T09:00:00+00:00"
    assert state.attributes["attribution"] == "MeteoGalicia · Xunta de Galicia"
    registry = er.async_get(hass)
    assert registry.async_get(ENTITY_ID).unique_id == f"{subentry_id}_rain_forecast"
    assert registry.async_get(ENTITY_ID).disabled_by is None

    client = await hass_client()
    response = await client.get(f"/api/image_proxy/{ENTITY_ID}")
    assert response.status == 200
    assert response.content_type == "image/webp"
    assert Image.open(io.BytesIO(await response.read())).n_frames == 6


async def test_window_moves_each_hour(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    mock_wrf_rain(aioclient_mock)
    await setup(hass)
    assert len(get_maps(aioclient_mock)) == 6

    # Misma hora: nada nuevo.
    freezer.tick(1800)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(get_maps(aioclient_mock)) == 6

    # Una hora después: la ventana avanza y solo se pide el mapa nuevo.
    freezer.tick(1800)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    maps = get_maps(aioclient_mock)
    assert len(maps) == 7
    assert maps[-1].query["time"] == "2026-09-27T16:00:00Z"
    assert hass.states.get(ENTITY_ID).state == "2026-09-27T10:00:00+00:00"


async def test_unavailable_without_maps(hass: HomeAssistant, aioclient_mock) -> None:
    mock_wrf_rain(aioclient_mock, status=500)

    entry = await setup(hass)

    # Complemento: MeteoGal arranca igual y solo esta imagen queda no disponible.
    assert hass.states.get(ENTITY_ID).state == "unavailable"
    assert hass.states.get("weather.santiago_de_compostela").state != "unavailable"
    assert entry.state.name == "LOADED"


def test_rain_frame_scale_and_caption() -> None:
    png = WRF_RAIN_FRAME.read_bytes()
    area = area_around(42.8805, -8.5456, 100)
    renderer = RadarRenderer(
        area, [], [Marker(42.8805, -8.5456, True)], "es", far_zone=False
    )
    assert renderer.footer_height == 22  # sin la nota de zona lejana del radar
    start = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    end = datetime(2026, 9, 27, 13, 0, tzinfo=UTC)

    image = renderer.rain_frame(png, start, end)

    assert image.size == (area.width, area.height + 22)
    # Hay lluvia de la escala (azul de «débil») y ninguna de las más intensas.
    colors = {rgb for _, rgb in image.getcolors(maxcolors=100000)}
    assert any(b > 200 and r < 140 for r, g, b in colors)
