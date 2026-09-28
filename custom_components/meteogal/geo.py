"""Concello y estación más cercanos a unas coordenadas.

Sin dependencias de Home Assistant. `ConcelloLocator.load()` lee un fichero: en Home
Assistant hay que llamarlo en el executor, no en el bucle de eventos.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import json
import math
from pathlib import Path

from .api.models import Station

DATA_FILE = Path(__file__).parent / "data" / "concellos.json"

# Si el punto no cae dentro de ningún concello (mar, puertos, islas, o por la
# simplificación de la costa) ni en un municipio vecino de Asturias, León o Zamora,
# se acepta el concello más cercano hasta esta distancia. Portugal no está en los
# datos: un punto portugués a menos de esta distancia se asigna al concello vecino.
MAX_NEAREST_KM = 2.0

# Los contornos se simplifican a ~100 m por separado, así que en la frontera con
# Asturias, León y Zamora pueden solaparse unos metros. Un punto que cae en un
# municipio vecino pero a menos de esta distancia de un concello se asigna al concello.
BORDER_TOLERANCE_KM = 0.25

_KM_PER_DEGREE_LAT = 110.57
_KM_PER_DEGREE_LON_EQUATOR = 111.32
_EARTH_RADIUS_KM = 6371.0

type _Ring = Sequence[Sequence[float]]
type _Polygon = Sequence[_Ring]


@dataclass(frozen=True, slots=True)
class _Area:
    concello_id: int | None  # None: municipio de fuera de Galicia
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    polygons: Sequence[_Polygon]

    def contains(self, lon: float, lat: float) -> bool:
        if not (
            self.min_lon <= lon <= self.max_lon and self.min_lat <= lat <= self.max_lat
        ):
            return False
        return any(_in_polygon(lon, lat, polygon) for polygon in self.polygons)

    def distance_km(self, lon: float, lat: float) -> float:
        return min(
            _distance_to_ring_km(lon, lat, ring)
            for polygon in self.polygons
            for ring in polygon
        )


def load_polygons(path: Path = DATA_FILE) -> list[list[list[tuple[float, float]]]]:
    """Todos los contornos para dibujar mapas: concellos de Galicia y municipios
    limítrofes. Polígonos de anillos de (longitud, latitud). Lee un fichero:
    bloquea."""
    data = json.loads(path.read_text(encoding="utf-8"))
    polygons = [
        polygon for polygons in data["concellos"].values() for polygon in polygons
    ]
    polygons += data.get("outside", [])
    return [
        [[tuple(point) for point in ring] for ring in polygon] for polygon in polygons
    ]


class ConcelloLocator:
    """Busca el concello de Galicia al que pertenece un punto."""

    def __init__(self, areas: Iterable[_Area], outside: Iterable[_Area] = ()) -> None:
        self._areas = tuple(areas)
        self._outside = tuple(outside)

    @classmethod
    def load(cls, path: Path = DATA_FILE) -> ConcelloLocator:
        """Carga los contornos (lee un fichero: bloquea)."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            (
                _area(int(concello_id), polygons)
                for concello_id, polygons in data["concellos"].items()
            ),
            (_area(None, [polygon]) for polygon in data.get("outside", [])),
        )

    def locate(self, latitude: float, longitude: float) -> int | None:
        """Código del concello del punto, o None si está fuera de Galicia."""
        for area in self._areas:
            if area.contains(longitude, latitude):
                return area.concello_id
        outside = any(area.contains(longitude, latitude) for area in self._outside)
        limit = BORDER_TOLERANCE_KM if outside else MAX_NEAREST_KM

        margin_lat = limit / _KM_PER_DEGREE_LAT
        margin_lon = limit / _km_per_degree_lon(latitude)
        candidates = [
            (area.distance_km(longitude, latitude), area.concello_id)
            for area in self._areas
            if area.min_lon - margin_lon <= longitude <= area.max_lon + margin_lon
            and area.min_lat - margin_lat <= latitude <= area.max_lat + margin_lat
        ]
        if not candidates:
            return None
        distance, concello_id = min(candidates, key=lambda c: c[0])
        return concello_id if distance <= limit else None


def nearest_station(
    latitude: float, longitude: float, stations: Iterable[Station]
) -> tuple[Station, float] | None:
    """Estación más cercana y su distancia en km, o None si no hay estaciones."""
    return min(
        (
            (
                station,
                distance_km(latitude, longitude, station.latitude, station.longitude),
            )
            for station in stations
        ),
        key=lambda item: item[1],
        default=None,
    )


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en km entre dos puntos (haversine)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _area(concello_id: int | None, polygons: Sequence[_Polygon]) -> _Area:
    lons = [point[0] for polygon in polygons for point in polygon[0]]
    lats = [point[1] for polygon in polygons for point in polygon[0]]
    return _Area(concello_id, min(lons), min(lats), max(lons), max(lats), polygons)


def _in_polygon(lon: float, lat: float, polygon: _Polygon) -> bool:
    """Regla par-impar sobre todos los anillos: los huecos restan solos."""
    inside = False
    for ring in polygon:
        x2, y2 = ring[-1]
        for x1, y1 in ring:
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (
                y2 - y1
            ) + x1:
                inside = not inside
            x2, y2 = x1, y1
    return inside


def _km_per_degree_lon(latitude: float) -> float:
    return _KM_PER_DEGREE_LON_EQUATOR * math.cos(math.radians(latitude))


def _distance_to_ring_km(lon: float, lat: float, ring: _Ring) -> float:
    """Distancia a un anillo, en un plano local (suficiente a pocos km)."""
    kx, ky = _km_per_degree_lon(lat), _KM_PER_DEGREE_LAT
    px, py = lon * kx, lat * ky
    best = math.inf
    x2, y2 = ring[-1][0] * kx, ring[-1][1] * ky
    for point in ring:
        x1, y1 = point[0] * kx, point[1] * ky
        dx, dy = x2 - x1, y2 - y1
        length2 = dx * dx + dy * dy
        t = 0.0
        if length2:
            t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length2))
        best = min(best, math.hypot(px - x1 - t * dx, py - y1 - t * dy))
        x2, y2 = x1, y1
    return best
