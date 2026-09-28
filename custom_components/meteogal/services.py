"""Acción `meteogal.get_warnings`: el detalle de los avisos, como hace
`weather.get_forecasts` con la previsión (docs/avisos.md)."""

from __future__ import annotations

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.helpers import service

from .const import DOMAIN

SERVICE_GET_WARNINGS = "get_warnings"


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Solo se puede lanzar sobre los sensores de nivel de aviso (los únicos enum)."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_GET_WARNINGS,
        entity_domain=SENSOR_DOMAIN,
        entity_device_classes=[SensorDeviceClass.ENUM],
        schema=None,
        func="get_warnings",
        supports_response=SupportsResponse.ONLY,
    )
