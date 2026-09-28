"""Radar en HA: entidades `image`, pasadas nuevas, medianoche UTC y opciones.

El THREDDS se simula con la lista real de pasadas del 2026-09-27 y una pasada real
en grises (A Coruña, 20:05Z) para todas las horas.
"""

from datetime import UTC, datetime, timedelta
import io
from itertools import pairwise

from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from PIL import Image
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.meteogal.const import DOMAIN

from .api.conftest import SANTIAGO, mock_meteogalicia, mock_radar, radar_steps

RADAR = "image.santiago_de_compostela_radar"
RADAR_LATEST = "image.santiago_de_compostela_radar_latest_scan"

pytestmark = pytest.mark.freeze_time("2026-09-27T20:50:00+00:00")


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


async def setup(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="MeteoGal",
        data={},
        options=options or {},
        subentries_data=[location()],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def get_maps(aioclient_mock) -> list:
    return [url for _, url, _, _ in aioclient_mock.mock_calls if "GetMap" in str(url)]


@pytest.fixture(autouse=True)
def services(aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)


async def test_radar_images(hass: HomeAssistant, aioclient_mock, hass_client) -> None:
    mock_radar(aioclient_mock, {"20260927": radar_steps("00:05", "20:45")})
    await setup(hass)

    state = hass.states.get(RADAR)
    # Estado: hora de la última pasada.
    assert state.state == "2026-09-27T20:45:00+00:00"
    assert state.attributes["attribution"] == "MeteoGalicia · Xunta de Galicia"
    # 2 h cada 10 min: 13 pasadas, de 18:45 a 20:45, una petición cada una.
    maps = get_maps(aioclient_mock)
    assert len(maps) == 13
    assert maps[0].query["time"] == "2026-09-27T18:45:00Z"
    assert maps[-1].query["time"] == "2026-09-27T20:45:00Z"

    client = await hass_client()
    response = await client.get(f"/api/image_proxy/{RADAR}")
    assert response.status == 200
    assert response.content_type == "image/webp"
    image = Image.open(io.BytesIO(await response.read()))
    assert image.n_frames == 13


async def test_latest_disabled_by_default(hass: HomeAssistant, aioclient_mock) -> None:
    mock_radar(aioclient_mock, {"20260927": radar_steps("00:05", "20:45")})
    entry = await setup(hass)
    (subentry_id,) = entry.subentries

    registry = er.async_get(hass)
    animation = registry.async_get(RADAR)
    latest = registry.async_get(RADAR_LATEST)
    assert animation.unique_id == f"{subentry_id}_radar"
    assert latest.unique_id == f"{subentry_id}_radar_latest"
    assert latest.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert (
        animation.device_id
        == registry.async_get("weather.santiago_de_compostela").device_id
    )


async def test_only_new_scans_are_downloaded(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    mock_radar(aioclient_mock, {"20260927": radar_steps("00:05", "20:45")})
    await setup(hass)
    assert len(get_maps(aioclient_mock)) == 13

    # Misma lista: no se pide ninguna imagen.
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(get_maps(aioclient_mock)) == 13

    # Una pasada nueva: se pide solo esa.
    aioclient_mock.clear_requests()
    mock_meteogalicia(aioclient_mock)
    mock_radar(aioclient_mock, {"20260927": radar_steps("00:05", "20:55")})
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    maps = get_maps(aioclient_mock)
    assert [url.query["time"] for url in maps] == ["2026-09-27T20:55:00Z"]
    assert hass.states.get(RADAR).state == "2026-09-27T20:55:00+00:00"


@pytest.mark.freeze_time("2026-09-28T00:08:00+00:00")
async def test_after_midnight_utc(hass: HomeAssistant, aioclient_mock) -> None:
    # A las 00:08Z aún no existe el fichero de hoy (el THREDDS responde 500).
    mock_radar(
        aioclient_mock,
        {"20260928": 500, "20260927": radar_steps("00:05", "23:55")},
    )
    await setup(hass)

    assert hass.states.get(RADAR).state == "2026-09-27T23:55:00+00:00"
    assert len(get_maps(aioclient_mock)) == 13


@pytest.mark.freeze_time("2026-09-28T00:50:00+00:00")
async def test_animation_across_midnight(hass: HomeAssistant, aioclient_mock) -> None:
    mock_radar(
        aioclient_mock,
        {
            "20260927": radar_steps("00:05", "23:55"),
            "20260928": radar_steps("00:05", "00:45"),
        },
    )
    await setup(hass)

    times = [url.query["time"] for url in get_maps(aioclient_mock)]
    assert times[0] == "2026-09-27T22:45:00Z"
    assert times[-1] == "2026-09-28T00:45:00Z"
    assert len(times) == 13


async def test_thredds_down(hass: HomeAssistant, aioclient_mock) -> None:
    mock_radar(aioclient_mock, {"20260926": 503, "20260927": 503})
    entry = await setup(hass)

    # El radar queda no disponible; el resto de MeteoGal funciona.
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(RADAR).state == "unavailable"
    assert hass.states.get("weather.santiago_de_compostela").state != "unavailable"


async def test_options(hass: HomeAssistant, aioclient_mock) -> None:
    mock_radar(aioclient_mock, {"20260927": radar_steps("00:05", "20:45")})
    entry = await setup(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"radar_hours": "6", "radar_zoom": "galicia"}
    )
    await hass.async_block_till_done()

    assert entry.options == {"radar_hours": "6", "radar_zoom": "galicia"}
    radar = entry.runtime_data.radar
    # 6 h, una pasada cada 30 min: 13 pasadas, de 14:45 a 20:45.
    assert (radar.period, radar.step) == (timedelta(hours=6), timedelta(minutes=30))
    last_setup = get_maps(aioclient_mock)[-13:]
    assert last_setup[0].query["time"] == "2026-09-27T14:45:00Z"
    # Toda Galicia, no alrededor de la ubicación.
    assert last_setup[0].query["bbox"] == "41.75,-9.45,43.85,-6.65"


def test_select_times() -> None:
    from custom_components.meteogal.coordinator import RadarCoordinator

    times = [
        datetime(2026, 9, 27, 18, 5, tzinfo=UTC) + timedelta(minutes=10 * n)
        for n in range(17)
    ]  # 18:05 a 20:45
    coordinator = RadarCoordinator.__new__(RadarCoordinator)
    coordinator.period = timedelta(hours=3)
    coordinator.step = timedelta(minutes=20)

    selected = coordinator.select_times(times)

    # Solo hay datos desde las 18:05: de 18:05 a 20:45 cada 20 min.
    assert selected[-1] == times[-1]
    assert all(b - a == timedelta(minutes=20) for a, b in pairwise(selected))
    assert selected[0] == datetime(2026, 9, 27, 18, 5, tzinfo=UTC)
