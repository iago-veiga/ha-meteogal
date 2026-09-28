"""Tests de la tabla de códigos (anexos II y III de JSON_Pred_Concello)."""

import pytest

from custom_components.meteogal.codes import (
    condition,
    wind_bearing,
    wind_intensity,
)

DAY_CODES = range(101, 126)
NIGHT_CODES = range(201, 226)


@pytest.mark.parametrize("code", [*DAY_CODES, *NIGHT_CODES])
def test_every_documented_sky_code_has_condition(code: int) -> None:
    assert condition(code) is not None


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (101, "sunny"),
        (201, "clear-night"),
        (103, "partlycloudy"),
        (203, "partlycloudy"),
        (105, "cloudy"),
        (205, "cloudy"),
        (106, "fog"),
        (111, "rainy"),
        (112, "snowy"),
        (113, "lightning-rainy"),
        (119, "lightning"),
        (120, "snowy-rainy"),
        (121, "hail"),
    ],
)
def test_condition(code: int, expected: str) -> None:
    assert condition(code) == expected


@pytest.mark.parametrize("code", [None, -9999, 0, 100, 126, 226, 301])
def test_unknown_sky_code(code) -> None:
    assert condition(code) is None


@pytest.mark.parametrize(
    ("code", "bearing", "intensity"),
    [
        (299, None, 0),  # calma
        (300, None, 1),  # variable
        (301, 0.0, 1),  # flojo del norte
        (302, 45.0, 1),  # flojo del nordés
        (308, 315.0, 1),  # flojo del noroeste
        (309, 0.0, 2),  # moderado del norte
        (315, 270.0, 2),  # moderado del oeste
        (321, 180.0, 3),  # fuerte del sur
        (332, 315.0, 4),  # muy fuerte del noroeste
        (-9999, None, None),
        (None, None, None),
        (333, None, None),
    ],
)
def test_wind(code, bearing, intensity) -> None:
    assert wind_bearing(code) == bearing
    assert wind_intensity(code) == intensity
