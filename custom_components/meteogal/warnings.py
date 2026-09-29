"""Avisos meteorológicos: nombres estables, orden y resúmenes (docs/avisos.md).

Sigue lo acordado en la revisión de GeoSphere Austria Warnings en HA: nivel como
enum, solo el aviso principal en atributos y el detalle completo en una acción,
siempre con slugs estables que traduce la interfaz.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Final

from .api import WarningText, WeatherWarning

LEVEL_NONE: Final = "none"
LEVELS: Final = {1: "yellow", 2: "orange", 3: "red"}
LEVEL_OPTIONS: Final = [LEVEL_NONE, *LEVELS.values()]

# Anexo II de la documentación de `jsonAvisosConcellos`.
TYPES: Final = {
    1: "high_temperature",
    2: "low_temperature",
    3: "rain_1h",
    4: "rain_12h",
    5: "fog",
    6: "snow",
    7: "thunderstorm",
    8: "wind_gust",
    9: "wind_at_sea",
    10: "waves",
}
UNKNOWN_TYPE: Final = "unknown"

# Zonas del RSS de avisos que no dependen del concello: provincia (por los dos
# primeros dígitos del código INE) y toda Galicia.
PROVINCE_ZONES: Final = {15: 316, 27: 317, 32: 318, 36: 319}
GALICIA_ZONE: Final = 320
# Avisos de mar: se asignan a zonas marítimo-costeras, que no están en la tabla.
MARINE_TYPES: Final = frozenset({9, 10})

ZONES_FILE: Final = Path(__file__).parent / "data" / "zonas_avisos.json"


def load_zones() -> dict[int, tuple[int, int]]:
    """Por código INE: la zona del concello y la de su agrupación (bloquea: en el
    executor). Generado con scripts/generate_warning_zones.py."""
    data = json.loads(ZONES_FILE.read_text(encoding="utf-8"))
    return {int(code): (own, group) for code, (own, group) in data["zones"].items()}


def concello_zones(concello_id: int, zones: dict[int, tuple[int, int]]) -> list[int]:
    """Zonas que incluyen al concello, de la más concreta a la más amplia."""
    own = list(zones.get(concello_id, ()))
    province = PROVINCE_ZONES.get(concello_id // 1000)
    return [*own, *([province] if province else []), GALICIA_ZONE]


def describe(
    warnings: list[WeatherWarning], texts: list[WarningText], zones: list[int]
) -> list[WeatherWarning]:
    """Añade a cada aviso el comentario del tramo del RSS que le corresponde.

    El tramo tiene que ser del mismo tipo, nivel, inicio y fin, y de una zona que
    incluya al concello; si hay varios, el de la zona más concreta. Los avisos de
    mar van en zonas marítimo-costeras, que no están en la tabla: valen si todos
    los tramos iguales dicen lo mismo. Sin tramo, el aviso queda sin comentario.
    """
    rank = {zone: n for n, zone in enumerate(zones)}
    result = []
    for warning in warnings:
        same = [
            t
            for t in texts
            if t.type_id == warning.type_id
            and t.level == warning.level
            and t.start == warning.start
            and t.end == warning.end
            and t.comment
        ]
        own = sorted(
            (t for t in same if t.zone_id in rank), key=lambda t: rank[t.zone_id]
        )
        match = own[0] if own else None
        if (
            match is None
            and warning.type_id in MARINE_TYPES
            and len({t.comment for t in same}) == 1
        ):
            match = same[0]
        if match:
            warning = replace(warning, description=match.comment, zone=match.zone_name)
        result.append(warning)
    return result


def type_slug(warning: WeatherWarning) -> str:
    return TYPES.get(warning.type_id, UNKNOWN_TYPE)


def level_slug(warning: WeatherWarning) -> str:
    return LEVELS.get(warning.level, LEVEL_NONE)


def active(warnings: Iterable[WeatherWarning], now: datetime) -> list[WeatherWarning]:
    """Vigentes ahora, ordenados (el principal primero)."""
    return sort_warnings(w for w in warnings if w.start <= now < w.end)


def upcoming(warnings: Iterable[WeatherWarning], now: datetime) -> list[WeatherWarning]:
    """Emitidos que aún no han empezado, ordenados. Sin ventana inventada: todos
    los que da MeteoGalicia (hasta pasado mañana)."""
    return sort_warnings(w for w in warnings if w.start > now)


def sort_warnings(warnings: Iterable[WeatherWarning]) -> list[WeatherWarning]:
    """Más grave primero; a igual nivel, el que acaba antes y luego el que empieza
    antes. El id deja el orden fijo entre avisos iguales."""
    return sorted(warnings, key=lambda w: (-w.level, w.end, w.start, w.id))


def highest_level(warnings: Iterable[WeatherWarning]) -> str:
    return LEVELS.get(max((w.level for w in warnings), default=0), LEVEL_NONE)


def main_warning_attributes(warnings: list[WeatherWarning]) -> dict[str, Any]:
    """Atributos del aviso principal (el primero de la lista ya ordenada)."""
    if not warnings:
        return {}
    warning = warnings[0]
    return {
        "type": type_slug(warning),
        "level": level_slug(warning),
        "start": warning.start.isoformat(),
        "end": warning.end.isoformat(),
        "warning_id": warning.id,
        "description": warning.description,
        "zone": warning.zone,
    }


def warning_details(warning: WeatherWarning, now: datetime) -> dict[str, Any]:
    """Un aviso tal como lo devuelve la acción `meteogal.get_warnings`."""
    return {
        **main_warning_attributes([warning]),
        "active": warning.start <= now < warning.end,
    }


def next_change(warnings: Iterable[WeatherWarning], now: datetime) -> datetime | None:
    """Próximo inicio o fin de algún aviso: cuándo cambia el estado sin datos
    nuevos."""
    return min((t for w in warnings for t in (w.start, w.end) if t > now), default=None)
