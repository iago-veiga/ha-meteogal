"""Sensores de MeteoSIX: lluvia de esta hora, próxima lluvia y cota de nieve.

Respuestas reales de MeteoSIX (Santiago, 2026-09-27, petición a las 11:09).
"""

from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.meteogal.api import MeteoSixHour
from custom_components.meteogal.api.client import TIMEZONE
from custom_components.meteogal.const import DOMAIN
from custom_components.meteogal.sensor import next_rain

from .api.conftest import (
    METEOSIX_DOWN_KEY,
    METEOSIX_KEY,
    SANTIAGO,
    mock_meteogalicia,
    mock_meteosix,
)

RAIN_THIS_HOUR = "sensor.santiago_de_compostela_rain_this_hour"
NEXT_RAIN = "sensor.santiago_de_compostela_next_rain"
SNOW_LEVEL = "sensor.santiago_de_compostela_snow_level"

pytestmark = pytest.mark.freeze_time("2026-09-27T11:10:00+02:00")


@pytest.fixture(autouse=True)
def services(aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)
    mock_meteosix(aioclient_mock)


async def setup(hass: HomeAssistant, data: dict) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="MeteoGal",
        data=data,
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
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_rain_sensors(hass: HomeAssistant) -> None:
    await setup(hass, {"api_key": METEOSIX_KEY})

    # De 11 a 12, nada.
    this_hour = hass.states.get(RAIN_THIS_HOUR)
    assert this_hour.state == "0.0"
    assert this_hour.attributes["unit_of_measurement"] == "mm"
    assert this_hour.attributes["device_class"] == "precipitation"
    # La primera lluvia: chubascos débiles de 15 a 16 (0,36 mm).
    next_rain = hass.states.get(NEXT_RAIN)
    assert next_rain.state == "2026-09-27T13:00:00+00:00"
    assert next_rain.attributes["device_class"] == "timestamp"


async def test_new_hour_moves_the_window(hass: HomeAssistant, freezer) -> None:
    await setup(hass, {"api_key": METEOSIX_KEY})

    # A las 15:00 ya llueve: la próxima lluvia es la hora en curso.
    freezer.move_to("2026-09-27T15:00:00+02:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(RAIN_THIS_HOUR).state == "0.36"
    assert hass.states.get(NEXT_RAIN).state == "2026-09-27T13:00:00+00:00"

    # A las 16:00 escampa; vuelve la llovizna de 18 a 19.
    freezer.move_to("2026-09-27T16:00:00+02:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(RAIN_THIS_HOUR).state == "0.0"
    assert hass.states.get(NEXT_RAIN).state == "2026-09-27T16:00:00+00:00"


async def test_snow_level_disabled_by_default(hass: HomeAssistant) -> None:
    await setup(hass, {"api_key": METEOSIX_KEY})

    entity = er.async_get(hass).async_get(SNOW_LEVEL)
    assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(SNOW_LEVEL) is None


async def test_snow_level(hass: HomeAssistant, freezer) -> None:
    registry = er.async_get(hass)
    entry = await setup(hass, {"api_key": METEOSIX_KEY})
    registry.async_update_entity(SNOW_LEVEL, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    # A las 11:00 MeteoSIX aún no tiene dato (empieza a las 12:00).
    assert hass.states.get(SNOW_LEVEL).state == STATE_UNKNOWN
    freezer.move_to("2026-09-27T12:00:00+02:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(SNOW_LEVEL).state == "2592.0"


async def test_same_device_and_stable_ids(hass: HomeAssistant) -> None:
    entry = await setup(hass, {"api_key": METEOSIX_KEY})
    (subentry_id,) = entry.subentries
    registry = er.async_get(hass)

    weather = registry.async_get("weather.santiago_de_compostela")
    for entity_id, key in (
        (RAIN_THIS_HOUR, "rain_this_hour"),
        (NEXT_RAIN, "next_rain"),
    ):
        entity = registry.async_get(entity_id)
        assert entity.unique_id == f"{subentry_id}_{key}"
        assert entity.device_id == weather.device_id
        assert entity.config_subentry_id == subentry_id


async def test_without_key_no_meteosix_sensors(hass: HomeAssistant) -> None:
    await setup(hass, {})

    registry = er.async_get(hass)
    for entity_id in (RAIN_THIS_HOUR, NEXT_RAIN, SNOW_LEVEL):
        assert registry.async_get(entity_id) is None
    # Los avisos no dependen de la clave.
    assert hass.states.get("sensor.santiago_de_compostela_warning_level")


async def test_meteosix_down(hass: HomeAssistant) -> None:
    await setup(hass, {"api_key": METEOSIX_DOWN_KEY})

    assert hass.states.get(RAIN_THIS_HOUR).state == STATE_UNAVAILABLE
    assert hass.states.get(NEXT_RAIN).state == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("amounts", "expected"),
    [([0, 0, 0], None), ([0, 0.05, 0.1], 2), ([0.1, 0, 0], 0)],
    ids=["dry", "below_threshold_then_rain", "raining_now"],
)
def test_next_rain(amounts: list[float], expected: int | None) -> None:
    """La lluvia de cada hora está en el dato de la hora siguiente."""
    start = datetime(2026, 9, 27, 11, tzinfo=TIMEZONE)
    hours = [
        MeteoSixHour(
            time=start + timedelta(hours=n + 1), model_run=None, precipitation=amount
        )
        for n, amount in enumerate(amounts)
    ]

    result = next_rain(hours, start)

    assert result == (None if expected is None else start + timedelta(hours=expected))
