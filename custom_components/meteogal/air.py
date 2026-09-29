"""Calidad del aire: niveles, contaminantes y de dónde sale el dato actual.

Sin nada de HA salvo las clases de sensor. Detalle y decisiones en
docs/calidad-aire.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER,
)

from .api import AirDayForecast, AirModelHour, AirStationIndex

# Los seis niveles del ICA, como el índice europeo de la EEA: 0-1 good, 1-2 fair…
# 5-6 extremely_poor. Se sacan del número, no de los textos de la API.
LEVELS: Final = (
    "good",
    "fair",
    "moderate",
    "poor",
    "very_poor",
    "extremely_poor",
)

# Origen del dato actual, del mejor al peor.
SOURCE_STATION: Final = "station"
SOURCE_MODEL: Final = "model"
SOURCE_FORECAST: Final = "forecast"

# Las estaciones publican cada hora, con retraso. Más de 3 h: ha dejado de enviar.
STATION_MAX_AGE: Final = timedelta(hours=3)

# Estación de aire propuesta por defecto: la más cercana, si está a menos de esto.
# Más lejos no representa el punto (mediana de 17 km de cada concello a la más
# cercana, docs/calidad-aire.md) y el modelo cubre la ubicación.
SUGGEST_WITHIN_KM: Final = 10.0

# Contaminante que manda en el ICA: código de la API → estado del sensor.
POLLUTANT_CODES: Final = {
    "NO2": "no2",
    "O3": "o3",
    "PM25": "pm25",
    "PM10": "pm10",
    "SO2": "so2",
}


# Tipo de estación de aire (texto de la API) → atributo traducible.
STATION_KINDS: Final = {
    "Tráfico": "traffic",
    "Industrial": "industrial",
    "Fondo": "background",
}


def level(index: float | None) -> str | None:
    """Nivel del ICA a partir del número (1,0 ya es `fair`; 2,0, `moderate`)."""
    if index is None:
        return None
    return LEVELS[min(int(index), len(LEVELS) - 1)]


def station_level(index: AirStationIndex) -> str | None:
    """Nivel de una estación: el que da MeteoGalicia (en inglés, los nombres de la
    EEA) si es uno conocido; si no, del número."""
    if index.label:
        name = index.label.strip().lower().replace(" ", "_")
        if name in LEVELS:
            return name
    return level(index.index)


def pollutant(code: str | None) -> str | None:
    return POLLUTANT_CODES.get(code) if code else None


@dataclass(frozen=True, slots=True, kw_only=True)
class AirPollutant:
    """Un sensor de contaminante de la estación de aire."""

    key: str
    code: str
    device_class: SensorDeviceClass
    unit: str
    enabled: bool = True


POLLUTANTS: Final = (
    AirPollutant(
        key="pm25",
        code="PM25",
        device_class=SensorDeviceClass.PM25,
        unit=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    AirPollutant(
        key="pm10",
        code="PM10",
        device_class=SensorDeviceClass.PM10,
        unit=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    AirPollutant(
        key="no2",
        code="NO2",
        device_class=SensorDeviceClass.NITROGEN_DIOXIDE,
        unit=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    AirPollutant(
        key="o3",
        code="O3",
        device_class=SensorDeviceClass.OZONE,
        unit=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    ),
    AirPollutant(
        key="so2",
        code="SO2",
        device_class=SensorDeviceClass.SULPHUR_DIOXIDE,
        unit=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        enabled=False,
    ),
    AirPollutant(
        key="co",
        code="CO",
        device_class=SensorDeviceClass.CO,
        unit=CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER,
        enabled=False,
    ),
    AirPollutant(
        key="no",
        code="NO",
        device_class=SensorDeviceClass.NITROGEN_MONOXIDE,
        unit=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        enabled=False,
    ),
)


@dataclass(frozen=True, slots=True)
class CurrentAir:
    """Calidad del aire ahora en una ubicación y de dónde sale."""

    level: str | None
    index: float
    pollutant: str | None
    source: str


def current_air(
    station: AirStationIndex | None,
    model: list[AirModelHour],
    forecast: list[AirDayForecast],
    now: datetime,
) -> CurrentAir | None:
    """Lo medido en la estación si es reciente; si no, el modelo en el punto a la hora
    en curso; si no, el previsto para hoy en el concello. None si no hay nada.

    `station` ya viene filtrada: None si la ubicación no tiene estación o no la usa.
    """
    if station and station.index is not None and now - station.time <= STATION_MAX_AGE:
        return CurrentAir(
            station_level(station),
            station.index,
            pollutant(station.pollutant),
            SOURCE_STATION,
        )
    hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    for item in model:
        if item.time == hour and item.index is not None:
            return CurrentAir(level(item.index), item.index, None, SOURCE_MODEL)
    today = now.date()
    for day in forecast:
        if day.date == today and day.index is not None:
            return CurrentAir(
                level(day.index),
                day.index,
                pollutant(day.pollutant),
                SOURCE_FORECAST,
            )
    return None
