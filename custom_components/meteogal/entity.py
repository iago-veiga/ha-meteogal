"""Piezas comunes de las entidades de MeteoGal."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_time_change,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import MeteoSixHour
from .const import ATTRIBUTION, DOMAIN
from .coordinator import LocationCoordinator, MeteoSixCoordinator
from .warnings import next_change

ONE_HOUR = timedelta(hours=1)


def location_device(subentry: ConfigSubentry) -> DeviceInfo:
    """El dispositivo de una ubicación: todas sus entidades van en él."""
    return DeviceInfo(
        identifiers={(DOMAIN, subentry.subentry_id)},
        name=subentry.title,
        manufacturer="MeteoGalicia",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://www.meteogalicia.gal",
    )


def current_hour(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def rain(hours: list[MeteoSixHour], start: datetime, count: int) -> float | None:
    """Lluvia (mm) de `count` horas desde `start`, o None si falta alguna.

    En MeteoSIX, la lluvia de cada hora está en el dato de la hora siguiente
    (docs/weather.md): la de 10:00 a 11:00 es la de las 11:00.
    """
    by_time = {hour.time: hour.precipitation for hour in hours}
    values = [by_time.get(start + ONE_HOUR * (n + 1)) for n in range(count)]
    if any(value is None for value in values):
        return None
    # Dos decimales, como MeteoSIX: la suma no arrastra restos de coma flotante y
    # el umbral de lluvia compara con el valor real (la pantalla muestra uno).
    return round(sum(value for value in values if value is not None), 2)


class MeteoSixEntity(CoordinatorEntity[MeteoSixCoordinator]):
    """Entidad de una ubicación con datos de MeteoSIX (solo con clave).

    Se recalcula también en cada cambio de hora: "la hora en curso" avanza
    aunque no lleguen datos nuevos.
    """

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self, coordinator: MeteoSixCoordinator, subentry: ConfigSubentry, key: str
    ) -> None:
        super().__init__(coordinator)
        self._subentry_id = subentry.subentry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{subentry.subentry_id}_{key}"
        self._attr_device_info = location_device(subentry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._handle_new_hour, minute=0, second=0
            )
        )

    @callback
    def _handle_new_hour(self, now: datetime) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return super().available and bool(self._hours)

    @property
    def _hours(self) -> list[MeteoSixHour]:
        return (self.coordinator.data or {}).get(self._subentry_id, [])

    @property
    def _start(self) -> datetime:
        return current_hour(dt_util.now())


class WarningsEntity(CoordinatorEntity[LocationCoordinator]):
    """Entidad de avisos de una ubicación (sin clave).

    El estado cambia justo cuando empieza o acaba un aviso, sin pedir datos: se
    programa el siguiente cambio cada vez que se escribe el estado.
    """

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: LocationCoordinator, key: str) -> None:
        super().__init__(coordinator)
        subentry = coordinator.subentry
        self._attr_translation_key = key
        self._attr_unique_id = f"{subentry.subentry_id}_{key}"
        self._attr_device_info = location_device(subentry)
        self._unsub_change: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_change)
        self._schedule_change()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._schedule_change()
        super()._handle_coordinator_update()

    @callback
    def _schedule_change(self) -> None:
        self._cancel_change()
        when = next_change(self.coordinator.data.warnings, dt_util.now())
        if when is not None:
            self._unsub_change = async_track_point_in_utc_time(
                self.hass, self._handle_change, dt_util.as_utc(when)
            )

    @callback
    def _handle_change(self, now: datetime) -> None:
        self._unsub_change = None
        self._schedule_change()
        self.async_write_ha_state()

    @callback
    def _cancel_change(self) -> None:
        if self._unsub_change:
            self._unsub_change()
            self._unsub_change = None
