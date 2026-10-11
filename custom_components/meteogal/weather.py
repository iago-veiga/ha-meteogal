"""Entidad del tiempo de cada ubicación.

Sin clave, con los servicios públicos de MeteoGalicia. Con clave de MeteoSIX, la
previsión por horas sale entera de MeteoSIX (sin mezclar fuentes en una misma hora)
y el estado actual gana humedad, presión, nubosidad y viento (docs/weather.md).

El WRF de 4 km (THREDDS, sin clave) da la racha prevista, que MeteoSIX no da, y hace de
respaldo de viento, humedad y presión donde no hay ni estación ni MeteoSIX. No aporta ni
lluvia ni cielo: sus lluvias chocan con los iconos públicos (docs/wrf.md).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from homeassistant.components.weather import (
    Forecast,
    SingleCoordinatorWeatherEntity,
)
from homeassistant.components.weather.const import WeatherEntityFeature
from homeassistant.const import (
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import MeteoGalConfigEntry, station
from .api import (
    DailyForecast,
    DayParts,
    HourlyForecast,
    MediumTermForecast,
    MeteoSixHour,
    WrfHour,
)
from .api.client import TIMEZONE
from .codes import (
    PRECIPITATION_CONDITIONS,
    condition,
    meteosix_condition,
    wind_bearing,
    wind_intensity,
)
from .const import ATTRIBUTION, CONF_STATION_WEATHER
from .coordinator import (
    LocationCoordinator,
    LocationData,
    MeteoSixCoordinator,
    StationCoordinator,
    WrfCoordinator,
)
from .entity import location_device
from .station import clean

ONE_HOUR = timedelta(hours=1)
MS_TO_KMH = 3.6


# Todo llega de coordinadores: no hay actualizaciones por entidad que limitar.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeteoGalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Una entidad del tiempo por ubicación."""
    meteosix = entry.runtime_data.meteosix
    wrf = entry.runtime_data.wrf
    for subentry_id, coordinator in entry.runtime_data.locations.items():
        measured = None
        if coordinator.subentry.data.get(CONF_STATION_WEATHER, True):
            measured = entry.runtime_data.stations.get(subentry_id)
        async_add_entities(
            [MeteoGalWeather(coordinator, meteosix, measured, wrf)],
            config_subentry_id=subentry_id,
        )


class MeteoGalWeather(SingleCoordinatorWeatherEntity[LocationCoordinator]):
    """El tiempo en un concello: estado actual y previsión diaria y horaria."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_attribution = ATTRIBUTION
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(
        self,
        coordinator: LocationCoordinator,
        meteosix: MeteoSixCoordinator | None,
        station: StationCoordinator | None = None,
        wrf: WrfCoordinator | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._meteosix = meteosix
        self._wrf = wrf
        # Solo si la ubicación usa su estación para el tiempo actual.
        self._station = station
        subentry = coordinator.subentry
        self._attr_unique_id = f"{subentry.subentry_id}_weather"
        self._attr_device_info = location_device(subentry)

    async def async_added_to_hass(self) -> None:
        """También se actualiza con datos nuevos de MeteoSIX, la estación y el WRF."""
        await super().async_added_to_hass()
        for other in (self._meteosix, self._station, self._wrf):
            if other:
                self.async_on_remove(
                    other.async_add_listener(self._handle_coordinator_update)
                )

    @property
    def _data(self) -> LocationData:
        return self.coordinator.data

    @property
    def _meteosix_hours(self) -> list[MeteoSixHour]:
        """Horas de MeteoSIX de esta ubicación; vacío sin clave o sin datos."""
        if not self._meteosix or not self._meteosix.data:
            return []
        return self._meteosix.data.get(self.coordinator.subentry.subentry_id, [])

    @property
    def _meteosix_now(self) -> MeteoSixHour | None:
        """La hora de MeteoSIX más cercana a ahora, si está a menos de una hora."""
        now = dt_util.now()
        nearest = min(
            self._meteosix_hours, key=lambda h: abs(h.time - now), default=None
        )
        return nearest if nearest and abs(nearest.time - now) <= ONE_HOUR else None

    @property
    def _wrf_hours(self) -> list[WrfHour]:
        """Horas del WRF de esta ubicación; vacío si el THREDDS no ha respondido."""
        if not self._wrf or not self._wrf.data:
            return []
        return self._wrf.data.hours.get(self.coordinator.subentry.subentry_id, [])

    @property
    def _wrf_now(self) -> WrfHour | None:
        """La hora del WRF más cercana a ahora, si está a menos de una hora."""
        now = dt_util.now()
        nearest = min(self._wrf_hours, key=lambda h: abs(h.time - now), default=None)
        return nearest if nearest and abs(nearest.time - now) <= ONE_HOUR else None

    @property
    def _measured(self) -> dict[str, float]:
        """Lo medido ahora en la estación (vacío sin estación o si no envía)."""
        data = self._station.data if self._station else None
        reading = data.fresh_reading(dt_util.utcnow()) if data else None
        return clean(reading) if reading else {}

    @property
    def _current_hour(self) -> HourlyForecast | None:
        now = dt_util.now()
        return next((h for h in reversed(self._data.hourly) if h.time <= now), None)

    @property
    def condition(self) -> str | None:
        """Del estado actual del concello; si falta, de la previsión de esta hora."""
        observation = self._data.observation
        if observation and (result := condition(observation.sky)):
            return result
        hour = self._current_hour
        return condition(hour.sky) if hour else None

    @property
    def native_temperature(self) -> float | None:
        # Lo medido en la estación, luego el concello y luego la previsión.
        if (measured := self._measured.get(station.TEMPERATURE)) is not None:
            return measured
        observation = self._data.observation
        if observation and observation.temperature is not None:
            return observation.temperature
        hour = self._current_hour
        return hour.temperature if hour else None

    @property
    def native_apparent_temperature(self) -> float | None:
        observation = self._data.observation
        return observation.apparent_temperature if observation else None

    @property
    def wind_bearing(self) -> float | None:
        # Velocidad y rumbo de la misma fuente: estación, MeteoSIX o concello.
        if (wind := self._measured_wind) is not None:
            return wind[1]
        if meteosix := self._meteosix_now:
            return meteosix.wind_bearing
        if (wrf := self._wrf_now) and wrf.wind_bearing is not None:
            return wrf.wind_bearing
        observation = self._data.observation
        if observation and observation.wind is not None:
            return wind_bearing(observation.wind)
        hour = self._current_hour
        return wind_bearing(hour.wind) if hour else None

    @property
    def native_wind_speed(self) -> float | None:
        if (wind := self._measured_wind) is not None:
            return wind[0]
        meteosix = self._meteosix_now
        if meteosix and meteosix.wind_speed is not None:
            return _round(meteosix.wind_speed)
        wrf = self._wrf_now
        return _round(wrf.wind_speed) if wrf else None

    @property
    def native_wind_gust_speed(self) -> float | None:
        """De la estación; sin ella, del WRF (ni la pública ni MeteoSIX dan rachas),
        nunca por debajo del viento medio que se muestra."""
        gust = self._measured.get(station.WIND_GUST)
        if gust is not None:
            return _round(gust * MS_TO_KMH)
        wrf = self._wrf_now
        if wrf is None or wrf.gust is None:
            return None
        return _round(max(wrf.gust, self.native_wind_speed or 0.0))

    @property
    def _measured_wind(self) -> tuple[float, float] | None:
        """Velocidad (km/h) y rumbo de la estación, solo si tiene los dos."""
        measured = self._measured
        speed = measured.get(station.WIND_SPEED)
        bearing = measured.get(station.WIND_BEARING)
        if speed is None or bearing is None:
            return None
        return round(speed * MS_TO_KMH, 1), bearing

    @property
    def humidity(self) -> float | None:
        if (measured := self._measured.get(station.HUMIDITY)) is not None:
            return measured
        meteosix = self._meteosix_now
        if meteosix and meteosix.humidity is not None:
            return meteosix.humidity
        wrf = self._wrf_now
        return wrf.humidity if wrf else None

    @property
    def native_pressure(self) -> float | None:
        if (measured := self._measured.get(station.PRESSURE)) is not None:
            return measured
        meteosix = self._meteosix_now
        if meteosix and meteosix.pressure is not None:
            return meteosix.pressure
        wrf = self._wrf_now
        return wrf.pressure if wrf else None

    @property
    def native_dew_point(self) -> float | None:
        return self._measured.get(station.DEW_POINT)

    @property
    def cloud_coverage(self) -> float | None:
        meteosix = self._meteosix_now
        return meteosix.cloud_coverage if meteosix else None

    @callback
    def _async_forecast_daily(self) -> list[Forecast]:
        return daily_forecast(
            self._data, dt_util.now(), self._meteosix_hours, self._wrf_hours
        )

    @callback
    def _async_forecast_hourly(self) -> list[Forecast]:
        return hourly_forecast(
            self._data, dt_util.now(), self._meteosix_hours, self._wrf_hours
        )


def daily_forecast(
    data: LocationData,
    now: datetime,
    meteosix: list[MeteoSixHour] | None = None,
    wrf: list[WrfHour] | None = None,
) -> list[Forecast]:
    """Corto plazo (días 0-3) seguido del medio plazo, desde hoy.

    Con MeteoSIX, los días que cubre ganan la lluvia total y el viento máximo. Con el
    WRF, los días que cubre entero ganan la racha máxima y, si no los había puesto
    MeteoSIX, el viento máximo.
    """
    today = now.date()
    forecast = [_from_daily(day) for day in data.daily if day.date >= today]
    covered = {day.date for day in data.daily}
    forecast += [
        _from_medium_term(day)
        for day in data.medium_term
        if day.date >= today and day.date not in covered
    ]
    if meteosix:
        start = now.replace(minute=0, second=0, microsecond=0)
        for day in forecast:
            _add_meteosix_day(day, meteosix, start)
    if wrf:
        start = now.replace(minute=0, second=0, microsecond=0)
        for day in forecast:
            _add_wrf_day(day, wrf, start)
    return forecast


def hourly_forecast(
    data: LocationData,
    now: datetime,
    meteosix: list[MeteoSixHour] | None = None,
    wrf: list[WrfHour] | None = None,
) -> list[Forecast]:
    """Desde la hora en curso: MeteoGalicia empieza siempre a las 00:00 de hoy.

    Con MeteoSIX, cada hora sale entera de una sola fuente: las que tiene MeteoSIX,
    de MeteoSIX, y solo las anteriores a su primera hora útil (la en curso, a
    veces), de la previsión pública. El WRF añade a todas las horas la racha y, a las
    que no la tienen de MeteoSIX, el viento, la humedad y la presión; nunca la lluvia
    ni el cielo.
    """
    start = now.replace(minute=0, second=0, microsecond=0)
    enriched = _from_meteosix(meteosix, start) if meteosix else []
    # Si los datos de MeteoSIX se han quedado viejos, todo sale de la pública.
    first = datetime.fromisoformat(enriched[0]["datetime"]) if enriched else None
    public = [
        Forecast(
            datetime=hour.time.isoformat(),
            condition=condition(hour.sky),
            native_temperature=hour.temperature,
            wind_bearing=wind_bearing(hour.wind),
        )
        for hour in data.hourly
        if hour.time >= start and (first is None or hour.time < first)
    ]
    forecast = public + enriched
    if wrf:
        _add_wrf_hours(forecast, wrf)
    return forecast


def _from_meteosix(hours: list[MeteoSixHour], start: datetime) -> list[Forecast]:
    """Horas de MeteoSIX desde `start`.

    En MeteoSIX, la lluvia, el estado del cielo y la nubosidad de cada hora son los
    de la hora anterior (van juntos: validado con unas 850 horas en 6 concellos).
    Home Assistant, como met.no, espera los de la hora que empieza. Por eso cielo,
    lluvia y nubosidad de las 10:00 salen del dato de las 11:00, y el resto
    (temperatura, viento, humedad, presión, instantáneos) del de las 10:00. La
    última hora se descarta: no tiene cielo ni lluvia.
    """
    by_time = {hour.time: hour for hour in hours}
    forecast = []
    for hour in hours:
        following = by_time.get(hour.time + ONE_HOUR)
        if hour.time < start or following is None:
            continue
        forecast.append(
            Forecast(
                datetime=hour.time.isoformat(),
                condition=meteosix_condition(following.sky, following.night),
                native_temperature=hour.temperature,
                native_precipitation=following.precipitation,
                native_wind_speed=_round(hour.wind_speed),
                wind_bearing=hour.wind_bearing,
                humidity=hour.humidity,
                cloud_coverage=_percent(following.cloud_coverage),
                native_pressure=hour.pressure,
            )
        )
    return forecast


def _day_periods(day: Forecast, start: datetime) -> list[datetime]:
    """Las horas (UTC) que empiezan dentro del día: de 00:00 a 23:00 (hoy, desde la
    hora en curso; 23 o 25 el día del cambio de hora)."""
    midnight = datetime.fromisoformat(day["datetime"])
    # En horas reales (UTC): el día del cambio de hora tiene 23 o 25.
    end = datetime.combine(midnight.date() + timedelta(days=1), time(), TIMEZONE)
    first = max(midnight, start).astimezone(UTC)
    return [first + timedelta(hours=n) for n in range(int((end - first) / ONE_HOUR))]


def _add_wrf_hours(forecast: list[Forecast], hours: list[WrfHour]) -> None:
    """Racha de cada hora y, donde falten, viento, humedad y presión del WRF.

    Todo es instantáneo en la hora de la entrada (validado: la racha casa con la
    medida de esa hora). La racha nunca queda por debajo del viento medio de la hora:
    el WRF de 4 km se queda corto en un 13 % de las horas frente a MeteoSIX. Con la
    velocidad del WRF, el rumbo sigue siendo el de la previsión pública.
    """
    by_time = {hour.time: hour for hour in hours}
    for item in forecast:
        hour = by_time.get(datetime.fromisoformat(item["datetime"]).astimezone(UTC))
        if hour is None:
            continue
        speed = item.get("native_wind_speed")
        if speed is None and hour.wind_speed is not None:
            speed = item["native_wind_speed"] = _round(hour.wind_speed)
        if item.get("humidity") is None and hour.humidity is not None:
            item["humidity"] = hour.humidity
        if item.get("native_pressure") is None and hour.pressure is not None:
            item["native_pressure"] = hour.pressure
        if hour.gust is not None:
            item["native_wind_gust_speed"] = _round(max(hour.gust, speed or 0.0))


def _add_wrf_day(day: Forecast, hours: list[WrfHour], start: datetime) -> None:
    """Racha máxima del día y, si falta, viento máximo, si el WRF cubre el día entero
    (hoy, desde la hora en curso), como con MeteoSIX."""
    periods = _day_periods(day, start)
    by_time = {hour.time: hour for hour in hours}
    if not periods or any(period not in by_time for period in periods):
        return
    day_hours = [by_time[period] for period in periods]
    speeds = [h.wind_speed for h in day_hours if h.wind_speed is not None]
    if "native_wind_speed" not in day and speeds:
        day["native_wind_speed"] = _round(max(speeds))
    gusts = [h.gust for h in day_hours if h.gust is not None]
    if gusts:
        day["native_wind_gust_speed"] = _round(
            max(max(gusts), day.get("native_wind_speed") or 0.0)
        )


def _add_meteosix_day(
    day: Forecast, hours: list[MeteoSixHour], start: datetime
) -> None:
    """Lluvia total y viento máximo del día, si MeteoSIX lo cubre entero.

    El día son las horas que empiezan de 00:00 a 23:00 (hoy, desde la hora en
    curso; 23 o 25 el día del cambio de hora), con la lluvia de cada hora en el
    dato de la hora siguiente, como en la previsión por horas. Velocidad y rumbo,
    de la misma hora: la de más viento.
    """
    periods = _day_periods(day, start)
    by_time = {hour.time: hour for hour in hours}
    rain = [
        hour.precipitation if (hour := by_time.get(period + ONE_HOUR)) else None
        for period in periods
    ]
    if not periods or any(amount is None for amount in rain):
        return
    day["native_precipitation"] = round(
        sum(amount for amount in rain if amount is not None), 1
    )
    windy = max(
        (
            by_time[period]
            for period in periods
            if period in by_time and by_time[period].wind_speed is not None
        ),
        key=lambda hour: hour.wind_speed or 0.0,
        default=None,
    )
    if windy:
        day["native_wind_speed"] = _round(windy.wind_speed)
        day["wind_bearing"] = windy.wind_bearing


def _percent(value: float | None) -> int | None:
    """Nubosidad entera, como la pide la previsión de HA (MeteoSIX da 43,75)."""
    return None if value is None else round(value)


def _round(value: float | None) -> float | None:
    """Velocidades con un decimal: MeteoSIX da dos y no aportan nada."""
    return None if value is None else round(value, 1)


def _from_daily(day: DailyForecast) -> Forecast:
    probabilities = _values(day.precipitation_probability)
    return Forecast(
        datetime=_midnight(day.date),
        condition=condition(day.sky),
        native_temperature=day.temperature_max,
        native_templow=day.temperature_min,
        precipitation_probability=max(probabilities) if probabilities else None,
        uv_index=day.uv_max,
        wind_bearing=_strongest_wind_bearing(day.wind),
    )


def _from_medium_term(day: MediumTermForecast) -> Forecast:
    likely = max(day.sky, key=lambda s: s.probability or 0, default=None)
    return Forecast(
        datetime=_midnight(day.date),
        condition=condition(likely.sky) if likely else None,
        native_temperature=day.temperature_max,
        native_templow=day.temperature_min,
        precipitation_probability=_precipitation_probability(day),
        wind_bearing=wind_bearing(day.wind),
    )


def _precipitation_probability(day: MediumTermForecast) -> int | None:
    """Suma de las probabilidades de los cielos con precipitación."""
    known = [s for s in day.sky if s.probability is not None]
    if not known:
        return None
    return min(
        100,
        sum(
            s.probability or 0
            for s in known
            if condition(s.sky) in PRECIPITATION_CONDITIONS
        ),
    )


def _strongest_wind_bearing(parts: DayParts[int | None]) -> float | None:
    """Rumbo de la franja con más viento.

    A igual intensidad gana la que tiene rumbo (el variable cuenta como flojo pero
    no tiene dirección) y, después, tarde, mañana y noche.
    """
    codes = [parts.afternoon, parts.morning, parts.night]
    strongest = max(
        codes,
        key=lambda code: (wind_intensity(code) or -1, wind_bearing(code) is not None),
    )
    return wind_bearing(strongest)


def _values(parts: DayParts[int | None]) -> list[int]:
    return [v for v in (parts.morning, parts.afternoon, parts.night) if v is not None]


def _midnight(day: date) -> str:
    return datetime.combine(day, time(), TIMEZONE).isoformat()
