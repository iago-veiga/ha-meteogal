"""Constantes de MeteoGal."""

from typing import Final

DOMAIN: Final = "meteogal"
NAME: Final = "MeteoGal"

SUBENTRY_LOCATION: Final = "location"

CONF_CONCELLO_ID: Final = "concello_id"
CONF_STATION_ID: Final = "station_id"
# Usar lo medido en la estación para el tiempo actual de la entidad weather.
CONF_STATION_WEATHER: Final = "station_weather"
CONF_CAMERA_ID: Final = "camera_id"
# Estación de la Rede de Calidade do Aire y si manda en la calidad del aire actual.
CONF_AIR_STATION_ID: Final = "air_station_id"
CONF_AIR_STATION_USE: Final = "air_station_use"

# No se traduce: Home Assistant muestra la atribución tal cual.
ATTRIBUTION: Final = "MeteoGalicia · Xunta de Galicia"

# Opciones del radar (entrada MeteoGal).
CONF_RADAR_HOURS: Final = "radar_hours"
CONF_RADAR_ZOOM: Final = "radar_zoom"
RADAR_HOURS: Final = ("1", "2", "3", "6")
DEFAULT_RADAR_HOURS: Final = "2"
ZOOM_GALICIA: Final = "galicia"
RADAR_ZOOMS: Final = ("50", "100", ZOOM_GALICIA)
DEFAULT_RADAR_ZOOM: Final = "100"
