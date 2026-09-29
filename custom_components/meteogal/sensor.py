"""Sensores por ubicación: avisos (sin clave) y lluvia y cota de nieve (MeteoSIX)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    MATCH_ALL,
    EntityCategory,
    UnitOfLength,
    UnitOfPrecipitationDepth,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import MeteoGalConfigEntry
from .air import (
    LEVELS,
    POLLUTANTS,
    STATION_KINDS,
    STATION_MAX_AGE,
    AirPollutant,
    level,
    pollutant,
)
from .api import AirMeasurements, MeteoSixHour, WeatherWarning
from .const import ATTRIBUTION, CONF_AIR_STATION_ID
from .coordinator import (
    AirStationCoordinator,
    AirStationData,
    LocationCoordinator,
    StationCoordinator,
    StationData,
)
from .entity import (
    ONE_HOUR,
    AirEntity,
    EnumActions,
    MeteoSixEntity,
    WarningsEntity,
    location_device,
    rain,
)
from .geo import distance_km
from .station import SENSORS, TODAY, StationSensor, clean, sensor_keys
from .warnings import (
    LEVEL_OPTIONS,
    active,
    highest_level,
    main_warning_attributes,
    upcoming,
    warning_details,
)

# Estados del sensor de calidad del aire.
AIR_LEVEL_OPTIONS = list(LEVELS)

# A partir de 0,1 mm se considera que llueve (lo mínimo que se mide).
RAIN_THRESHOLD = 0.1


# Todo llega de coordinadores: no hay actualizaciones por entidad que limitar.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeteoGalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Avisos en todas las ubicaciones; lluvia y nieve, solo con clave de MeteoSIX."""
    meteosix = entry.runtime_data.meteosix
    for subentry_id, coordinator in entry.runtime_data.locations.items():
        entities: list[SensorEntity] = [
            WarningLevelSensor(coordinator, "warning_level", active),
            WarningLevelSensor(coordinator, "upcoming_warning_level", upcoming),
            WarningCountSensor(coordinator, "active_warnings", active),
            WarningCountSensor(coordinator, "upcoming_warnings", upcoming),
        ]
        if meteosix is not None:
            subentry = entry.subentries[subentry_id]
            entities += [
                RainThisHourSensor(meteosix, subentry, "rain_this_hour"),
                NextRainSensor(meteosix, subentry, "next_rain"),
                SnowLevelSensor(meteosix, subentry, "snow_level"),
            ]
        async_add_entities(entities, config_subentry_id=subentry_id)

    for subentry_id, station in entry.runtime_data.stations.items():
        _add_station_sensors(station, subentry_id, async_add_entities)

    air_model = entry.runtime_data.air_model
    air_stations = entry.runtime_data.air_stations
    for subentry_id in entry.runtime_data.locations:
        subentry = entry.subentries[subentry_id]
        async_add_entities(
            [
                AirQualitySensor(air_model, air_stations, subentry, "air_quality"),
                AirQualityIndexSensor(
                    air_model, air_stations, subentry, "air_quality_index"
                ),
            ],
            config_subentry_id=subentry_id,
        )
        if air_stations is not None and subentry.data.get(CONF_AIR_STATION_ID):
            _add_air_station_sensors(
                air_stations,
                subentry,
                int(subentry.data[CONF_AIR_STATION_ID]),
                async_add_entities,
            )


@callback
def _add_air_station_sensors(
    stations: AirStationCoordinator,
    subentry: ConfigSubentry,
    station_id: int,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Solo los contaminantes que mide esa estación. Si al arrancar aún no hay
    medidas, se añaden con las primeras que lleguen."""

    @callback
    def add() -> bool:
        data: AirStationData | None = stations.data
        if data is None or station_id not in data.measurements:
            return False
        measured = data.measurements[station_id].values
        entities: list[SensorEntity] = [
            AirStationUpdatedSensor(stations, subentry, station_id)
        ]
        entities += [
            AirPollutantSensor(stations, subentry, station_id, pollutant)
            for pollutant in POLLUTANTS
            if pollutant.code in measured
        ]
        async_add_entities(entities, config_subentry_id=subentry.subentry_id)
        return True

    if add():
        return
    remove: CALLBACK_TYPE | None = None

    @callback
    def on_update() -> None:
        if add() and remove:
            remove()

    remove = stations.async_add_listener(on_update)
    stations.config_entry.async_on_unload(remove)


@callback
def _add_station_sensors(
    station: StationCoordinator,
    subentry_id: str,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Solo los sensores de lo que mide esa estación. Si al arrancar aún no hay
    datos, se añaden con la primera lectura."""

    @callback
    def add() -> bool:
        data: StationData | None = station.data
        if data is None:
            return False
        # Lo que mide la estación. Sin datos de hoy todavía (justo después de
        # medianoche), los de hoy se deducen de la lectura de 10 minutos.
        keys = sensor_keys(
            set(data.reading.values) if data.reading else set(),
            set(data.day.values) if data.day else set(),
        )
        entities: list[SensorEntity] = [StationUpdatedSensor(station)]
        entities += [
            StationValueSensor(station, description)
            for description in SENSORS
            if description.key in keys
        ]
        async_add_entities(entities, config_subentry_id=subentry_id)
        return True

    if add():
        return
    remove: CALLBACK_TYPE | None = None

    @callback
    def on_update() -> None:
        if add() and remove:
            remove()

    remove = station.async_add_listener(on_update)
    station.config_entry.async_on_unload(remove)


class StationEntity(CoordinatorEntity[StationCoordinator]):
    """Entidad de la estación de una ubicación, en su dispositivo."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: StationCoordinator, key: str) -> None:
        super().__init__(coordinator)
        subentry = coordinator.subentry
        self._attr_translation_key = f"station_{key}"
        self._attr_unique_id = f"{subentry.subentry_id}_station_{key}"
        self._attr_device_info = location_device(subentry)


class StationValueSensor(StationEntity, SensorEntity):
    """Una medida de la estación: la última lectura o lo acumulado hoy."""

    def __init__(
        self, coordinator: StationCoordinator, description: StationSensor
    ) -> None:
        super().__init__(coordinator, description.key)
        self._description = description
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.unit
        self._attr_state_class = description.state_class
        self._attr_suggested_display_precision = description.precision
        self._attr_entity_registry_enabled_default = description.enabled

    @property
    def native_value(self) -> float | None:
        data: StationData | None = self.coordinator.data
        if data is None:
            return None
        description = self._description
        if description.source == TODAY:
            day = data.day
            if day is None or day.date != dt_util.now().date():
                return None  # aún no hay datos de hoy
            values = day.values
        else:
            reading = data.fresh_reading(dt_util.utcnow())
            if reading is None:
                return None  # la estación ha dejado de enviar
            values = clean(reading)
        value = values.get(description.code)
        return None if value is None else value * description.scale


class StationUpdatedSensor(StationEntity, SensorEntity):
    """Hora de la última lectura de la estación, con cuál es y a qué distancia."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: StationCoordinator) -> None:
        super().__init__(coordinator, "updated")

    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data
        return data.reading.time if data and data.reading else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        station = self.coordinator.station
        attributes: dict[str, Any] = {"station_id": self.coordinator.station_id}
        if station:
            location = self.coordinator.subentry.data
            attributes["station_name"] = station.name
            attributes["distance"] = round(
                distance_km(
                    location[CONF_LATITUDE],
                    location[CONF_LONGITUDE],
                    station.latitude,
                    station.longitude,
                ),
                1,
            )
        return attributes


type WarningSelector = Callable[[list[WeatherWarning], datetime], list[WeatherWarning]]


class WarningLevelSensor(WarningsEntity, EnumActions, SensorEntity):
    """Nivel más alto de los avisos vigentes (o de los próximos).

    Atributos: solo el aviso principal y fuera del recorder. La lista completa se
    pide con la acción `meteogal.get_warnings`.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = LEVEL_OPTIONS
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(
        self, coordinator: LocationCoordinator, key: str, select: WarningSelector
    ) -> None:
        super().__init__(coordinator, key)
        self._select = select

    @property
    def _warnings(self) -> list[WeatherWarning]:
        return self._select(self.coordinator.data.warnings, dt_util.now())

    @property
    def native_value(self) -> str:
        return highest_level(self._warnings)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return main_warning_attributes(self._warnings)

    def get_warnings(self) -> dict[str, Any]:
        """Respuesta de `meteogal.get_warnings`: todos los avisos de la ubicación
        (vigentes y próximos), el principal primero."""
        now = dt_util.now()
        warnings = [
            *active(self.coordinator.data.warnings, now),
            *upcoming(self.coordinator.data.warnings, now),
        ]
        return {"warnings": [warning_details(w, now) for w in warnings]}


class WarningCountSensor(WarningsEntity, SensorEntity):
    """Número de avisos vigentes (o próximos). Desactivado por defecto."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: LocationCoordinator, key: str, select: WarningSelector
    ) -> None:
        super().__init__(coordinator, key)
        self._select = select

    @property
    def native_value(self) -> int:
        return len(self._select(self.coordinator.data.warnings, dt_util.now()))


class RainThisHourSensor(MeteoSixEntity, SensorEntity):
    """Lluvia prevista (mm) en la hora en curso, como el `rain` de AEMET."""

    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | None:
        return rain(self._hours, self._start, 1)


class NextRainSensor(MeteoSixEntity, SensorEntity):
    """Hora a la que empieza la próxima lluvia, como el `next_rain` de Météo-France.

    Es el inicio de la primera hora, desde la en curso, con lluvia prevista. Si ya
    llueve en la hora en curso, su inicio (algo antes de ahora). Sin lluvia en
    todo el alcance de MeteoSIX, desconocido.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        return next_rain(self._hours, self._start)


def next_rain(hours: list[MeteoSixHour], start: datetime) -> datetime | None:
    """Inicio de la primera hora desde `start` con lluvia prevista, o None."""
    last = max((hour.time for hour in hours), default=start)
    for n in range(int((last - start) / ONE_HOUR)):
        amount = rain(hours, start + ONE_HOUR * n, 1)
        if amount is not None and amount >= RAIN_THRESHOLD:
            return start + ONE_HOUR * n
    return None


class SnowLevelSensor(MeteoSixEntity, SensorEntity):
    """Cota de nieve de la hora en curso. Solo interesa en invierno o en la montaña."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_suggested_display_precision = 0
    _attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> float | None:
        now = self._start
        return next((hour.snow_level for hour in self._hours if hour.time == now), None)


class AirQualitySensor(AirEntity, EnumActions, SensorEntity):
    """Calidad del aire ahora: la estación de aire si la hay y su dato es reciente;
    si no, el modelo en el punto; si no, lo previsto para hoy en el concello.

    El detalle por horas y días se pide con la acción `meteogal.get_air_quality`.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = AIR_LEVEL_OPTIONS

    @property
    def native_value(self) -> str | None:
        current = self._current
        return current.level if current else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        current = self._current
        if current is None:
            return {}
        return {"source": current.source, "main_pollutant": current.pollutant}

    def get_air_quality(self) -> dict[str, Any]:
        """Respuesta de `meteogal.get_air_quality`: ahora, cada hora del modelo desde
        la en curso y cada día previsto para el concello."""
        current = self._current
        start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        return {
            "now": {
                "level": current.level,
                "index": current.index,
                "main_pollutant": current.pollutant,
                "source": current.source,
            }
            if current
            else None,
            "hourly": [
                {
                    "datetime": dt_util.as_local(hour.time).isoformat(),
                    "level": level(hour.index),
                    "index": hour.index,
                }
                for hour in self._model_hours
                if hour.time >= start and hour.index is not None
            ],
            "daily": [
                {
                    "date": day.date.isoformat(),
                    "level": level(day.index),
                    "index": day.index,
                    "main_pollutant": pollutant(day.pollutant),
                    "peak": day.peak.isoformat() if day.peak else None,
                }
                for day in self._forecast
                if day.date >= dt_util.now().date() and day.index is not None
            ],
        }


class AirQualityIndexSensor(AirEntity, SensorEntity):
    """El número del ICA (0-6) del que sale el nivel. Desactivado por defecto."""

    _attr_device_class = SensorDeviceClass.AQI
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> float | None:
        current = self._current
        return current.index if current else None


class AirStationEntity(CoordinatorEntity[AirStationCoordinator]):
    """Entidad de la estación de aire de una ubicación, en su dispositivo."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: AirStationCoordinator,
        subentry: ConfigSubentry,
        station_id: int,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._subentry = subentry
        self._station_id = station_id
        self._attr_unique_id = f"{subentry.subentry_id}_air_{key}"
        self._attr_device_info = location_device(subentry)

    @property
    def _measurements(self) -> AirMeasurements | None:
        data = self.coordinator.data
        return data.measurements.get(self._station_id) if data else None


class AirPollutantSensor(AirStationEntity, SensorEntity):
    """Un contaminante medido en la estación de aire. El nombre sale de la clase de
    dispositivo (PM2,5, Ozono…), así valen los disparadores y condiciones de HA."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: AirStationCoordinator,
        subentry: ConfigSubentry,
        station_id: int,
        description: AirPollutant,
    ) -> None:
        super().__init__(coordinator, subentry, station_id, description.key)
        self._code = description.code
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.unit
        self._attr_entity_registry_enabled_default = description.enabled

    @property
    def native_value(self) -> float | None:
        measurements = self._measurements
        if (
            measurements is None
            or measurements.time is None
            or dt_util.now() - measurements.time > STATION_MAX_AGE
        ):
            return None  # la estación ha dejado de enviar
        return measurements.values.get(self._code)


class AirStationUpdatedSensor(AirStationEntity, SensorEntity):
    """Hora de la última medida de la estación de aire, con cuál es, de qué tipo y
    a qué distancia."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "air_station_updated"

    def __init__(
        self,
        coordinator: AirStationCoordinator,
        subentry: ConfigSubentry,
        station_id: int,
    ) -> None:
        super().__init__(coordinator, subentry, station_id, "station_updated")

    @property
    def native_value(self) -> datetime | None:
        measurements = self._measurements
        return measurements.time if measurements else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes: dict[str, Any] = {"station_id": self._station_id}
        station = self.coordinator.stations.get(self._station_id)
        if station:
            location = self._subentry.data
            attributes["station_name"] = station.name
            attributes["station_type"] = STATION_KINDS.get(station.kind)
            attributes["distance"] = round(
                distance_km(
                    location[CONF_LATITUDE],
                    location[CONF_LONGITUDE],
                    station.latitude,
                    station.longitude,
                ),
                1,
            )
        return attributes
