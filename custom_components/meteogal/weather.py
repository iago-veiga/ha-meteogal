"""Entidad del tiempo de cada ubicación.

Sin clave, con los servicios públicos de MeteoGalicia. Con clave de MeteoSIX, la
previsión por horas sale entera de MeteoSIX (sin mezclar fuentes en una misma hora)
y el estado actual gana humedad, presión, nubosidad y viento (docs/weather.md).
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
    for subentry_id, coordinator in entry.runtime_data.locations.items():
        measured = None
        if coordinator.subentry.data.get(CONF_STATION_WEATHER, True):
            measured = entry.runtime_data.stations.get(subentry_id)
        async_add_entities(
            [MeteoGalWeather(coordinator, meteosix, measured)],
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
    ) -> None:
        super().__init__(coordinator)
        self._meteosix = meteosix
        # Solo si la ubicación usa su estación para el tiempo actual.
        self._station = station
        subentry = coordinator.subentry
        self._attr_unique_id = f"{subentry.subentry_id}_weather"
        self._attr_device_info = location_device(subentry)

    async def async_added_to_hass(self) -> None:
        """También se actualiza con datos nuevos de MeteoSIX y de la estación."""
        await super().async_added_to_hass()
        for other in (self._meteosix, self._station):
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
        return _round(meteosix.wind_speed) if meteosix else None

    @property
    def native_wind_gust_speed(self) -> float | None:
        """Solo de la estación: ni la previsión pública ni MeteoSIX dan rachas."""
        gust = self._measured.get(station.WIND_GUST)
        return None if gust is None else _round(gust * MS_TO_KMH)

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
        return meteosix.humidity if meteosix else None

    @property
    def native_pressure(self) -> float | None:
        if (measured := self._measured.get(station.PRESSURE)) is not None:
            return measured
        meteosix = self._meteosix_now
        return meteosix.pressure if meteosix else None

    @property
    def native_dew_point(self) -> float | None:
        return self._measured.get(station.DEW_POINT)

    @property
    def cloud_coverage(self) -> float | None:
        meteosix = self._meteosix_now
        return meteosix.cloud_coverage if meteosix else None

    @callback
    def _async_forecast_daily(self) -> list[Forecast]:
        return daily_forecast(self._data, dt_util.now(), self._meteosix_hours)

    @callback
    def _async_forecast_hourly(self) -> list[Forecast]:
        return hourly_forecast(self._data, dt_util.now(), self._meteosix_hours)


def daily_forecast(
    data: LocationData, now: datetime, meteosix: list[MeteoSixHour] | None = None
) -> list[Forecast]:
    """Corto plazo (días 0-3) seguido del medio plazo, desde hoy.

    Con MeteoSIX, los días que cubre ganan la lluvia total y el viento máximo.
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
    return forecast


def hourly_forecast(
    data: LocationData, now: datetime, meteosix: list[MeteoSixHour] | None = None
) -> list[Forecast]:
    """Desde la hora en curso: MeteoGalicia empieza siempre a las 00:00 de hoy.

    Con MeteoSIX, cada hora sale entera de una sola fuente: las que tiene MeteoSIX,
    de MeteoSIX, y solo las anteriores a su primera hora útil (la en curso, a
    veces), de la previsión pública.
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
    return public + enriched


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


def _add_meteosix_day(
    day: Forecast, hours: list[MeteoSixHour], start: datetime
) -> None:
    """Lluvia total y viento máximo del día, si MeteoSIX lo cubre entero.

    El día son las horas que empiezan de 00:00 a 23:00 (hoy, desde la hora en
    curso; 23 o 25 el día del cambio de hora), con la lluvia de cada hora en el
    dato de la hora siguiente, como en la previsión por horas. Velocidad y rumbo,
    de la misma hora: la de más viento.
    """
    midnight = datetime.fromisoformat(day["datetime"])
    # En horas reales (UTC): el día del cambio de hora tiene 23 o 25.
    end = datetime.combine(midnight.date() + timedelta(days=1), time(), TIMEZONE)
    first = max(midnight, start).astimezone(UTC)
    periods = [first + timedelta(hours=n) for n in range(int((end - first) / ONE_HOUR))]
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
