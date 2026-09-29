"""Acción `meteogal.get_warnings`: el detalle de los avisos, como hace
`weather.get_forecasts` con la previsión (docs/avisos.md)."""

from __future__ import annotations

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.helpers import service

from .const import DOMAIN

SERVICE_GET_WARNINGS = "get_warnings"
SERVICE_GET_AIR_QUALITY = "get_air_quality"


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Las dos sobre los sensores enum de MeteoGal: `get_warnings` sobre el nivel de
    aviso y `get_air_quality` sobre la calidad del aire. Sobre otro sensor, error
    claro (`EnumActions`)."""
    for name in (SERVICE_GET_WARNINGS, SERVICE_GET_AIR_QUALITY):
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=SENSOR_DOMAIN,
            entity_device_classes=[SensorDeviceClass.ENUM],
            schema=None,
            func=name,
            supports_response=SupportsResponse.ONLY,
        )
