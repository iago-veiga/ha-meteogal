"""Avisos meteorológicos: sensores de nivel, contadores y acción `get_warnings`.

Respuesta real de Muxía (2026-09-27): dos avisos amarillos el martes 29, racha
máxima de viento de 12 a 18 h y lluvia en 12 horas de 12 a 24 h.
"""

from dataclasses import replace
from datetime import datetime

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceNotSupported
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.meteogal.api import WarningText, WeatherWarning
from custom_components.meteogal.api.client import (
    TIMEZONE,
    _parse_warning_texts,
    _parse_warnings,
)
from custom_components.meteogal.const import DOMAIN
from custom_components.meteogal.sensor import WarningLevelSensor
from custom_components.meteogal.warnings import (
    active,
    concello_zones,
    describe,
    highest_level,
    load_zones,
    next_change,
    sort_warnings,
    upcoming,
)

from .api.conftest import (
    FIXTURES,
    SANTIAGO,
    WARNING_TEXTS,
    WARNINGS,
    load,
    mock_meteogalicia,
)

LEVEL = "sensor.santiago_de_compostela_warning_level"
UPCOMING_LEVEL = "sensor.santiago_de_compostela_upcoming_warning_level"
ACTIVE_COUNT = "sensor.santiago_de_compostela_active_warnings"
UPCOMING_COUNT = "sensor.santiago_de_compostela_upcoming_warnings"


def at(day: int, hour: int) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=TIMEZONE)


def warning(id_: int, level: int, start: datetime, end: datetime, type_id=8):
    return WeatherWarning(id=id_, type_id=type_id, level=level, start=start, end=end)


@pytest.fixture(autouse=True)
def services(aioclient_mock) -> None:
    # Los avisos de Muxía para la ubicación de Santiago; el resto, Santiago.
    aioclient_mock.get(
        WARNINGS,
        params={"idConcello": SANTIAGO, "dia": -1},
        json=load("jsonAvisosConcellos_15053.json"),
    )
    mock_meteogalicia(aioclient_mock)


async def setup(hass: HomeAssistant) -> MockConfigEntry:
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
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def move_to(hass: HomeAssistant, freezer, when: str) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.freeze_time("2026-09-29T10:00:00+02:00")
async def test_warnings_through_the_day(hass: HomeAssistant, freezer) -> None:
    entry = await setup(hass)
    registry = er.async_get(hass)
    for entity_id in (ACTIVE_COUNT, UPCOMING_COUNT):
        registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    # 10:00: los dos avisos están emitidos pero aún no empezaron.
    assert hass.states.get(LEVEL).state == "none"
    assert hass.states.get(LEVEL).attributes.get("type") is None
    upcoming_level = hass.states.get(UPCOMING_LEVEL)
    assert upcoming_level.state == "yellow"
    # A igual nivel, el principal es el que acaba antes: el viento (18 h).
    assert upcoming_level.attributes["type"] == "wind_gust"
    assert upcoming_level.attributes["level"] == "yellow"
    assert upcoming_level.attributes["start"] == "2026-09-29T12:00:00+02:00"
    assert upcoming_level.attributes["end"] == "2026-09-29T18:00:00+02:00"
    assert upcoming_level.attributes["warning_id"] == 815130500
    assert hass.states.get(ACTIVE_COUNT).state == "0"
    assert hass.states.get(UPCOMING_COUNT).state == "2"

    # 12:00 en punto: empiezan los dos.
    await move_to(hass, freezer, "2026-09-29T12:00:00+02:00")
    level = hass.states.get(LEVEL)
    assert level.state == "yellow"
    assert level.attributes["type"] == "wind_gust"
    assert hass.states.get(UPCOMING_LEVEL).state == "none"
    assert hass.states.get(ACTIVE_COUNT).state == "2"

    # 18:00 en punto: acaba el viento, sigue la lluvia.
    await move_to(hass, freezer, "2026-09-29T18:00:00+02:00")
    level = hass.states.get(LEVEL)
    assert level.state == "yellow"
    assert level.attributes["type"] == "rain_12h"
    assert hass.states.get(ACTIVE_COUNT).state == "1"

    # Medianoche: sin avisos.
    await move_to(hass, freezer, "2026-09-30T00:00:00+02:00")
    assert hass.states.get(LEVEL).state == "none"
    assert hass.states.get(ACTIVE_COUNT).state == "0"


@pytest.mark.freeze_time("2026-09-29T11:59:00+02:00")
async def test_change_on_time_without_new_data(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    await setup(hass)
    calls = aioclient_mock.call_count

    # Un minuto después (lejos del siguiente refresco): el estado cambia solo.
    await move_to(hass, freezer, "2026-09-29T12:00:00+02:00")

    assert hass.states.get(LEVEL).state == "yellow"
    assert aioclient_mock.call_count == calls


@pytest.mark.freeze_time("2026-09-29T13:00:00+02:00")
async def test_get_warnings_action(hass: HomeAssistant) -> None:
    await setup(hass)

    response = await hass.services.async_call(
        DOMAIN,
        "get_warnings",
        target={"entity_id": LEVEL},
        blocking=True,
        return_response=True,
    )

    assert response == {
        LEVEL: {
            "warnings": [
                {
                    "type": "wind_gust",
                    "level": "yellow",
                    "start": "2026-09-29T12:00:00+02:00",
                    "end": "2026-09-29T18:00:00+02:00",
                    "warning_id": 815130500,
                    "description": None,
                    "zone": None,
                    "active": True,
                },
                {
                    "type": "rain_12h",
                    "level": "yellow",
                    "start": "2026-09-29T12:00:00+02:00",
                    "end": "2026-09-30T00:00:00+02:00",
                    "warning_id": 1360271719,
                    "description": None,
                    "zone": None,
                    "active": True,
                },
            ]
        }
    }


@pytest.mark.freeze_time("2026-09-27T12:00:00+02:00")
async def test_no_warnings(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        WARNINGS,
        params={"idConcello": SANTIAGO, "dia": -1},
        json=load("jsonAvisosConcellos_unknown.json"),
    )
    mock_meteogalicia(aioclient_mock)
    await setup(hass)

    assert hass.states.get(LEVEL).state == "none"
    assert hass.states.get(UPCOMING_LEVEL).state == "none"
    assert hass.states.get(LEVEL).attributes.get("type") is None


@pytest.mark.freeze_time("2026-09-29T13:00:00+02:00")
async def test_failed_update_keeps_warnings(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await setup(hass)

    aioclient_mock.clear_requests()
    aioclient_mock.get(WARNINGS, params={"idConcello": SANTIAGO, "dia": -1}, status=503)
    mock_meteogalicia(aioclient_mock)
    await entry.runtime_data.locations[next(iter(entry.subentries))].async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(LEVEL).state == "yellow"


@pytest.mark.freeze_time("2026-09-29T13:00:00+02:00")
async def test_entities(hass: HomeAssistant) -> None:
    entry = await setup(hass)
    (subentry_id,) = entry.subentries
    registry = er.async_get(hass)

    weather = registry.async_get("weather.santiago_de_compostela")
    for entity_id, key, enabled in (
        (LEVEL, "warning_level", True),
        (UPCOMING_LEVEL, "upcoming_warning_level", True),
        (ACTIVE_COUNT, "active_warnings", False),
        (UPCOMING_COUNT, "upcoming_warnings", False),
    ):
        entity = registry.async_get(entity_id)
        assert entity.unique_id == f"{subentry_id}_{key}"
        assert entity.device_id == weather.device_id
        assert (entity.disabled_by is None) is enabled
    level = hass.states.get(LEVEL)
    assert level.attributes["device_class"] == "enum"
    assert level.attributes["options"] == ["none", "yellow", "orange", "red"]
    # Los atributos no se guardan en la base de datos.
    assert WarningLevelSensor._unrecorded_attributes == frozenset({MATCH_ALL})


def test_sorting_and_levels() -> None:
    now = at(29, 13)
    wind = warning(1, 1, at(29, 12), at(29, 18))
    rain = warning(2, 1, at(29, 12), at(30, 0), type_id=4)
    red_waves = warning(3, 3, at(29, 12), at(30, 12), type_id=10)
    tomorrow = warning(4, 2, at(30, 6), at(30, 12))

    # El más grave primero, aunque acabe más tarde.
    assert sort_warnings([wind, rain, red_waves]) == [red_waves, wind, rain]
    assert active([wind, rain, red_waves, tomorrow], now) == [red_waves, wind, rain]
    assert upcoming([wind, tomorrow], now) == [tomorrow]
    assert highest_level([wind, red_waves]) == "red"
    assert highest_level([]) == "none"
    assert next_change([wind, rain, tomorrow], now) == at(29, 18)
    assert next_change([], now) is None


@pytest.mark.freeze_time("2026-09-29T13:00:00+02:00")
async def test_get_warnings_only_on_warning_level(hass: HomeAssistant) -> None:
    """Un sensor que no es de nivel de aviso da el error estándar de HA."""
    entry = await setup(hass)
    er.async_get(hass).async_update_entity(ACTIVE_COUNT, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceNotSupported):
        await hass.services.async_call(
            DOMAIN,
            "get_warnings",
            target={"entity_id": ACTIVE_COUNT},
            blocking=True,
            return_response=True,
        )


# --- Comentario de cada aviso (RSS por zonas), respuestas reales del 2026-09-29 ---


def rss_warnings(concello: int) -> list[WeatherWarning]:
    return _parse_warnings(load(f"jsonAvisosConcellos_{concello}_rss.json"))


def rss_texts(locale: str = "es") -> list[WarningText]:
    return _parse_warning_texts(
        (FIXTURES / f"rssAdversos_{locale}.xml").read_text(encoding="utf-8")
    )


def described(concello: int, locale: str = "es") -> dict:
    zones = concello_zones(concello, load_zones())
    return {
        (w.type_id, w.level, w.start.hour, w.end.hour): (w.description, w.zone)
        for w in describe(rss_warnings(concello), rss_texts(locale), zones)
    }


def test_parse_warning_texts() -> None:
    texts = rss_texts()
    assert len(texts) == 16
    rain = next(t for t in texts if t.type_id == 3 and t.zone_id == 322)
    assert rain.zone_name == "Oeste de A Coruña"
    assert rain.level == 2
    assert rain.start == at(29, 18)
    assert rain.end == at(29, 21)
    assert rain.comment == "Lluvia de más de 30 litros/m2 en una hora."


def test_zones_of_a_concello() -> None:
    zones = load_zones()
    assert len(zones) == 313
    # A Coruña: su zona, Noroeste de A Coruña, la provincia y Galicia.
    assert concello_zones(15030, zones) == [213, 321, 316, 320]
    assert concello_zones(27045, zones)[2] == 317  # Pedrafita: Lugo


def test_describe_a_coruna() -> None:
    """Los dos avisos de A Coruña salen del tramo de la provincia."""
    assert described(15030) == {
        (3, 1, 18, 21): (
            "LLuvias de más de 15 l/m2 en una hora.",
            "A Coruña (provincia)",
        ),
        (8, 1, 9, 21): ("Rachas superando los 80 km/h.", "A Coruña (provincia)"),
    }


def test_describe_cee() -> None:
    """Cee: el mismo tipo y hora con dos niveles, cada uno con el suyo (la
    agrupación para el naranja, la provincia para el amarillo). La racha naranja de
    12 a 18 ya no está en el RSS: sin comentario."""
    assert described(15023) == {
        (8, 2, 12, 18): (None, None),
        (8, 1, 9, 21): ("Rachas superando los 80 km/h.", "A Coruña (provincia)"),
        (3, 1, 18, 21): (
            "LLuvias de más de 15 l/m2 en una hora.",
            "A Coruña (provincia)",
        ),
        (3, 2, 18, 21): (
            "Lluvia de más de 30 litros/m2 en una hora.",
            "Oeste de A Coruña",
        ),
        (4, 1, 12, 0): ("Lluvia de más de 40 litros/m2.", "Oeste de A Coruña"),
    }


def test_describe_in_galician() -> None:
    comment, zone = described(15030, "gl")[(8, 1, 9, 21)]
    assert zone == "A Coruña (provincia)"
    assert comment and "80 km/h" in comment
    assert comment != "Rachas superando los 80 km/h."


def test_describe_other_zone_or_marine() -> None:
    """Un tramo de otra zona no vale; los de mar, sí, si todos dicen lo mismo."""
    texts = [
        WarningText(
            type_id=8,
            zone_id=332,
            zone_name="Montaña de Ourense",
            level=1,
            start=at(29, 9),
            end=at(29, 21),
            comment="Rachas superando los 80 km/h.",
        ),
        WarningText(
            type_id=9,
            zone_id=342,
            zone_name="Coruña Noroeste (mar+costa)",
            level=1,
            start=at(29, 15),
            end=at(29, 21),
            comment="Viento del sur, fuerza 7.",
        ),
    ]
    zones = concello_zones(15030, load_zones())
    gust = warning(1, 1, at(29, 9), at(29, 21))
    sea = warning(2, 1, at(29, 15), at(29, 21), type_id=9)
    result = describe([gust, sea], texts, zones)
    assert result[0].description is None
    assert (result[1].description, result[1].zone) == (
        "Viento del sur, fuerza 7.",
        "Coruña Noroeste (mar+costa)",
    )
    # Dos zonas de mar con textos distintos: no se sabe cuál es.
    texts.append(replace(texts[1], zone_id=400, comment="Viento del sur, fuerza 8."))
    assert describe([sea], texts, zones)[0].description is None


A_CORUNA = "sensor.a_coruna_warning_level"


async def setup_a_coruna(hass: HomeAssistant, aioclient_mock, rss_down: bool) -> None:
    """A Coruña con sus avisos reales del 2026-09-29. Lo propio va antes que la
    simulación general: gana la primera respuesta que encaja."""
    await hass.config.async_set_time_zone("Europe/Madrid")
    aioclient_mock.clear_requests()
    if rss_down:
        aioclient_mock.get(WARNING_TEXTS, status=503)
    aioclient_mock.get(
        WARNINGS,
        params={"idConcello": 15030, "dia": -1},
        json=load("jsonAvisosConcellos_15030_rss.json"),
    )
    mock_meteogalicia(aioclient_mock)
    mock_meteogalicia(aioclient_mock, concello=15030)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="MeteoGal",
        data={},
        subentries_data=[
            ConfigSubentryData(
                subentry_type="location",
                title="A Coruña",
                data={
                    "latitude": 43.3665,
                    "longitude": -8.3735,
                    "concello_id": 15030,
                    "station_id": None,
                },
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.freeze_time("2026-09-29T19:00:00+02:00")
async def test_description_in_ha(hass: HomeAssistant, aioclient_mock) -> None:
    await setup_a_coruna(hass, aioclient_mock, rss_down=False)

    state = hass.states.get(A_CORUNA)
    assert state.state == "yellow"
    # Principal: la racha, que acaba a la vez que la lluvia pero empezó antes.
    assert state.attributes["type"] == "wind_gust"
    assert state.attributes["description"] == "Rachas superando los 80 km/h."
    assert state.attributes["zone"] == "A Coruña (provincia)"


@pytest.mark.freeze_time("2026-09-29T19:00:00+02:00")
async def test_description_rss_down(hass: HomeAssistant, aioclient_mock) -> None:
    """Sin RSS, los avisos siguen, sin comentario."""
    await setup_a_coruna(hass, aioclient_mock, rss_down=True)

    state = hass.states.get(A_CORUNA)
    assert state.state == "yellow"
    assert state.attributes["description"] is None
