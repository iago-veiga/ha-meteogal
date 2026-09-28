"""Diagnósticos: el estado de cada fuente, sin la clave ni las coordenadas."""

import json

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.meteogal.const import DOMAIN

from .api.conftest import (
    METEOSIX_KEY,
    mock_meteogalicia,
    mock_meteosix,
    mock_radar,
    radar_steps,
)

LATITUDE, LONGITUDE = 43.3665, -8.3735

pytestmark = pytest.mark.freeze_time("2026-09-27T21:45:00+00:00")


async def test_diagnostics(hass: HomeAssistant, hass_client, aioclient_mock) -> None:
    mock_meteogalicia(aioclient_mock)
    mock_meteogalicia(aioclient_mock, concello=15030)
    mock_meteosix(aioclient_mock)
    mock_radar(aioclient_mock, {"20260927": radar_steps("00:05", "21:35")})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="MeteoGal",
        data={"api_key": METEOSIX_KEY},
        options={"radar_hours": "1", "radar_zoom": "50"},
        subentries_data=[
            ConfigSubentryData(
                subentry_type="location",
                title="A Coruña",
                data={
                    "latitude": LATITUDE,
                    "longitude": LONGITUDE,
                    "concello_id": 15030,
                    "station_id": 14000,
                    "station_weather": True,
                    "camera_id": "Corunha",
                },
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    # Nada que identifique al usuario ni su clave.
    text = json.dumps(result)
    assert METEOSIX_KEY not in text
    assert str(LATITUDE) not in text and str(LONGITUDE) not in text
    assert result["entry"]["data"] == {"api_key": "**REDACTED**"}
    assert result["entry"]["meteosix_key"] is True
    assert result["entry"]["options"] == {"radar_hours": "1", "radar_zoom": "50"}

    (location,) = result["locations"]
    assert location["title"] == "A Coruña"
    assert location["data"]["latitude"] == "**REDACTED**"
    assert location["data"]["station_id"] == 14000
    assert location["forecast"]["last_update_success"] is True
    assert location["forecast"]["hourly"]["count"] == 96
    assert location["station"]["name"] == "Coruña-Dique"
    assert location["station"]["reading_time"] == "2026-09-27 21:40:00+00:00"
    assert location["station"]["reading"]["TA_AVG_1.5m"] == 17.03
    assert location["meteosix"]["count"] == 87
    assert location["radar"]["time"] == "2026-09-27 21:35:00+00:00"
    assert location["camera"]["name"] == "Coruña-Dique"
    assert result["radar"]["zoom"] == "50"
    assert result["radar"]["step"] == "0:10:00"
    assert result["cameras"]["count"] == 33  # dos pares comparten identificador
    assert result["meteosix"]["last_update_success"] is True
