"""Avisos meteorológicos: nombres estables, orden y resúmenes (docs/avisos.md).

Sigue lo acordado en la revisión de GeoSphere Austria Warnings en HA: nivel como
enum, solo el aviso principal en atributos y el detalle completo en una acción,
siempre con slugs estables que traduce la interfaz.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Final

from .api import WeatherWarning

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
