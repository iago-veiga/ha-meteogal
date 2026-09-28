"""Diagnósticos de MeteoGal: el estado de cada fuente, sin datos personales.

Se ocultan la clave de MeteoSIX y las coordenadas de las ubicaciones (suelen ser
la casa del usuario). No incluye imágenes ni respuestas completas: solo lo
necesario para ver qué fuente falla y con qué datos está trabajando cada una.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY, CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import MeteoGalConfigEntry
from .const import CONF_CAMERA_ID
from .warnings import warning_details

TO_REDACT = {CONF_API_KEY, CONF_LATITUDE, CONF_LONGITUDE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MeteoGalConfigEntry
) -> dict[str, Any]:
    data = entry.runtime_data
    radar = data.radar
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
            "meteosix_key": CONF_API_KEY in entry.data,
        },
        "radar": {
            **_status(radar),
            "period": str(radar.period),
            "step": str(radar.step),
            "zoom": radar.zoom,
        },
        "meteosix": _status(data.meteosix) if data.meteosix else None,
        "cameras": {
            **_status(data.cameras),
            "count": len(data.cameras.data or {}),
        }
        if data.cameras
        else None,
        "locations": [_location(entry, subentry_id) for subentry_id in data.locations],
    }


def _location(entry: MeteoGalConfigEntry, subentry_id: str) -> dict[str, Any]:
    data = entry.runtime_data
    subentry = entry.subentries[subentry_id]
    forecast = data.locations[subentry_id]
    result: dict[str, Any] = {
        "title": subentry.title,
        "data": async_redact_data(dict(subentry.data), TO_REDACT),
        "forecast": _status(forecast),
    }
    if values := forecast.data:
        observation = values.observation
        now = dt_util.now()
        result["forecast"].update(
            daily_days=[str(day.date) for day in values.daily],
            medium_term_days=[str(day.date) for day in values.medium_term],
            hourly=_range([hour.time for hour in values.hourly]),
            observation_time=str(observation.time) if observation else None,
            warnings=[warning_details(warning, now) for warning in values.warnings],
        )
    if station := data.stations.get(subentry_id):
        result["station"] = _status(station)
        info = station.station
        result["station"]["name"] = info.name if info else None
        if station.data:
            reading, day = station.data.reading, station.data.day
            result["station"].update(
                reading_time=str(reading.time) if reading else None,
                reading=dict(reading.values) if reading else None,
                day=str(day.date) if day else None,
                day_values=dict(day.values) if day else None,
            )
    if data.meteosix and data.meteosix.data is not None:
        hours = data.meteosix.data.get(subentry_id, [])
        result["meteosix"] = {
            **_range([hour.time for hour in hours]),
            "model_run": str(hours[0].model_run) if hours else None,
        }
    if images := (data.radar.data or {}).get(subentry_id):
        result["radar"] = {
            "time": str(images.time),
            "animation_bytes": len(images.animation),
            "latest_bytes": len(images.latest),
        }
    if (camera_id := subentry.data.get(CONF_CAMERA_ID)) and data.cameras:
        camera = data.cameras.find(camera_id)
        result["camera"] = {
            "configured": camera_id,
            "key": camera.key if camera else None,
            "name": camera.name if camera else None,
            "time": str(camera.time) if camera else None,
        }
    return result


def _status(coordinator: DataUpdateCoordinator[Any]) -> dict[str, Any]:
    return {
        "last_update_success": coordinator.last_update_success,
        "last_update": str(getattr(coordinator, "last_update_success_time", None)),
        "last_exception": repr(coordinator.last_exception)
        if coordinator.last_exception
        else None,
        "update_interval": str(coordinator.update_interval),
    }


def _range(times: list[datetime]) -> dict[str, Any]:
    return {
        "count": len(times),
        "first": str(times[0]) if times else None,
        "last": str(times[-1]) if times else None,
    }
