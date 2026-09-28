"""Configuración de MeteoGal.

Una sola entrada MeteoGal y cada ubicación como subentrada (D1 en docs/diseno.md).
Añadir una ubicación son dos pasos, iguales en la primera instalación y después:

1. `location`: un punto en el mapa, por defecto la casa de Home Assistant.
2. `confirm`: concello y estación deducidos del punto, ya elegidos; el usuario solo
   confirma o corrige.

La clave de MeteoSIX es opcional y va en la entrada, no en las ubicaciones: se añade,
cambia o quita reconfigurando la entrada, y se vuelve a pedir si deja de valer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any, override

from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import (
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    LocationSelector,
    LocationSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import (
    Camera,
    MeteoGalClient,
    MeteoGalError,
    MeteoSixAuthError,
    MeteoSixClient,
    Station,
)
from .const import (
    CONF_CAMERA_ID,
    CONF_CONCELLO_ID,
    CONF_RADAR_HOURS,
    CONF_RADAR_ZOOM,
    CONF_STATION_ID,
    CONF_STATION_WEATHER,
    DEFAULT_RADAR_HOURS,
    DEFAULT_RADAR_ZOOM,
    DOMAIN,
    NAME,
    RADAR_HOURS,
    RADAR_ZOOMS,
    SUBENTRY_LOCATION,
)
from .geo import ConcelloLocator, distance_km
from .toponyms import load_toponyms

_LOGGER = logging.getLogger(__name__)

# Dos ubicaciones a menos de ~10 m se consideran la misma.
SAME_LOCATION_DEGREES = 1e-4

# Página de MeteoGalicia donde se pide la clave. Fuera de las traducciones, que no
# admiten URL.
METEOSIX_KEY_URL = "https://www.meteogalicia.gal/web/modelos-numericos/meteosix"


@dataclass(slots=True)
class _Candidate:
    """Lo deducido de un punto, para rellenar el paso de confirmación."""

    latitude: float
    longitude: float
    concello_id: int
    toponyms: dict[int, str]
    # Estaciones de la más cercana a la más lejana, con su concello y distancia.
    stations: list[tuple[Station, int | None, float]]
    # Cámaras de la más cercana a la más lejana, con su distancia (vacío si falla:
    # la cámara es opcional).
    cameras: list[tuple[Camera, float]]


async def _async_candidate(
    hass: HomeAssistant, latitude: float, longitude: float, errors: dict[str, str]
) -> _Candidate | None:
    """Deduce concello y estaciones de un punto, o rellena `errors`."""
    locator, toponyms = await hass.async_add_executor_job(_load_data)
    concello_id = locator.locate(latitude, longitude)
    if concello_id is None:
        errors["base"] = "outside_galicia"
        return None

    client = MeteoGalClient(async_get_clientsession(hass))
    try:
        stations = await client.get_stations()
    except MeteoGalError as err:
        _LOGGER.debug("No se pudo obtener la lista de estaciones: %s", err)
        errors["base"] = "cannot_connect"
        return None

    ranked = sorted(
        (
            (
                station,
                locator.locate(station.latitude, station.longitude),
                distance_km(latitude, longitude, station.latitude, station.longitude),
            )
            for station in stations
        ),
        key=lambda item: item[2],
    )
    try:
        cameras = await client.get_cameras()
    except MeteoGalError as err:
        _LOGGER.debug("No se pudo obtener la lista de cámaras: %s", err)
        cameras = []
    ranked_cameras = sorted(
        (
            (
                camera,
                distance_km(latitude, longitude, camera.latitude, camera.longitude),
            )
            for camera in cameras
        ),
        key=lambda item: item[1],
    )
    return _Candidate(
        latitude, longitude, concello_id, toponyms, ranked, ranked_cameras
    )


def camera_position(camera: Camera) -> tuple[float, float]:
    return camera.latitude, camera.longitude


def _load_data() -> tuple[ConcelloLocator, dict[int, str]]:
    return ConcelloLocator.load(), load_toponyms()


def _location_schema(hass: HomeAssistant) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_LOCATION,
                default={
                    CONF_LATITUDE: hass.config.latitude,
                    CONF_LONGITUDE: hass.config.longitude,
                },
            ): LocationSelector(LocationSelectorConfig(radius=False)),
        }
    )


def _confirm_schema(hass: HomeAssistant, candidate: _Candidate) -> vol.Schema:
    decimal = "." if hass.config.language.startswith("en") else ","
    concellos = sorted(candidate.toponyms.items(), key=lambda item: _sort_key(item[1]))
    stations = [
        SelectOptionDict(
            value=str(station.id),
            label=(
                f"{station.name} ({candidate.toponyms.get(concello_id, '?')}) · "
                f"{distance:.1f} km".replace(".", decimal)
            ),
        )
        for station, concello_id, distance in candidate.stations
    ]
    cameras = [
        SelectOptionDict(
            value=camera.key,
            label=(
                f"{camera.name} ({candidate.toponyms.get(camera.concello_id, '?')}) · "
                f"{distance:.1f} km".replace(".", decimal)
            ),
        )
        for camera, distance in candidate.cameras
    ]
    return vol.Schema(
        {
            vol.Required(CONF_CONCELLO_ID): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=str(code), label=name)
                        for code, name in concellos
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                    sort=False,
                )
            ),
            vol.Optional(CONF_STATION_ID): SelectSelector(
                SelectSelectorConfig(
                    options=stations, mode=SelectSelectorMode.DROPDOWN, sort=False
                )
            ),
            vol.Optional(CONF_STATION_WEATHER): BooleanSelector(),
            vol.Optional(CONF_CAMERA_ID): SelectSelector(
                SelectSelectorConfig(
                    options=cameras, mode=SelectSelectorMode.DROPDOWN, sort=False
                )
            ),
        }
    )


def _confirm_placeholders(candidate: _Candidate) -> dict[str, str]:
    return {"concello": candidate.toponyms[candidate.concello_id]}


async def _async_check_api_key(
    hass: HomeAssistant, api_key: str, errors: dict[str, str]
) -> bool:
    """Comprueba la clave con MeteoSIX, o rellena `errors`."""
    client = MeteoSixClient(async_get_clientsession(hass), api_key)
    try:
        await client.check_key()
    except MeteoSixAuthError:
        errors[CONF_API_KEY] = "invalid_api_key"
    except MeteoGalError as err:
        _LOGGER.debug("No se pudo comprobar la clave de MeteoSIX: %s", err)
        errors["base"] = "cannot_connect_meteosix"
    return not errors


def _sort_key(name: str) -> str:
    """Ordena por el nombre sin artículo: "A Coruña" junto a "Culleredo"."""
    for article in ("A ", "O ", "As ", "Os "):
        if name.startswith(article):
            return name.removeprefix(article).casefold()
    return name.casefold()


def _location_data(candidate: _Candidate, user_input: dict[str, Any]) -> dict:
    station = user_input.get(CONF_STATION_ID)
    camera = user_input.get(CONF_CAMERA_ID)
    return {
        CONF_LATITUDE: candidate.latitude,
        CONF_LONGITUDE: candidate.longitude,
        CONF_CONCELLO_ID: int(user_input[CONF_CONCELLO_ID]),
        CONF_STATION_ID: int(station) if station else None,
        CONF_STATION_WEATHER: bool(user_input.get(CONF_STATION_WEATHER, True)),
        CONF_CAMERA_ID: camera or None,
    }


def _is_already_configured(
    hass: HomeAssistant,
    latitude: float,
    longitude: float,
    exclude_subentry_id: str | None = None,
) -> bool:
    return any(
        abs(subentry.data[CONF_LATITUDE] - latitude) <= SAME_LOCATION_DEGREES
        and abs(subentry.data[CONF_LONGITUDE] - longitude) <= SAME_LOCATION_DEGREES
        for entry in hass.config_entries.async_entries(DOMAIN)
        for subentry in entry.subentries.values()
        if subentry.subentry_id != exclude_subentry_id
    )


class MeteoGalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Primera instalación: la entrada MeteoGal con su primera ubicación."""

    VERSION = 1

    _candidate: _Candidate

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Paso 1: elegir el punto."""
        errors: dict[str, str] = {}
        if user_input is not None:
            location = user_input[CONF_LOCATION]
            candidate = await _async_candidate(
                self.hass, location[CONF_LATITUDE], location[CONF_LONGITUDE], errors
            )
            if candidate:
                self._candidate = candidate
                return await self.async_step_confirm()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _location_schema(self.hass), user_input
            ),
            errors=errors,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Paso 2: confirmar concello y estación."""
        candidate = self._candidate
        if user_input is not None:
            data = _location_data(candidate, user_input)
            return self.async_create_entry(
                title=NAME,
                data={},
                subentries=[
                    {
                        "subentry_type": SUBENTRY_LOCATION,
                        "data": data,
                        "title": candidate.toponyms[data[CONF_CONCELLO_ID]],
                        "unique_id": None,
                    }
                ],
            )

        return self.async_show_form(
            step_id="confirm",
            data_schema=self.add_suggested_values_to_schema(
                _confirm_schema(self.hass, candidate), _suggested(candidate)
            ),
            description_placeholders=_confirm_placeholders(candidate),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Añadir, cambiar o quitar la clave de MeteoSIX."""
        return await self._async_step_api_key(
            "reconfigure", self._get_reconfigure_entry(), user_input
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """MeteoSIX ya no acepta la clave guardada."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pedir otra clave, o quitarla para seguir sin MeteoSIX."""
        return await self._async_step_api_key(
            "reauth_confirm", self._get_reauth_entry(), user_input
        )

    async def _async_step_api_key(
        self, step_id: str, entry: ConfigEntry, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Formulario común de la clave. Vacía, se quita la clave."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input.get(CONF_API_KEY, "").strip()
            data = {k: v for k, v in entry.data.items() if k != CONF_API_KEY}
            if api_key:
                data[CONF_API_KEY] = api_key
            if not api_key or await _async_check_api_key(self.hass, api_key, errors):
                return self.async_update_reload_and_abort(entry, data=data)
        elif step_id == "reconfigure":
            user_input = {CONF_API_KEY: entry.data.get(CONF_API_KEY, "")}

        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_API_KEY): TextSelector(
                            TextSelectorConfig(type=TextSelectorType.PASSWORD)
                        )
                    }
                ),
                user_input,
            ),
            errors=errors,
            description_placeholders={"url": METEOSIX_KEY_URL},
        )

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Opciones del radar."""
        return MeteoGalOptionsFlow()

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Las ubicaciones son subentradas."""
        return {SUBENTRY_LOCATION: LocationSubentryFlow}


class MeteoGalOptionsFlow(OptionsFlow):
    """Periodo y encuadre del radar (valen para todas las ubicaciones)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = {
            CONF_RADAR_HOURS: DEFAULT_RADAR_HOURS,
            CONF_RADAR_ZOOM: DEFAULT_RADAR_ZOOM,
            **self.config_entry.options,
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_RADAR_HOURS): SelectSelector(
                            SelectSelectorConfig(
                                options=list(RADAR_HOURS),
                                translation_key=CONF_RADAR_HOURS,
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Required(CONF_RADAR_ZOOM): SelectSelector(
                            SelectSelectorConfig(
                                options=list(RADAR_ZOOMS),
                                translation_key=CONF_RADAR_ZOOM,
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                    }
                ),
                options,
            ),
        )


class LocationSubentryFlow(ConfigSubentryFlow):
    """Añadir o reconfigurar una ubicación."""

    _candidate: _Candidate

    @property
    def _is_new(self) -> bool:
        return self.source == SOURCE_USER

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Paso 1: elegir el punto."""
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        errors: dict[str, str] = {}
        if user_input is not None:
            location = user_input[CONF_LOCATION]
            exclude = None if self._is_new else self._get_reconfigure_subentry()
            if _is_already_configured(
                self.hass,
                location[CONF_LATITUDE],
                location[CONF_LONGITUDE],
                exclude.subentry_id if exclude else None,
            ):
                return self.async_abort(reason="already_configured")
            candidate = await _async_candidate(
                self.hass, location[CONF_LATITUDE], location[CONF_LONGITUDE], errors
            )
            if candidate:
                self._candidate = candidate
                return await self.async_step_confirm()
        elif not self._is_new:
            subentry = self._get_reconfigure_subentry()
            user_input = {
                CONF_LOCATION: {
                    CONF_LATITUDE: subentry.data[CONF_LATITUDE],
                    CONF_LONGITUDE: subentry.data[CONF_LONGITUDE],
                }
            }

        return self.async_show_form(
            step_id="location",
            data_schema=self.add_suggested_values_to_schema(
                _location_schema(self.hass), user_input
            ),
            errors=errors,
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Paso 2: confirmar concello y estación."""
        candidate = self._candidate
        if user_input is not None:
            data = _location_data(candidate, user_input)
            title = candidate.toponyms[data[CONF_CONCELLO_ID]]
            if self._is_new:
                return self.async_create_entry(title=title, data=data)
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=title,
                data=data,
            )

        suggested = _suggested(candidate)
        if not self._is_new:
            previous = self._get_reconfigure_subentry().data
            same_concello = previous[CONF_CONCELLO_ID] == candidate.concello_id
            if same_concello:
                # Mismo concello que antes: se respeta lo elegido.
                if previous.get(CONF_STATION_ID):
                    suggested[CONF_STATION_ID] = str(previous[CONF_STATION_ID])
                suggested[CONF_STATION_WEATHER] = previous.get(
                    CONF_STATION_WEATHER, True
                )
                if previous.get(CONF_CAMERA_ID):
                    suggested[CONF_CAMERA_ID] = _camera_key(
                        candidate, previous[CONF_CAMERA_ID]
                    )
                else:
                    suggested.pop(CONF_CAMERA_ID, None)

        return self.async_show_form(
            step_id="confirm",
            data_schema=self.add_suggested_values_to_schema(
                _confirm_schema(self.hass, candidate), suggested
            ),
            description_placeholders=_confirm_placeholders(candidate),
        )

    async_step_user = async_step_location
    async_step_reconfigure = async_step_location


def _camera_key(candidate: _Candidate, camera_id: str | int) -> str:
    """Clave de la cámara guardada; antes se guardaba el identificador numérico."""
    if any(camera.key == camera_id for camera, _ in candidate.cameras):
        return str(camera_id)
    return next(
        (c.key for c, _ in candidate.cameras if str(c.id) == str(camera_id)),
        str(camera_id),
    )


def _suggested(candidate: _Candidate) -> dict[str, Any]:
    """Concello del punto, estación más cercana usada para el tiempo actual y, si
    esa estación tiene cámara (comparten identificador), su cámara."""
    suggested: dict[str, Any] = {
        CONF_CONCELLO_ID: str(candidate.concello_id),
        CONF_STATION_WEATHER: True,
    }
    if candidate.stations:
        station = candidate.stations[0][0]
        suggested[CONF_STATION_ID] = str(station.id)
        # La primera de la estación (la más cercana, si tiene dos).
        camera = next((c for c, _ in candidate.cameras if c.id == station.id), None)
        if camera:
            suggested[CONF_CAMERA_ID] = camera.key
    return suggested
