"""Tests de la búsqueda de concello y estación por coordenadas."""

import re
import unicodedata

import pytest

from custom_components.meteogal.api.client import _parse_stations
from custom_components.meteogal.geo import (
    ConcelloLocator,
    distance_km,
    nearest_station,
)

from .api.conftest import load


@pytest.fixture(scope="module")
def locator() -> ConcelloLocator:
    return ConcelloLocator.load()


@pytest.fixture(scope="module")
def stations():
    return _parse_stations(load("listaEstacionsMeteo.json"))


@pytest.mark.parametrize(
    ("latitude", "longitude", "concello_id"),
    [
        (42.8805, -8.5456, 15078),  # Santiago, praza do Obradoiro
        (42.2406, -8.7207, 36057),  # Vigo, centro
        (43.0097, -7.5560, 27028),  # Lugo, centro
        (42.3358, -7.8639, 32054),  # Ourense, centro
    ],
)
def test_inside(locator, latitude, longitude, concello_id) -> None:
    assert locator.locate(latitude, longitude) == concello_id


def test_sea_near_coast_uses_nearest(locator) -> None:
    # Estación de Illas Cíes: cae fuera del contorno simplificado de la costa.
    assert locator.locate(42.221944, -8.905278) == 36057


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (40.4168, -3.7038),  # Madrid
        (43.0, -10.5),  # Atlántico, lejos de la costa
    ],
)
def test_outside_galicia(locator, latitude, longitude) -> None:
    assert locator.locate(latitude, longitude) is None


def test_neighbour_municipality_is_outside(locator) -> None:
    # Vegadeo (Asturias), a menos de 2 km de Ribadeo al otro lado del Eo.
    assert locator.locate(43.4697, -7.0496) is None


def test_portugal_near_border_goes_to_nearest(locator) -> None:
    # Valença (Portugal): Portugal no está en los datos y cae a <2 km de Tui.
    assert locator.locate(42.0283, -8.6440) == 36055


def test_every_concello_is_loaded(locator) -> None:
    concellos = load("jsonConcellosNivelMax.json")["listaDiaConcellos"][0]
    expected = {c["idConcello"] for c in concellos["listaNiveisMaximos"]}
    assert {area.concello_id for area in locator._areas} == expected


def test_stations_match_their_concello(locator, stations) -> None:
    """Cada estación dice su concello: sirve de validación con datos reales.

    Referencia (2026-09-27): 152 de 155. Dos de los fallos son errores de MeteoGalicia
    (Fragavella y Xinzo: el IGN a resolución completa nos da la razón); el otro,
    Río do Sol, está pegado al límite entre Coristanco y Tordoia.
    """
    concellos = load("jsonConcellosNivelMax.json")["listaDiaConcellos"][0]
    names = {
        c["idConcello"]: c["nomeConcello"] for c in concellos["listaNiveisMaximos"]
    }

    matches = sum(
        1
        for s in stations
        if _normalize(names.get(locator.locate(s.latitude, s.longitude), ""))
        == _normalize(s.concello)
    )

    assert matches >= 152


def test_nearest_station(stations) -> None:
    station, distance = nearest_station(42.8805, -8.5456, stations)

    assert station.concello == "SANTIAGO DE COMPOSTELA"
    assert distance < 5


def test_nearest_station_at_station(stations) -> None:
    target = stations[10]

    station, distance = nearest_station(target.latitude, target.longitude, stations)

    assert station == target
    assert distance == 0


def test_nearest_station_without_stations() -> None:
    assert nearest_station(42.88, -8.54, []) is None


def test_distance_km() -> None:
    # Santiago - A Coruña, en línea recta.
    assert distance_km(42.8805, -8.5456, 43.3623, -8.4115) == pytest.approx(54.6, abs=1)


def _normalize(name: str) -> str:
    """ "Coruña (A)" (lista de concellos) y "A CORUÑA" (estaciones) → "A CORUNA"."""
    decomposed = unicodedata.normalize("NFD", name.upper())
    plain = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    if match := re.fullmatch(r"(.+) \((A|O|AS|OS)\)", plain):
        return f"{match[2]} {match[1]}"
    return plain
