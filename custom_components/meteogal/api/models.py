"""Datos devueltos por el cliente.

Los códigos de cielo y viento se devuelven tal cual los da MeteoGalicia; traducirlos
a conceptos de Home Assistant es cosa de la integración. Los valores "no disponible"
(-9999) llegan como None.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class Concello:
    """Concello de Galicia, con su código INE."""

    id: int
    name: str


@dataclass(frozen=True, slots=True)
class Station:
    """Estación meteorológica."""

    id: int
    name: str
    concello: str
    province: str
    latitude: float
    longitude: float
    altitude: float | None


@dataclass(frozen=True, slots=True)
class DayParts[T]:
    """Un valor por franja del día: mañana, tarde y noche."""

    morning: T
    afternoon: T
    night: T


@dataclass(frozen=True, slots=True)
class DailyForecast:
    """Previsión de un día a corto plazo (`jsonPredConcellos`)."""

    date: date
    sky: int | None
    sky_parts: DayParts[int | None]
    precipitation_probability: DayParts[int | None]
    wind: DayParts[int | None]
    temperature_max: int | None
    temperature_min: int | None
    temperature_max_parts: DayParts[int | None]
    temperature_min_parts: DayParts[int | None]
    uv_max: int | None
    alert_level: int | None


@dataclass(frozen=True, slots=True)
class HourlyForecast:
    """Previsión de una hora (`jsonPredHorariaConcellos`)."""

    time: datetime
    sky: int | None
    wind: int | None
    temperature: int | None


@dataclass(frozen=True, slots=True)
class SkyProbability:
    """Un estado de cielo posible y su probabilidad en %."""

    sky: int
    probability: int | None


@dataclass(frozen=True, slots=True)
class MediumTermForecast:
    """Previsión de un día a medio plazo (`jsonPredMedioPrazo`).

    Las temperaturas traen un margen: `*_low` y `*_high` son los límites inferior y
    superior de la máxima y de la mínima.
    """

    date: date
    day: int
    sky: tuple[SkyProbability, ...]
    wind: int | None
    temperature_max: int | None
    temperature_max_low: int | None
    temperature_max_high: int | None
    temperature_min: int | None
    temperature_min_low: int | None
    temperature_min_high: int | None


@dataclass(frozen=True, slots=True)
class ConcelloObservation:
    """Estado actual de un concello (`observacionConcellos`)."""

    concello_id: int
    time: datetime
    sky: int | None
    wind: int | None
    temperature: float | None
    apparent_temperature: float | None


@dataclass(frozen=True, slots=True)
class MeteoSixHour:
    """Previsión numérica de una hora en un punto (MeteoSIX, `getNumericForecastInfo`).

    La lluvia es la acumulada en la hora anterior. El cielo es el nombre que da
    MeteoSIX (`SUNNY`, `RAIN`…) y `night` dice si su icono es el de noche. Cada campo
    puede faltar si esa variable no tiene dato en esa hora o no se pidió.
    """

    time: datetime
    model_run: datetime | None
    sky: str | None = None
    night: bool | None = None
    temperature: float | None = None
    precipitation: float | None = None
    wind_speed: float | None = None
    wind_bearing: float | None = None
    humidity: float | None = None
    cloud_coverage: float | None = None
    pressure: float | None = None
    snow_level: float | None = None


@dataclass(frozen=True, slots=True)
class WeatherWarning:
    """Aviso meteorológico de un concello (`jsonAvisosConcellos`).

    `level`: 1 amarillo, 2 naranja, 3 rojo. `type_id`: tipo de fenómeno (anexo II
    de la documentación: 1 temperatura máxima … 9 viento en el mar, 10 olas).
    """

    id: int
    type_id: int
    level: int
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class StationReading:
    """Última lectura de una estación (`ultimos10minEstacionsMeteo`).

    `values`: por código de MeteoGalicia (`TA_AVG_1.5m`, `PP_SUM_1.5m`…), solo los
    datos válidos (sin validar, válidos o interpolados). Cada estación mide cosas
    distintas: lo que no mide no aparece.
    """

    station_id: int
    time: datetime
    values: dict[str, float]


@dataclass(frozen=True, slots=True)
class StationDay:
    """Acumulados y extremos del día de una estación (`datosDiariosEstacionsMeteo`)."""

    station_id: int
    date: date
    values: dict[str, float]


@dataclass(frozen=True, slots=True)
class Camera:
    """Cámara de MeteoGalicia (`jsonCamaras`). Muchas están en una estación y
    comparten su identificador.

    `key` identifica la cámara: el identificador no basta, porque hay sitios con
    dos cámaras que lo comparten (Ons playa y puerto, Cíes faro norte y sur). Es
    la carpeta de su foto en la web de MeteoGalicia (`Corunha`, `Onsplaya`…).
    """

    key: str
    id: int
    name: str
    concello_id: int
    latitude: float
    longitude: float
    image_url: str
    time: datetime
