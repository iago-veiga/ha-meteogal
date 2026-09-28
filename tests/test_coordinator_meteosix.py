"""Tests del coordinador de MeteoSIX (respuestas reales del 2026-09-27)."""

from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntryState,
    ConfigSubentry,
    ConfigSubentryData,
)
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meteogal.api import MeteoSixHour
from custom_components.meteogal.api.meteosix import MAX_POINTS
from custom_components.meteogal.const import DOMAIN
from custom_components.meteogal.coordinator import MeteoSixCoordinator

from .api.conftest import (
    METEOSIX_BAD_KEY,
    METEOSIX_DOWN_KEY,
    METEOSIX_FORECAST,
    METEOSIX_KEY,
    SANTIAGO,
    load,
    mock_meteogalicia,
    mock_meteosix,
)

CEST = timezone(timedelta(hours=2))

# Hora de las respuestas guardadas de MeteoSIX (petición a las 11:09).
pytestmark = pytest.mark.freeze_time("2026-09-27T11:10:00+02:00")


def location(title: str = "Santiago de Compostela") -> ConfigSubentryData:
    return ConfigSubentryData(
        subentry_type="location",
        title=title,
        data={
            "latitude": 42.8805,
            "longitude": -8.5456,
            "concello_id": SANTIAGO,
            "station_id": None,
        },
        unique_id=None,
    )


async def setup(hass: HomeAssistant, data: dict) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="MeteoGal", data=data, subentries_data=[location()]
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def meteosix_calls(aioclient_mock) -> list:
    return [
        url
        for _, url, _, _ in aioclient_mock.mock_calls
        if str(url).startswith(METEOSIX_FORECAST)
    ]


@pytest.fixture(autouse=True)
def mock_services(aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)
    mock_meteosix(aioclient_mock)


async def test_without_key(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await setup(hass, {})

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.meteosix is None
    assert not meteosix_calls(aioclient_mock)


async def test_with_key(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await setup(hass, {"api_key": METEOSIX_KEY})

    assert entry.state is ConfigEntryState.LOADED
    coordinator = entry.runtime_data.meteosix
    assert coordinator.last_update_success
    (subentry_id,) = entry.subentries
    hours = coordinator.data[subentry_id]
    assert len(hours) == 87
    assert hours[0].time == datetime(2026, 9, 27, 12, tzinfo=CEST)
    # Una sola petición, con la ubicación de la subentrada.
    (url,) = meteosix_calls(aioclient_mock)
    assert url.query["coords"] == "-8.5456,42.8805"


async def test_rejected_key_starts_reauth(hass: HomeAssistant) -> None:
    entry = await setup(hass, {"api_key": METEOSIX_BAD_KEY})

    # Los datos públicos siguen funcionando.
    assert entry.state is ConfigEntryState.LOADED
    assert not entry.runtime_data.meteosix.last_update_success
    (flow,) = entry.async_get_active_flows(hass, {SOURCE_REAUTH})
    assert flow["step_id"] == "reauth_confirm"


async def test_meteosix_down(hass: HomeAssistant) -> None:
    entry = await setup(hass, {"api_key": METEOSIX_DOWN_KEY})

    assert entry.state is ConfigEntryState.LOADED
    assert not entry.runtime_data.meteosix.last_update_success
    assert not list(entry.async_get_active_flows(hass, {SOURCE_REAUTH}))


async def test_location_without_data(hass: HomeAssistant, aioclient_mock) -> None:
    # MeteoSIX responde 217 solo para ese punto.
    forecast = load("meteosix_forecast.json")
    forecast["features"] = forecast["features"][2:]
    aioclient_mock.clear_requests()
    aioclient_mock.get(METEOSIX_FORECAST, json=forecast)
    mock_meteogalicia(aioclient_mock)

    entry = await setup(hass, {"api_key": METEOSIX_KEY})

    coordinator = entry.runtime_data.meteosix
    assert coordinator.last_update_success
    assert coordinator.data == {}


class FakeMeteoSix:
    """Devuelve una hora por punto y apunta cuántos puntos van en cada petición."""

    def __init__(self) -> None:
        self.batches: list[int] = []

    async def get_forecast(self, points):
        self.batches.append(len(points))
        return [
            [MeteoSixHour(time=datetime(2026, 9, 27, 12, tzinfo=CEST), model_run=None)]
            for _ in points
        ]


async def test_more_locations_than_one_request(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"api_key": METEOSIX_KEY})
    entry.add_to_hass(hass)
    subentries = [
        ConfigSubentry(**location(f"Ubicación {n}")) for n in range(MAX_POINTS + 1)
    ]
    client = FakeMeteoSix()
    coordinator = MeteoSixCoordinator(hass, entry, subentries, client)

    await coordinator.async_refresh()

    assert client.batches == [MAX_POINTS, 1]
    assert set(coordinator.data) == {s.subentry_id for s in subentries}
