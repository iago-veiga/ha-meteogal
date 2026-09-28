"""Cliente de MeteoGalicia sin dependencias de Home Assistant."""

from .client import MeteoGalClient
from .exceptions import (
    MeteoGalConnectionError,
    MeteoGalError,
    MeteoGalNotFoundError,
    MeteoGalResponseError,
    MeteoSixAuthError,
    MeteoSixError,
)
from .meteosix import MeteoSixClient
from .models import (
    Camera,
    Concello,
    ConcelloObservation,
    DailyForecast,
    DayParts,
    HourlyForecast,
    MediumTermForecast,
    MeteoSixHour,
    SkyProbability,
    Station,
    StationDay,
    StationReading,
    WeatherWarning,
)

__all__ = [
    "Camera",
    "Concello",
    "ConcelloObservation",
    "DailyForecast",
    "DayParts",
    "HourlyForecast",
    "MediumTermForecast",
    "MeteoGalClient",
    "MeteoGalConnectionError",
    "MeteoGalError",
    "MeteoGalNotFoundError",
    "MeteoGalResponseError",
    "MeteoSixAuthError",
    "MeteoSixClient",
    "MeteoSixError",
    "MeteoSixHour",
    "SkyProbability",
    "Station",
    "StationDay",
    "StationReading",
    "WeatherWarning",
]
