"""Tests de los nombres oficiales de los concellos."""

import pytest

from custom_components.meteogal.geo import ConcelloLocator
from custom_components.meteogal.toponyms import load_toponyms

from .api.conftest import load


@pytest.fixture(scope="module")
def toponyms() -> dict[int, str]:
    return load_toponyms()


def test_same_concellos_as_meteogalicia(toponyms) -> None:
    concellos = load("jsonConcellosNivelMax.json")["listaDiaConcellos"][0]
    assert set(toponyms) == {c["idConcello"] for c in concellos["listaNiveisMaximos"]}


def test_same_concellos_as_boundaries(toponyms) -> None:
    assert set(toponyms) == {a.concello_id for a in ConcelloLocator.load()._areas}


@pytest.mark.parametrize(
    ("code", "name"),
    [
        # Artículo delante y minúsculas en las preposiciones.
        (15030, "A Coruña"),
        (15078, "Santiago de Compostela"),
        (32075, "San Cibrao das Viñas"),
        # MeteoGalicia: "Pontes De Garcáa Rodríguez (As)".
        (15070, "As Pontes de García Rodríguez"),
        # MeteoGalicia: "Pobra Do Caramiñal", sin artículo.
        (15067, "A Pobra do Caramiñal"),
        # Cambiados en el Nomenclátor de 2026.
        (36009, "A Caniza"),
        (36008, "Cangas de Morrazo"),
        (15071, "O Porto do Son"),
        (27002, "Alfoz do Castrodouro"),
        (27044, "Pastoriza"),
        (15902, "Oza Cesuras"),
        (36902, "Cerdedo Cotobade"),
    ],
)
def test_official_name(toponyms, code, name) -> None:
    assert toponyms[code] == name


def test_no_raw_formats(toponyms) -> None:
    for name in toponyms.values():
        assert "(" not in name
        assert name == name.strip()
        assert not name.isupper()
        assert " De " not in name and " Do " not in name and " Da " not in name
