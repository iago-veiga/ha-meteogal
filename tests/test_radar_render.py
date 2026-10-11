"""Dibujo del radar: escala propia, capas, rótulos y animación."""

from datetime import datetime
import io

from PIL import Image
import pytest

from custom_components.meteogal.api.radar import DBZ_MAX, DBZ_MIN
from custom_components.meteogal.radar import (
    FOOTER_HEIGHT,
    LEVELS,
    NOTE_HEIGHT,
    RADAR_ALPHA,
    RADAR_POSITION,
    RELIABLE_KM,
    Marker,
    RadarRenderer,
    _colorize,
    animation,
    area_around,
    distance_km,
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

    assert frame.size == (area.width, area.height + renderer.footer_height)
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


def test_distance_to_the_radar() -> None:
    assert distance_km(*RADAR_POSITION) == 0
    # De Cuntis a A Coruña: ~77 km al norte y 18 al este.
    assert distance_km(*CORUNA) == pytest.approx(79, abs=3)


def test_far_zone_is_marked() -> None:
    """A más de 100 km del radar: rayas, círculo y una línea más en la franja."""
    area = area_around(*CORUNA, 100)
    renderer = RadarRenderer(area, square(area), [Marker(*CORUNA, main=True)], "es")
    assert renderer.far
    assert renderer.footer_height == FOOTER_HEIGHT + NOTE_HEIGHT
    # Sin radar (transparente), se ve el mapa: rayas en la esquina lejana, y nada
    # cerca del radar.
    frame = renderer.frame(gray_png(200, alpha=0, size=(10, 10)), datetime(2026, 10, 1))
    far_corner = frame.crop((0, 0, 40, 40))
    near_radar = frame.crop(
        tuple(
            round(v)
            for v in (
                *(c - 12 for c in area.xy(*RADAR_POSITION)),
                *(c + 12 for c in area.xy(*RADAR_POSITION)),
            )
        )
    )
    hatch = (184, 186, 188)  # el mar con las rayas por encima
    assert hatch in [color for _, color in far_corner.getcolors(1000)]
    assert hatch not in [color for _, color in near_radar.getcolors(1000)]
    note = frame.crop((0, area.height + FOOTER_HEIGHT, area.width, frame.height))
    assert len(note.getcolors(1000)) > 2  # la nota escrita


def test_no_far_zone_close_to_the_radar() -> None:
    area = area_around(*RADAR_POSITION, RELIABLE_KM / 2)
    renderer = RadarRenderer(
        area, square(area), [Marker(*RADAR_POSITION, main=True)], "es"
    )
    assert not renderer.far
    assert renderer.footer_height == FOOTER_HEIGHT
    frame = renderer.frame(gray_png(200, alpha=0, size=(10, 10)), datetime(2026, 10, 1))
    assert frame.size == (area.width, area.height + FOOTER_HEIGHT)
