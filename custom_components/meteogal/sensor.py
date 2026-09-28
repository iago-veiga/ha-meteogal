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
from homeassistant.const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    MATCH_ALL,
    EntityCategory,
    UnitOfLength,
    UnitOfPrecipitationDepth,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import MeteoGalConfigEntry
from .api import MeteoSixHour, WeatherWarning
from .const import ATTRIBUTION
from .coordinator import StationCoordinator
from .entity import ONE_HOUR, MeteoSixEntity, WarningsEntity, location_device, rain
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
        data = station.data
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
    remove = None

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
        data = self.coordinator.data
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


class WarningLevelSensor(WarningsEntity, SensorEntity):
    """Nivel más alto de los avisos vigentes (o de los próximos).

    Atributos: solo el aviso principal y fuera del recorder. La lista completa se
    pide con la acción `meteogal.get_warnings`.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = LEVEL_OPTIONS
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(self, coordinator, key: str, select: WarningSelector) -> None:
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

    def __init__(self, coordinator, key: str, select: WarningSelector) -> None:
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
