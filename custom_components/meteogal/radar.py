"""Imágenes del radar: mapa propio, colores propios y animación (docs/radar.md).

Sin nada de Home Assistant: recibe las pasadas en grises del WMS de MeteoGalicia
y devuelve un WEBP animado y un PNG. Capas, de abajo arriba: fondo y concellos,
radar semitransparente, contornos de los concellos, ubicaciones, y hora, leyenda y
atribución en una franja aparte, para que con lluvia en todas partes se siga
viendo dónde está cada cosa.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import cache
import io
import math
from pathlib import Path
from typing import Final

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .api.radar import DBZ_MAX, DBZ_MIN, BBox

FONT_FILE: Final = Path(__file__).parent / "data" / "DejaVuSans-latin.ttf"

KM_PER_DEGREE: Final = 111.2
# Tamaño de la imagen centrada en una ubicación (cuadrada) y de la de Galicia.
AREA_SIZE: Final = 480
GALICIA: Final = BBox(south=41.75, west=-9.45, north=43.85, east=-6.65)

# Escala propia: desde qué dBZ empieza cada nivel. Por debajo del primero, nada
# (ecos débiles, ruido). Con Marshall-Palmer (Z = 200·R^1,6): 20 dBZ ≈ 0,6 mm/h,
# 28 ≈ 1,9, 35 ≈ 5,6, 42 ≈ 15, 48 ≈ 37 y 54 ≈ 87 mm/h.
LEVELS: Final = (
    ("light", 20.0, (70, 150, 245)),
    ("moderate", 28.0, (40, 190, 90)),
    ("heavy", 35.0, (250, 210, 40)),
    ("very_heavy", 42.0, (245, 130, 30)),
    ("intense", 48.0, (225, 40, 40)),
    ("torrential", 54.0, (170, 40, 190)),
)
RADAR_ALPHA: Final = 180  # ~70 % de opacidad

LABELS: Final = {
    "gl": ("feble", "moderada", "forte", "moi forte", "intensa", "torrencial"),
    "es": ("débil", "moderada", "fuerte", "muy fuerte", "intensa", "torrencial"),
    "en": ("light", "moderate", "heavy", "very heavy", "intense", "torrential"),
}
ATTRIBUTION: Final = "MeteoGalicia · CC BY-SA 4.0"

BACKGROUND: Final = (236, 238, 241, 255)  # mar y fuera de Galicia (sin distinguir)
LAND: Final = (226, 229, 219, 255)
BORDER: Final = (95, 95, 95, 255)
FOOTER: Final = (255, 255, 255, 255)
TEXT: Final = (30, 30, 30, 255)
FOOTER_HEIGHT: Final = 22


@dataclass(frozen=True, slots=True)
class Area:
    """Recuadro de la imagen y su tamaño en píxeles (proyección lat/lon)."""

    bbox: BBox
    width: int
    height: int

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        box = self.bbox
        return (
            (lon - box.west) / (box.east - box.west) * self.width,
            (box.north - lat) / (box.north - box.south) * self.height,
        )


def area_around(lat: float, lon: float, radius_km: float) -> Area:
    """Cuadrado de `radius_km` de radio (en km) centrado en el punto."""
    dlat = radius_km / KM_PER_DEGREE
    dlon = radius_km / (KM_PER_DEGREE * math.cos(math.radians(lat)))
    bbox = BBox(south=lat - dlat, west=lon - dlon, north=lat + dlat, east=lon + dlon)
    return Area(bbox, AREA_SIZE, AREA_SIZE)


def galicia_area() -> Area:
    box = GALICIA
    km_wide = (box.east - box.west) * KM_PER_DEGREE * math.cos(math.radians(42.8))
    km_high = (box.north - box.south) * KM_PER_DEGREE
    return Area(box, round(AREA_SIZE * km_wide / km_high), AREA_SIZE)


@dataclass(frozen=True, slots=True)
class Marker:
    latitude: float
    longitude: float
    main: bool  # la ubicación de la imagen; el resto, más discretas


class RadarRenderer:
    """Dibuja las pasadas de un recuadro. El mapa se prepara una sola vez."""

    def __init__(
        self,
        area: Area,
        polygons: Iterable[Sequence[Sequence[tuple[float, float]]]],
        markers: Iterable[Marker],
        language: str,
    ) -> None:
        self.area = area
        rings = [
            [area.xy(lat, lon) for lon, lat in ring]
            for polygon in polygons
            for ring in polygon
        ]
        self._base = Image.new("RGBA", (area.width, area.height), BACKGROUND)
        draw = ImageDraw.Draw(self._base)
        for ring in rings:
            draw.polygon(ring, fill=LAND)
        self._overlay = Image.new("RGBA", (area.width, area.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(self._overlay)
        for ring in rings:
            draw.line([*ring, ring[0]], fill=BORDER, width=1)
        for marker in sorted(markers, key=lambda m: m.main):
            _draw_marker(draw, area.xy(marker.latitude, marker.longitude), marker.main)
        self._labels = LABELS.get(language.split("-")[0], LABELS["en"])

    def frame(self, gray_png: bytes, local_time: datetime) -> Image.Image:
        """Una pasada: mapa, radar con nuestros colores, contornos y rótulos."""
        radar = _colorize(Image.open(io.BytesIO(gray_png)))
        if radar.size != self._base.size:
            radar = radar.resize(self._base.size)
        image = self._base.copy()
        image.alpha_composite(radar)
        image.alpha_composite(self._overlay)
        return self._with_footer(image, local_time).convert("RGB")

    def _with_footer(self, image: Image.Image, local_time: datetime) -> Image.Image:
        width, height = image.size
        out = Image.new("RGBA", (width, height + FOOTER_HEIGHT), FOOTER)
        out.paste(image, (0, 0))
        draw = ImageDraw.Draw(out)
        font = _font(11)
        y = height + 5
        draw.text((6, y - 1), local_time.strftime("%H:%M"), fill=TEXT, font=_font(12))
        x = 50.0
        for (_, _, color), label in zip(LEVELS, self._labels, strict=True):
            draw.rectangle((x, y + 1, x + 9, y + 10), fill=color)
            draw.text((x + 12, y), label, fill=TEXT, font=font)
            x += 12 + draw.textlength(label, font=font) + 7
        small = _font(9)
        draw.text(
            (width - 4 - draw.textlength(ATTRIBUTION, font=small), 3),
            ATTRIBUTION,
            fill=TEXT,
            font=small,
            stroke_width=2,
            stroke_fill=FOOTER,
        )
        return out


def animation(frames: Sequence[Image.Image], frame_ms: int = 500) -> bytes:
    """WEBP animado; el último fotograma se queda un poco más antes de repetir."""
    buffer = io.BytesIO()
    durations = [frame_ms] * (len(frames) - 1) + [frame_ms * 4]
    frames[0].save(
        buffer,
        "WEBP",
        save_all=True,
        append_images=list(frames[1:]),
        duration=durations,
        loop=0,
        quality=80,
    )
    return buffer.getvalue()


def still(frame: Image.Image) -> bytes:
    buffer = io.BytesIO()
    frame.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def level_for(dbz: float) -> int | None:
    """Índice del nivel de la escala para una reflectividad, o None si no llega."""
    index = None
    for position, (_, start, _) in enumerate(LEVELS):
        if dbz >= start:
            index = position
    return index


@cache
def _lookup() -> tuple[list[int], list[int], list[int], list[int]]:
    """Gris del WMS (0-255) → color de nuestra escala y opacidad."""
    red, green, blue, alpha = [], [], [], []
    for gray in range(256):
        level = level_for(DBZ_MIN + gray / 255 * (DBZ_MAX - DBZ_MIN))
        color = LEVELS[level][2] if level is not None else (0, 0, 0)
        red.append(color[0])
        green.append(color[1])
        blue.append(color[2])
        alpha.append(RADAR_ALPHA if level is not None else 0)
    return red, green, blue, alpha


def _colorize(gray: Image.Image) -> Image.Image:
    luminance, transparency = gray.convert("LA").split()
    red, green, blue, alpha = _lookup()
    opacity = ImageChops.multiply(luminance.point(alpha), transparency)
    return Image.merge(
        "RGBA",
        (luminance.point(red), luminance.point(green), luminance.point(blue), opacity),
    )


def _draw_marker(
    draw: ImageDraw.ImageDraw, xy: tuple[float, float], main: bool
) -> None:
    x, y = xy
    if main:
        draw.ellipse(
            (x - 4, y - 4, x + 4, y + 4), fill="white", outline="black", width=2
        )
    else:
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), outline="black", width=1)


@cache
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_FILE), size)
