"""Coordinadores: uno por ubicación (datos públicos) y uno de MeteoSIX por entrada."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    TimestampDataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .api import (
    Camera,
    ConcelloObservation,
    DailyForecast,
    HourlyForecast,
    MediumTermForecast,
    MeteoGalClient,
    MeteoGalError,
    MeteoSixAuthError,
    MeteoSixClient,
    MeteoSixHour,
    Station,
    StationDay,
    StationReading,
    WeatherWarning,
)
from .api.meteosix import MAX_POINTS
from .api.radar import RadarClient
from .const import (
    CONF_CONCELLO_ID,
    CONF_RADAR_HOURS,
    CONF_RADAR_ZOOM,
    CONF_STATION_ID,
    DEFAULT_RADAR_HOURS,
    DEFAULT_RADAR_ZOOM,
    DOMAIN,
    ZOOM_GALICIA,
)
from .geo import load_polygons
from .radar import Marker, RadarRenderer, animation, area_around, galicia_area, still
from .station import MAX_AGE

if TYPE_CHECKING:
    from . import MeteoGalConfigEntry

_LOGGER = logging.getLogger(__name__)

# MeteoGalicia actualiza la previsión unas pocas veces al día y la observación
# cada hora: 30 minutos es suficiente y respetuoso con su servicio.
UPDATE_INTERVAL = timedelta(minutes=30)

# El modelo de 1 km de MeteoSIX sale una vez al día (hacia las 09:30) y los de 4 km
# y más, dos: cada hora es de sobra.
METEOSIX_UPDATE_INTERVAL = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class LocationData:
    """Todo lo que se descarga para una ubicación."""

    observation: ConcelloObservation | None
    daily: list[DailyForecast]
    hourly: list[HourlyForecast]
    medium_term: list[MediumTermForecast]
    warnings: list[WeatherWarning] = field(default_factory=list)


class LocationCoordinator(TimestampDataUpdateCoordinator[LocationData]):
    """Descarga la previsión y la observación de un concello."""

    config_entry: MeteoGalConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MeteoGalConfigEntry,
        subentry: ConfigSubentry,
        client: MeteoGalClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {subentry.title}",
            update_interval=UPDATE_INTERVAL,
        )
        self.subentry = subentry
        self.concello_id: int = subentry.data[CONF_CONCELLO_ID]
        self._client = client

    async def _async_update_data(self) -> LocationData:
        concello = self.concello_id
        daily, hourly, medium_term, observation, warnings = await asyncio.gather(
            self._client.get_daily_forecast(concello),
            self._client.get_hourly_forecast(concello),
            self._client.get_medium_term_forecast(concello),
            self._client.get_concello_observation(concello),
            self._client.get_warnings(concello),
            return_exceptions=True,
        )
        # Sin previsión diaria u horaria no hay nada que mostrar.
        for result in (daily, hourly):
            if isinstance(result, BaseException):
                raise UpdateFailed(f"MeteoGalicia: {result}") from result

        previous = self.data
        if isinstance(medium_term, MeteoGalError):
            _LOGGER.debug("Sin medio plazo para %s: %s", concello, medium_term)
            medium_term = previous.medium_term if previous else []
        if isinstance(observation, MeteoGalError):
            _LOGGER.debug("Sin observación para %s: %s", concello, observation)
            observation = previous.observation if previous else None
        if isinstance(warnings, MeteoGalError):
            _LOGGER.debug("Sin avisos para %s: %s", concello, warnings)
            warnings = previous.warnings if previous else []
        for result in (medium_term, observation, warnings):
            if isinstance(result, BaseException):
                raise result

        return LocationData(
            observation=observation,
            daily=daily,
            hourly=hourly,
            medium_term=medium_term,
            warnings=warnings,
        )


class MeteoSixCoordinator(
    TimestampDataUpdateCoordinator[dict[str, list[MeteoSixHour]]]
):
    """Previsión por horas de MeteoSIX de todas las ubicaciones, por id de subentrada.

    Una petición para todas (MeteoSIX admite hasta 20 puntos en cada una). Una
    ubicación sin datos de MeteoSIX no aparece en el resultado.
    """

    config_entry: MeteoGalConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MeteoGalConfigEntry,
        subentries: list[ConfigSubentry],
        client: MeteoSixClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} MeteoSIX",
            update_interval=METEOSIX_UPDATE_INTERVAL,
        )
        self._points = {
            subentry.subentry_id: (
                subentry.data[CONF_LATITUDE],
                subentry.data[CONF_LONGITUDE],
            )
            for subentry in subentries
        }
        self._client = client

    async def _async_update_data(self) -> dict[str, list[MeteoSixHour]]:
        ids = list(self._points)
        data: dict[str, list[MeteoSixHour]] = {}
        try:
            for start in range(0, len(ids), MAX_POINTS):
                batch = ids[start : start + MAX_POINTS]
                forecasts = await self._client.get_forecast(
                    [self._points[subentry_id] for subentry_id in batch]
                )
                data.update(
                    (subentry_id, hours)
                    for subentry_id, hours in zip(batch, forecasts, strict=True)
                    if hours
                )
        except MeteoSixAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MeteoGalError as err:
            raise UpdateFailed(f"MeteoSIX: {err}") from err

        for subentry_id, hours in data.items():
            _LOGGER.debug(
                "MeteoSIX %s: %d horas, de %s a %s, pasada %s",
                subentry_id,
                len(hours),
                hours[0].time,
                hours[-1].time,
                hours[0].model_run,
            )
        return data


# El radar publica una pasada cada 10 min, con ~10-15 min de retraso: mirar cada
# 5 min basta para no quedarse una pasada atrás.
RADAR_UPDATE_INTERVAL = timedelta(minutes=5)
# Separación entre fotogramas según el periodo, para que la animación no pase de
# ~13-19 fotogramas (~0,5-0,8 MB): 10 min hasta 2 h, luego 20 y 30 (docs/radar.md).
RADAR_STEP_MINUTES = {1: 10, 2: 10, 3: 20, 6: 30}


@dataclass(frozen=True, slots=True)
class RadarImages:
    """Imágenes del radar de una ubicación."""

    animation: bytes
    latest: bytes
    time: datetime


class RadarCoordinator(TimestampDataUpdateCoordinator[dict[str, RadarImages]]):
    """Radar de todas las ubicaciones de la entrada, por id de subentrada.

    Guarda las pasadas ya descargadas (PNG en grises, ~20-40 KB) y solo pide las
    nuevas; las imágenes se rehacen cuando hay una pasada nueva.
    """

    config_entry: MeteoGalConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MeteoGalConfigEntry,
        subentries: list[ConfigSubentry],
        client: RadarClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} radar",
            update_interval=RADAR_UPDATE_INTERVAL,
        )
        self._subentries = subentries
        self._client = client
        hours = int(entry.options.get(CONF_RADAR_HOURS, DEFAULT_RADAR_HOURS))
        self.period = timedelta(hours=hours)
        self.step = timedelta(minutes=RADAR_STEP_MINUTES[hours])
        self.zoom = entry.options.get(CONF_RADAR_ZOOM, DEFAULT_RADAR_ZOOM)
        self._renderers: dict[str, RadarRenderer] = {}
        self._frames: dict[tuple[str, datetime], bytes] = {}

    async def _async_update_data(self) -> dict[str, RadarImages]:
        times = await self._published_times(dt_util.utcnow())
        selected = self.select_times(times)
        if self.data and selected[-1] == next(iter(self.data.values())).time:
            return self.data  # sin pasada nueva
        if not self._renderers:
            self._renderers = await self.hass.async_add_executor_job(
                self._make_renderers
            )

        wanted = {(s.subentry_id, t) for s in self._subentries for t in selected}
        for key in [key for key in self._frames if key not in wanted]:
            del self._frames[key]
        for subentry_id, when in sorted(wanted - self._frames.keys()):
            area = self._renderers[subentry_id].area
            try:
                self._frames[subentry_id, when] = await self._client.get_frame(
                    when, area.bbox, area.width, area.height
                )
            except MeteoGalError as err:
                _LOGGER.debug("Sin la pasada de radar de %s: %s", when, err)

        return await self.hass.async_add_executor_job(self._render, selected)

    async def _published_times(self, now: datetime) -> list[datetime]:
        """Pasadas de hoy y, si el periodo empieza ayer, también de ayer (UTC).

        El fichero de hoy no existe hasta la primera pasada del día: ese error se
        pasa por alto si hay pasadas de ayer.
        """
        days = sorted({(now - self.period - self.step).date(), now.date()})
        times: list[datetime] = []
        for day in days:
            try:
                times += await self._client.get_times(day)
            except MeteoGalError as err:
                if day != now.date() or len(days) == 1:
                    raise UpdateFailed(f"Radar: {err}") from err
                _LOGGER.debug("Aún no hay radar de hoy: %s", err)
        if not times:
            raise UpdateFailed("Radar: sin pasadas publicadas")
        return times

    def select_times(self, times: list[datetime]) -> list[datetime]:
        """Pasadas de la animación: la última y, hacia atrás, una cada `step`
        durante `period`."""
        latest = times[-1]
        return [
            t
            for t in times
            if latest - self.period <= t and (latest - t) % self.step == timedelta(0)
        ]

    def _make_renderers(self) -> dict[str, RadarRenderer]:
        polygons = load_polygons()
        markers = {
            s.subentry_id: (s.data[CONF_LATITUDE], s.data[CONF_LONGITUDE])
            for s in self._subentries
        }
        renderers = {}
        for subentry_id, (lat, lon) in markers.items():
            if self.zoom == ZOOM_GALICIA:
                area = galicia_area()
            else:
                area = area_around(lat, lon, float(self.zoom))
            renderers[subentry_id] = RadarRenderer(
                area,
                polygons,
                [
                    Marker(mlat, mlon, main=other == subentry_id)
                    for other, (mlat, mlon) in markers.items()
                ],
                self.hass.config.language,
            )
        return renderers

    def _render(self, selected: list[datetime]) -> dict[str, RadarImages]:
        result = {}
        for subentry_id, renderer in self._renderers.items():
            frames = [
                renderer.frame(self._frames[subentry_id, t], dt_util.as_local(t))
                for t in selected
                if (subentry_id, t) in self._frames
            ]
            if not frames:
                continue
            last = max(t for t in selected if (subentry_id, t) in self._frames)
            result[subentry_id] = RadarImages(
                animation=animation(frames), latest=still(frames[-1]), time=last
            )
        if not result:
            raise UpdateFailed("Radar: no se pudo descargar ninguna pasada")
        return result


# Las estaciones publican cada 10 min con ~5 min de retraso.
STATION_UPDATE_INTERVAL = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class StationData:
    """Lo medido en la estación: la última lectura y lo de hoy."""

    reading: StationReading | None
    day: StationDay | None

    def fresh_reading(self, now: datetime) -> StationReading | None:
        reading = self.reading
        if reading is None or now - reading.time > MAX_AGE:
            return None
        return reading


class StationCoordinator(TimestampDataUpdateCoordinator[StationData]):
    """Lecturas de la estación de una ubicación (sin clave)."""

    config_entry: MeteoGalConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MeteoGalConfigEntry,
        subentry: ConfigSubentry,
        client: MeteoGalClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} estación {subentry.title}",
            update_interval=STATION_UPDATE_INTERVAL,
        )
        self.subentry = subentry
        self.station_id: int = subentry.data[CONF_STATION_ID]
        # Nombre y coordenadas de la estación (una vez; para el diagnóstico).
        self.station: Station | None = None
        self._client = client

    async def _async_update_data(self) -> StationData:
        if self.station is None:
            try:
                stations = await self._client.get_stations()
            except MeteoGalError as err:
                _LOGGER.debug("Sin la lista de estaciones: %s", err)
            else:
                self.station = next(
                    (s for s in stations if s.id == self.station_id), None
                )
        reading, day = await asyncio.gather(
            self._client.get_station_reading(self.station_id),
            self._client.get_station_day(self.station_id),
            return_exceptions=True,
        )
        if isinstance(reading, BaseException):
            raise UpdateFailed(f"Estación {self.station_id}: {reading}") from reading
        if isinstance(day, MeteoGalError):
            _LOGGER.debug("Sin datos de hoy de %s: %s", self.station_id, day)
            day = self.data.day if self.data else None
        elif isinstance(day, BaseException):
            raise day
        return StationData(reading=reading, day=day)


# Las cámaras cambian de imagen cada ~5 min.
CAMERA_UPDATE_INTERVAL = timedelta(minutes=5)


class CameraCoordinator(TimestampDataUpdateCoordinator[dict[str, Camera]]):
    """Cámaras de MeteoGalicia, por su clave. Una petición para todas."""

    config_entry: MeteoGalConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: MeteoGalConfigEntry, client: MeteoGalClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} cámaras",
            update_interval=CAMERA_UPDATE_INTERVAL,
        )
        self._client = client

    async def _async_update_data(self) -> dict[str, Camera]:
        try:
            cameras = await self._client.get_cameras()
        except MeteoGalError as err:
            raise UpdateFailed(f"Cámaras: {err}") from err
        return {camera.key: camera for camera in cameras}

    def find(self, camera_id: str | int | None) -> Camera | None:
        """La cámara elegida en una ubicación.

        Acepta también el identificador numérico con el que se guardaba antes (si
        hay dos cámaras con ese identificador, la primera).
        """
        cameras = self.data or {}
        if camera_id is None:
            return None
        if camera := cameras.get(str(camera_id)):
            return camera
        return next((c for c in cameras.values() if str(c.id) == str(camera_id)), None)
