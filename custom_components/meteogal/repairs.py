"""Reparaciones: la estación de una ubicación ha dejado de enviar datos.

Pasa de verdad: el 2026-09-28, Marroxo llevaba sin enviar desde el 19 y Serra do
Faro desde el 23. Tras un día sin lecturas se avisa en Ajustes → Reparaciones y el
aviso deja elegir otra estación (o ninguna) sin reconfigurar la ubicación entera.
Lo mismo con la estación de calidad del aire, con su propio aviso.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api import AirStationIndex, StationReading
from .config_flow import (
    Candidate,
    air_station_options,
    async_candidate,
    station_options,
)
from .const import CONF_AIR_STATION_ID, CONF_STATION_ID, DOMAIN
from .station import NO_DATA

if TYPE_CHECKING:
    from . import MeteoGalConfigEntry

# Una estación puede pasar horas sin enviar (mantenimiento); un día ya es avería.
STALE_AFTER: Final = timedelta(days=1)

ISSUE_PREFIX: Final = "station_stale_"
AIR_ISSUE_PREFIX: Final = "air_station_stale_"
ISSUE_PREFIXES: Final = (ISSUE_PREFIX, AIR_ISSUE_PREFIX)


def _issue_id(subentry_id: str) -> str:
    return f"{ISSUE_PREFIX}{subentry_id}"


def _air_issue_id(subentry_id: str) -> str:
    return f"{AIR_ISSUE_PREFIX}{subentry_id}"


@callback
def async_check_station(
    hass: HomeAssistant,
    entry: MeteoGalConfigEntry,
    subentry: ConfigSubentry,
    station_name: str,
    reading: StationReading | None,
    now: datetime,
) -> None:
    """Abre o cierra el aviso según la última lectura de la estación.

    Sin lectura (la estación no devuelve nada) no se avisa: no se sabe desde
    cuándo, y el sensor de diagnóstico ya queda «Desconocido».
    """
    issue_id = _issue_id(subentry.subentry_id)
    if reading is None or now - reading.time <= STALE_AFTER:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="station_stale",
        translation_placeholders=_placeholders(subentry, station_name, reading),
        data={"entry_id": entry.entry_id, "subentry_id": subentry.subentry_id},
    )


@callback
def async_check_air_station(
    hass: HomeAssistant,
    entry: MeteoGalConfigEntry,
    subentry: ConfigSubentry,
    station_name: str,
    index: AirStationIndex | None,
    now: datetime,
) -> None:
    """Como `async_check_station`, con la hora del último ICA de la estación de aire.

    Sin ICA (la estación no aparece en la lista) no se avisa.
    """
    issue_id = _air_issue_id(subentry.subentry_id)
    if index is None or now - index.time <= STALE_AFTER:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="air_station_stale",
        translation_placeholders=_placeholders(subentry, station_name, index),
        data={"entry_id": entry.entry_id, "subentry_id": subentry.subentry_id},
    )


def _placeholders(
    subentry: ConfigSubentry, station_name: str, last: StationReading | AirStationIndex
) -> dict[str, str]:
    return {
        "location": subentry.title,
        "station": station_name,
        "since": dt_util.as_local(last.time).strftime("%Y-%m-%d %H:%M"),
    }


@callback
def async_clean_issues(hass: HomeAssistant, entry: MeteoGalConfigEntry) -> None:
    """Quita los avisos de ubicaciones que ya no existen o ya no tienen estación."""
    registry = ir.async_get(hass)
    for domain, issue_id in list(registry.issues):
        prefix = next((p for p in ISSUE_PREFIXES if issue_id.startswith(p)), None)
        if domain != DOMAIN or prefix is None:
            continue
        issue = registry.issues[domain, issue_id]
        if issue.data and issue.data.get("entry_id") != entry.entry_id:
            continue
        subentry = entry.subentries.get(issue_id.removeprefix(prefix))
        key = CONF_AIR_STATION_ID if prefix == AIR_ISSUE_PREFIX else CONF_STATION_ID
        if subentry is None or not subentry.data.get(key):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


class StationRepairFlow(RepairsFlow):
    """Elegir otra estación para la ubicación, o ninguna. Meteorológica o de aire."""

    def __init__(self, entry_id: str, subentry_id: str, *, air: bool = False) -> None:
        self._entry_id = entry_id
        self._subentry_id = subentry_id
        self._air = air
        self._key = CONF_AIR_STATION_ID if air else CONF_STATION_ID
        self._issue_id = (_air_issue_id if air else _issue_id)(subentry_id)
        self._candidate: Candidate | None = None

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        subentry = entry.subentries.get(self._subentry_id) if entry else None
        if entry is None or subentry is None:
            return self.async_abort(reason="location_removed")

        # Sin lista (MeteoGalicia no respondió), enviar el formulario es reintentar.
        if user_input is not None and self._candidate is not None:
            station = user_input.get(self._key)
            self.hass.config_entries.async_update_subentry(
                entry,
                subentry,
                data={**subentry.data, self._key: int(station) if station else None},
            )
            return self.async_create_entry(data={})

        errors: dict[str, str] = {}
        if self._candidate is None:
            self._candidate = await async_candidate(
                self.hass,
                subentry.data[CONF_LATITUDE],
                subentry.data[CONF_LONGITUDE],
                errors,
            )
        candidate = self._candidate
        issue = ir.async_get(self.hass).async_get_issue(DOMAIN, self._issue_id)
        placeholders = dict(issue.translation_placeholders or {}) if issue else {}
        placeholders.setdefault("location", subentry.title)
        placeholders.setdefault("station", str(subentry.data.get(self._key)))
        placeholders.setdefault("since", "?")
        if candidate is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors=errors,
                description_placeholders=placeholders,
            )

        return self.async_show_form(
            step_id="confirm",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(self._key): SelectSelector(
                            SelectSelectorConfig(
                                options=(
                                    air_station_options(self.hass, candidate)
                                    if self._air
                                    else station_options(self.hass, candidate)
                                ),
                                mode=SelectSelectorMode.DROPDOWN,
                                sort=False,
                            )
                        )
                    }
                ),
                (_suggested_air if self._air else _suggested)(
                    candidate, subentry.data.get(self._key)
                ),
            ),
            description_placeholders=placeholders,
        )


def _suggested(candidate: Candidate, current: int | None) -> dict[str, str]:
    """La más cercana que envía datos, sin contar la actual."""
    station = next(
        (
            station
            for station, _, _ in candidate.stations
            if station.id != current
            and NO_DATA not in candidate.gaps.get(station.id, frozenset())
        ),
        None,
    )
    return {CONF_STATION_ID: str(station.id)} if station else {}


def _suggested_air(candidate: Candidate, current: int | None) -> dict[str, str]:
    """La estación de aire más cercana con dato ahora, sin contar la actual."""
    station = next(
        (
            station
            for station, _, has_data in candidate.air_stations
            if station.id != current and has_data
        ),
        None,
    )
    return {CONF_AIR_STATION_ID: str(station.id)} if station else {}


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Flujo de reparación de un aviso de MeteoGal."""
    assert data is not None
    return StationRepairFlow(
        data["entry_id"],
        data["subentry_id"],
        air=issue_id.startswith(AIR_ISSUE_PREFIX),
    )
