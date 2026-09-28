"""Dibujo del radar: escala propia, capas, rótulos y animación."""

from datetime import datetime
import io

from PIL import Image
import pytest

from custom_components.meteogal.api.radar import DBZ_MAX, DBZ_MIN
from custom_components.meteogal.radar import (
    FOOTER_HEIGHT,
    LEVELS,
    RADAR_ALPHA,
    Marker,
    RadarRenderer,
    _colorize,
    animation,
    area_around,
    galicia_area,
    level_for,
    still,
)

from .api.conftest import RADAR_FRAME

CORUNA = (43.3623, -8.4115)


def gray_for(dbz: float) -> int:
    return round((dbz - DBZ_MIN) / (DBZ_MAX - DBZ_MIN) * 255)


def gray_png(value: int, alpha: int = 255, size=(4, 4)) -> bytes:
    buffer = io.BytesIO()
    Image.new("LA", size, (value, alpha)).convert("RGBA").save(buffer, "PNG")
    return buffer.getvalue()


# Un cuadrado de tierra que ocupa todo el recuadro, para no depender del IGN.
def square(area) -> list:
    box = area.bbox
    return [[[(box.west, box.south), (box.east, box.south), (box.east, box.north)]]]


@pytest.mark.parametrize(
    ("dbz", "level"),
    [
        (19.9, None),
        (20, "light"),
        (27.9, "light"),
        (28, "moderate"),
        (54, "torrential"),
    ],
)
def test_levels(dbz: float, level: str | None) -> None:
    index = level_for(dbz)
    assert (LEVELS[index][0] if index is not None else None) == level


def test_colorize_uses_our_scale() -> None:
    # 26 dBZ (lo que medía el radar en A Coruña): débil, al 70 % de opacidad.
    light = _colorize(Image.open(io.BytesIO(gray_png(gray_for(26)))))
    assert light.getpixel((0, 0)) == (*LEVELS[0][2], RADAR_ALPHA)
    heavy = _colorize(Image.open(io.BytesIO(gray_png(gray_for(40)))))
    assert heavy.getpixel((0, 0))[:3] == LEVELS[2][2]
    # Por debajo de la escala, o transparente en el WMS: nada.
    assert (
        _colorize(Image.open(io.BytesIO(gray_png(gray_for(15))))).getpixel((0, 0))[3]
        == 0
    )
    assert (
        _colorize(Image.open(io.BytesIO(gray_png(200, alpha=0)))).getpixel((0, 0))[3]
        == 0
    )


def test_frame_layers_and_footer() -> None:
    area = area_around(*CORUNA, 100)
    renderer = RadarRenderer(area, square(area), [Marker(*CORUNA, main=True)], "gl")

    # Lluvia torrencial en todas partes: la ubicación y los rótulos se siguen viendo.
    frame = renderer.frame(
        gray_png(gray_for(60), size=(10, 10)), datetime(2026, 9, 27, 22, 5)
    )

    assert frame.size == (area.width, area.height + FOOTER_HEIGHT)
    x, y = (round(v) for v in area.xy(*CORUNA))
    assert frame.getpixel((x, y)) == (255, 255, 255)  # centro del marcador
    assert frame.getpixel((x + 20, y)) != (255, 255, 255)  # radar alrededor
    footer = frame.crop((0, area.height, area.width, area.height + FOOTER_HEIGHT))
    assert len(footer.getcolors(10_000)) > 2  # hora y leyenda escritas


def test_real_frame_and_animation() -> None:
    area = area_around(*CORUNA, 100)
    renderer = RadarRenderer(area, square(area), [Marker(*CORUNA, main=True)], "es")
    frames = [
        renderer.frame(RADAR_FRAME.read_bytes(), datetime(2026, 9, 27, 22, 5 + n))
        for n in range(3)
    ]

    webp = Image.open(io.BytesIO(animation(frames)))
    assert webp.format == "WEBP"
    assert webp.n_frames == 3
    assert Image.open(io.BytesIO(still(frames[-1]))).format == "PNG"


def test_areas() -> None:
    area = area_around(*CORUNA, 100)
    assert area.width == area.height
    # 100 km de radio: ~1,8° de latitud de lado.
    assert area.bbox.north - area.bbox.south == pytest.approx(1.8, abs=0.01)
    galicia = galicia_area()
    assert galicia.bbox.south < 42 and galicia.bbox.north > 43.7
