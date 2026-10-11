"""Medidas de las estaciones: qué sensor sale de cada código y cómo se limpia.

Sin nada de HA salvo las clases de sensor. Detalle y decisiones en
docs/estaciones.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    UnitOfIrradiance,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)

from .api import StationDay, StationHour, StationReading

# Lectura de 10 minutos ("now") o acumulados y extremos de hoy ("today").
NOW: Final = "now"
TODAY: Final = "today"

TEMPERATURE: Final = "TA_AVG_1.5m"
HUMIDITY: Final = "HR_AVG_1.5m"
DEW_POINT: Final = "TO_AVG_1.5m"
PRESSURE: Final = "PRED_AVG_1.5m"  # reducida al nivel del mar, como la de weather
RAIN: Final = "PP_SUM_1.5m"
WIND_SPEED: Final = "VV_AVG_10m"
WIND_GUST: Final = "VV_RACHA_10m"
WIND_BEARING: Final = "DV_AVG_10m"
WIND_CODES: Final = frozenset(
    {WIND_SPEED, WIND_GUST, WIND_BEARING, "DV_SD_10m", "VV_SD_10m", "DV_CONDICION_10m"}
)

TEMPERATURE_MAX: Final = "TA_MAX_1.5m"
TEMPERATURE_MIN: Final = "TA_MIN_1.5m"
SUNSHINE: Final = "HSOL_SUM_1.5m"
EVAPOTRANSPIRATION: Final = "ET0_SUM_1.5m"

# Lo de hoy que también dan las horas, y cómo se juntan con el día UTC.
HOURLY: Final[dict[str, Callable[[list[float]], float]]] = {
    RAIN: sum,
    TEMPERATURE_MAX: max,
    TEMPERATURE_MIN: min,
}
# Acumulados que las horas no dan, pero que de noche son 0: tapan el hueco hasta
# que llega el día UTC.
NIGHT_SUMS: Final = frozenset({SUNSHINE, EVAPOTRANSPIRATION})
# Acumulados de hoy: nunca bajan dentro del día.
SUMS: Final = frozenset({RAIN}) | NIGHT_SUMS

# Más antigua que esto, la lectura no vale: la estación ha dejado de enviar.
MAX_AGE: Final = timedelta(hours=1)

# Lo que puede faltarle a una estación para el tiempo actual (se avisa al elegirla).
NO_DATA: Final = "no_data"
NO_WIND: Final = "no_wind"
NO_PRESSURE: Final = "no_pressure"


@dataclass(frozen=True, slots=True, kw_only=True)
class StationSensor:
    """Un sensor de estación: de qué código y de qué lectura sale."""

    key: str
    code: str
    source: str = NOW
    device_class: SensorDeviceClass | None = None
    unit: str | None = None
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    enabled: bool = True
    scale: float = 1.0
    precision: int | None = None
    # Solo los de hoy: la medida de 10 min que indica que la estación lo tendrá.
    # Sirve cuando aún no hay datos del día (justo después de medianoche).
    requires: str | None = None


SENSORS: Final = (
    # Activados: lo que se mira a diario.
    StationSensor(
        key="temperature",
        code=TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        precision=1,
    ),
    StationSensor(
        key="humidity",
        code=HUMIDITY,
        device_class=SensorDeviceClass.HUMIDITY,
        unit=PERCENTAGE,
        precision=0,
    ),
    StationSensor(
        key="rain_today",
        requires=RAIN,
        code=RAIN,
        source=TODAY,
        device_class=SensorDeviceClass.PRECIPITATION,
        unit=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        precision=1,
    ),
    StationSensor(
        key="rain_10min",
        code=RAIN,
        device_class=SensorDeviceClass.PRECIPITATION,
        unit=UnitOfPrecipitationDepth.MILLIMETERS,
        precision=1,
    ),
    StationSensor(
        key="wind_speed",
        code=WIND_SPEED,
        device_class=SensorDeviceClass.WIND_SPEED,
        unit=UnitOfSpeed.METERS_PER_SECOND,
        precision=1,
    ),
    StationSensor(
        key="wind_gust",
        code=WIND_GUST,
        device_class=SensorDeviceClass.WIND_SPEED,
        unit=UnitOfSpeed.METERS_PER_SECOND,
        precision=1,
    ),
    StationSensor(
        key="pressure",
        code=PRESSURE,
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        unit=UnitOfPressure.HPA,
        precision=0,
    ),
    StationSensor(
        key="water_temperature",
        code="TSA_AVG_-1m",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        precision=1,
    ),
    # Desactivados: para quien los necesite.
    StationSensor(
        key="wind_direction",
        code=WIND_BEARING,
        device_class=SensorDeviceClass.WIND_DIRECTION,
        unit=DEGREE,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        enabled=False,
        precision=0,
    ),
    StationSensor(
        key="dew_point",
        code=DEW_POINT,
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        enabled=False,
        precision=1,
    ),
    StationSensor(
        key="temperature_max_today",
        requires=TEMPERATURE,
        code=TEMPERATURE_MAX,
        source=TODAY,
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        enabled=False,
        precision=1,
    ),
    StationSensor(
        key="temperature_min_today",
        requires=TEMPERATURE,
        code=TEMPERATURE_MIN,
        source=TODAY,
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        enabled=False,
        precision=1,
    ),
    StationSensor(
        key="wind_max_today",
        requires=WIND_SPEED,
        code="VV_MAX_10m",
        source=TODAY,
        device_class=SensorDeviceClass.WIND_SPEED,
        unit=UnitOfSpeed.METERS_PER_SECOND,
        enabled=False,
        precision=1,
    ),
    StationSensor(
        key="sun_hours_today",
        requires=SUNSHINE,
        code=SUNSHINE,
        source=TODAY,
        device_class=SensorDeviceClass.DURATION,
        unit=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        enabled=False,
        precision=1,
    ),
    StationSensor(
        key="evapotranspiration_today",
        requires="RS_AVG_1.5m",
        code=EVAPOTRANSPIRATION,
        source=TODAY,
        device_class=SensorDeviceClass.PRECIPITATION,
        unit=UnitOfPrecipitationDepth.MILLIMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        enabled=False,
        precision=1,
    ),
    StationSensor(
        key="solar_radiation",
        code="RS_AVG_1.5m",
        device_class=SensorDeviceClass.IRRADIANCE,
        unit=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        enabled=False,
        precision=0,
    ),
    StationSensor(
        key="uv_radiation",
        code="BIO_AVG_1.5m",
        device_class=SensorDeviceClass.IRRADIANCE,
        unit=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        enabled=False,
        precision=1,
    ),
    StationSensor(
        key="ground_temperature",
        code="TA_AVG_0.1m",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        enabled=False,
        precision=1,
    ),
    StationSensor(
        key="soil_temperature",
        code="TS_AVG_-0.1m",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        enabled=False,
        precision=1,
    ),
    StationSensor(
        key="soil_moisture",
        code="HS_CV_AVG_-0.2m",
        device_class=SensorDeviceClass.MOISTURE,
        unit=PERCENTAGE,
        enabled=False,
        scale=100.0,  # m³/m³ → %
        precision=0,
    ),
)


def sensor_keys(reading_codes: set[str], day_codes: set[str]) -> set[str]:
    """Claves de los sensores que tiene sentido crear para una estación."""
    keys = set()
    for sensor in SENSORS:
        if sensor.source == NOW:
            present = sensor.code in reading_codes
        else:
            present = sensor.code in day_codes or (
                not day_codes and sensor.requires in reading_codes
            )
        if present:
            keys.add(sensor.key)
    return keys


def station_gaps(
    readings: list[StationReading], station_ids: Iterable[int]
) -> dict[int, frozenset[str]]:
    """Lo que no dará cada estación, según la última lectura de todas.

    «Sin datos» se mide contra la lectura más reciente de todas y no contra el
    reloj: si MeteoGalicia va con retraso, no se marcan todas. Viento y presión,
    por el código aunque venga a cero: lo que importa es que la estación lo mide.
    """
    if not readings:
        return {}
    latest = max(reading.time for reading in readings)
    by_id = {reading.station_id: reading for reading in readings}
    gaps = {}
    for station_id in station_ids:
        reading = by_id.get(station_id)
        if reading is None or latest - reading.time > MAX_AGE:
            gaps[station_id] = frozenset({NO_DATA})
            continue
        gaps[station_id] = frozenset(
            gap
            for gap, code in ((NO_WIND, WIND_SPEED), (NO_PRESSURE, PRESSURE))
            if code not in reading.values
        )
    return gaps


def clean(reading: StationReading) -> dict[str, float]:
    """Valores de la lectura, sin el viento si viene todo a cero.

    Visto en Coruña-Dique (2026-09-27 21:40Z): velocidad, racha, rumbo y sus
    desviaciones exactamente a 0 con la dirección de la racha en 13°, mientras en
    las horas de antes y después había rachas de 2-5 m/s. Una calma real no da
    racha 0,0 con desviación 0: se toma como dato ausente, no como calma.
    """
    values = dict(reading.values)
    if (
        values.get(WIND_SPEED) == 0
        and values.get(WIND_GUST) == 0
        and values.get("DV_SD_10m") == 0
    ):
        for code in WIND_CODES:
            values.pop(code, None)
    return values


def evening(start: datetime) -> tuple[datetime, datetime]:
    """Horas del día UTC anterior que ya son del día local que empieza en `start`
    (medianoche local): de 22:00Z a 24:00Z en verano y de 23:00Z a 24:00Z en
    invierno. Devuelve el principio y el final, en UTC."""
    end = datetime.combine(utc_day(start), time(), UTC)
    return start.astimezone(UTC), end


def utc_day(start: datetime) -> date:
    """Día UTC del que MeteoGalicia da los datos diarios del día local que empieza
    en `start`."""
    return (start + timedelta(hours=12)).astimezone(UTC).date()


def local_day(
    day: StationDay | None,
    hours: list[StationHour] | None,
    start: datetime,
    now: datetime,
) -> dict[str, float] | None:
    """Acumulados y extremos del día local que empieza en `start`, hasta `now`.

    MeteoGalicia cierra el día en UTC (el nuevo aparece a las ~00:24Z): el día
    local son las horas de la tarde UTC anterior que ya caen en él (`evening`) más
    el día UTC. Entre la medianoche local y la llegada del día UTC, solo las horas.
    `hours` es None si no se pudieron pedir: entonces solo el día UTC.
    """
    first, end = evening(start)
    utc = day.values if day is not None and day.date == utc_day(start) else {}
    own = [hour for hour in hours or () if first < hour.time <= min(end, now)]
    values = {code: value for code, value in utc.items() if code not in HOURLY}
    for code, combine in HOURLY.items():
        parts = [hour.values[code] for hour in own if code in hour.values]
        if code in utc:
            parts.append(utc[code])
        if parts:
            values[code] = combine(parts)
        elif code in SUMS and hours is not None:
            values[code] = 0.0  # aún no hay ninguna hora entera del día
    if hours is not None:
        for code in NIGHT_SUMS:
            values.setdefault(code, 0.0)
    return values or None
