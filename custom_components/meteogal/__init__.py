"""MeteoGal: previsión y datos de MeteoGalicia para Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import MeteoGalClient, MeteoSixClient
from .api.radar import RadarClient
from .const import CONF_CAMERA_ID, CONF_STATION_ID, DOMAIN, SUBENTRY_LOCATION
from .coordinator import (
    CameraCoordinator,
    LocationCoordinator,
    MeteoSixCoordinator,
    RadarCoordinator,
    StationCoordinator,
)
from .repairs import ISSUE_PREFIX, async_clean_issues
from .services import async_setup_services

PLATFORMS = [Platform.IMAGE, Platform.SENSOR, Platform.WEATHER]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class MeteoGalData:
    """Coordinadores de la entrada."""

    # Datos públicos de cada ubicación, por el id de su subentrada.
    locations: dict[str, LocationCoordinator]
    # Solo con clave de MeteoSIX.
    meteosix: MeteoSixCoordinator | None
    # Radar de todas las ubicaciones.
    radar: RadarCoordinator
    # Estación de cada ubicación que la tenga, por id de subentrada.
    stations: dict[str, StationCoordinator]
    # Solo si alguna ubicación tiene cámara.
    cameras: CameraCoordinator | None


type MeteoGalConfigEntry = ConfigEntry[MeteoGalData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Acciones de MeteoGal (se registran una vez, aunque no haya entradas)."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MeteoGalConfigEntry) -> bool:
    """Configura MeteoGal. Las ubicaciones son subentradas de esta entrada."""
    session = async_get_clientsession(hass)
    client = MeteoGalClient(session)
    locations = [
        subentry
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_LOCATION
    ]
    coordinators: dict[str, LocationCoordinator] = {}
    for subentry in locations:
        coordinator = LocationCoordinator(hass, entry, subentry, client)
        await coordinator.async_config_entry_first_refresh()
        coordinators[subentry.subentry_id] = coordinator

    meteosix = None
    if (api_key := entry.data.get(CONF_API_KEY)) and locations:
        meteosix = MeteoSixCoordinator(
            hass, entry, locations, MeteoSixClient(session, api_key)
        )
        # La clave suma, no sustituye: si MeteoSIX falla, MeteoGal arranca igual con
        # los datos públicos. Con la clave rechazada se abre la reautenticación.
        await meteosix.async_refresh()
    radar = RadarCoordinator(hass, entry, locations, RadarClient(session))
    # Complemento, como MeteoSIX: si el THREDDS falla, el radar queda no
    # disponible y el resto de MeteoGal arranca igual.
    await radar.async_refresh()
    # Estaciones y cámaras, complemento como el radar: si fallan, lo demás sigue.
    stations: dict[str, StationCoordinator] = {}
    for subentry in locations:
        if subentry.data.get(CONF_STATION_ID):
            station = StationCoordinator(hass, entry, subentry, client)
            await station.async_refresh()
            stations[subentry.subentry_id] = station
    cameras = None
    if any(subentry.data.get(CONF_CAMERA_ID) for subentry in locations):
        cameras = CameraCoordinator(hass, entry, client)
        await cameras.async_refresh()
    async_clean_issues(hass, entry)
    entry.runtime_data = MeteoGalData(
        locations=coordinators,
        meteosix=meteosix,
        radar=radar,
        stations=stations,
        cameras=cameras,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MeteoGalConfigEntry) -> bool:
    """Descarga MeteoGal."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: MeteoGalConfigEntry) -> None:
    """Al borrar MeteoGal, sus avisos de reparación también."""
    for subentry_id in entry.subentries:
        ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_PREFIX}{subentry_id}")


async def _async_reload(hass: HomeAssistant, entry: MeteoGalConfigEntry) -> None:
    """Recarga al añadir, cambiar o quitar ubicaciones."""
    await hass.config_entries.async_reload(entry.entry_id)
