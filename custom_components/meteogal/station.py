"""Medidas de las estaciones: qué sensor sale de cada código y cómo se limpia.

Sin nada de HA salvo las clases de sensor. Detalle y decisiones en
docs/estaciones.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
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

from .api import StationReading

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
        code="TA_MAX_1.5m",
        source=TODAY,
        device_class=SensorDeviceClass.TEMPERATURE,
        unit=UnitOfTemperature.CELSIUS,
        enabled=False,
        precision=1,
    ),
    StationSensor(
        key="temperature_min_today",
        requires=TEMPERATURE,
        code="TA_MIN_1.5m",
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
        requires="HSOL_SUM_1.5m",
        code="HSOL_SUM_1.5m",
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
        code="ET0_SUM_1.5m",
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
