"""Cliente asíncrono de los servicios públicos de MeteoGalicia (sin clave)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
import logging
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from .exceptions import (
    MeteoGalConnectionError,
    MeteoGalNotFoundError,
    MeteoGalResponseError,
)
from .models import (
    Camera,
    Concello,
    ConcelloObservation,
    DailyForecast,
    DayParts,
    HourlyForecast,
    MediumTermForecast,
    SkyProbability,
    Station,
    StationDay,
    StationReading,
    WeatherWarning,
)

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://servizos.meteogalicia.gal/mgrss"
DEFAULT_TIMEOUT = 30

# MeteoGalicia da las fechas en hora local de Galicia, sin zona.
TIMEZONE = ZoneInfo("Europe/Madrid")

# Valor que usa MeteoGalicia para "dato no disponible".
MISSING = -9999

# Códigos de validación de las medidas de estación que se aceptan: 0 sin validar
# (lo más reciente), 1 válido y 5 válido interpolado. Se descartan 2 sospechoso,
# 3 erróneo y 9 no registrado.
VALID_CODES = frozenset({0, 1, 5})


class MeteoGalClient:
    """Cliente de los endpoints públicos de MeteoGalicia.

    Recibe la sesión de aiohttp desde fuera (en Home Assistant, la compartida).
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def get_concellos(self) -> list[Concello]:
        """Los 313 concellos de Galicia (`jsonConcellosNivelMax`)."""
        data = await self._get("predicion/adversos/jsonConcellosNivelMax.action", dia=0)
        return _parse(data, _parse_concellos)

    async def get_stations(self) -> list[Station]:
        """Estaciones meteorológicas con coordenadas (`listaEstacionsMeteo`)."""
        data = await self._get("observacion/listaEstacionsMeteo.action")
        return _parse(data, _parse_stations)

    async def get_daily_forecast(self, concello_id: int) -> list[DailyForecast]:
        """Previsión diaria a corto plazo, desde hoy (`jsonPredConcellos`)."""
        data = await self._get("predicion/jsonPredConcellos.action", idConc=concello_id)
        if isinstance(data, Mapping) and data.get("predConcello", ...) is None:
            raise MeteoGalNotFoundError(f"Concello desconocido: {concello_id}")
        return _parse(data, _parse_daily)

    async def get_hourly_forecast(self, concello_id: int) -> list[HourlyForecast]:
        """Previsión por horas desde las 00:00 de hoy (`jsonPredHorariaConcellos`)."""
        data = await self._get(
            "predicion/jsonPredHorariaConcellos.action", idConc=concello_id
        )
        _check_known(data, "predHoraria", concello_id)
        return _parse(data, _parse_hourly)

    async def get_medium_term_forecast(
        self, concello_id: int
    ) -> list[MediumTermForecast]:
        """Previsión a medio plazo, tras el corto plazo (`jsonPredMedioPrazo`)."""
        data = await self._get(
            "predicion/jsonPredMedioPrazo.action", idConc=concello_id, dia=-1
        )
        _check_known(data, "predMPrazo", concello_id)
        return _parse(data, _parse_medium_term)

    async def get_concello_observation(
        self, concello_id: int
    ) -> ConcelloObservation | None:
        """Estado actual del concello (`observacionConcellos`), o None si no hay."""
        data = await self._get(
            "observacion/observacionConcellos.action", idConcello=concello_id
        )
        return _parse(data, _parse_observation)

    async def get_warnings(self, concello_id: int) -> list[WeatherWarning]:
        """Avisos del concello para hoy, mañana y pasado (`jsonAvisosConcellos`).

        Con un concello inexistente responde igual que sin avisos: lista vacía.
        """
        data = await self._get(
            "predicion/adversos/jsonAvisosConcellos.action",
            idConcello=concello_id,
            dia=-1,
        )
        return _parse(data, _parse_warnings)

    async def get_station_reading(self, station_id: int) -> StationReading | None:
        """Última lectura de 10 minutos de la estación, o None si no hay."""
        data = await self._get(
            "observacion/ultimos10minEstacionsMeteo.action", idEst=station_id
        )
        return _parse(data, _parse_station_reading)

    async def get_station_day(self, station_id: int) -> StationDay | None:
        """Datos de hoy de la estación hasta ahora, o None si aún no hay."""
        data = await self._get(
            "observacion/datosDiariosEstacionsMeteo.action", idEst=station_id
        )
        return _parse(data, _parse_station_day)

    async def get_cameras(self) -> list[Camera]:
        """Las cámaras de MeteoGalicia con su última imagen (`jsonCamaras`)."""
        data = await self._get("observacion/jsonCamaras.action")
        return _parse(data, _parse_cameras)

    async def _get(self, path: str, **params: Any) -> Any:
        url = f"{self._base_url}/{path}"
        try:
            async with self._session.get(
                url, params=params, timeout=self._timeout
            ) as response:
                if response.status != 200:
                    raise MeteoGalResponseError(
                        f"{path}: respuesta HTTP {response.status}"
                    )
                return await response.json()
        except (TimeoutError, aiohttp.ClientConnectionError) as err:
            raise MeteoGalConnectionError(f"{path}: {err!r}") from err
        except (aiohttp.ClientError, ValueError) as err:
            raise MeteoGalResponseError(f"{path}: {err!r}") from err


def _parse[T](data: Any, parser: Callable[[Any], T]) -> T:
    """Convierte cualquier sorpresa en el formato en un error del cliente."""
    try:
        return parser(data)
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise MeteoGalResponseError(f"Formato inesperado: {err!r}") from err


def _check_known(data: Any, key: str, concello_id: int) -> None:
    # Con un concello inexistente responden 200 con idConcello 0 y la lista vacía.
    if (
        isinstance(data, Mapping)
        and isinstance(data.get(key), Mapping)
        and data[key].get("idConcello") == 0
    ):
        raise MeteoGalNotFoundError(f"Concello desconocido: {concello_id}")


def _value(raw: Any) -> int | None:
    if raw is None or raw == MISSING:
        return None
    return int(raw)


def _float(raw: Any) -> float | None:
    if raw is None or raw == MISSING:
        return None
    return float(raw)


def _parts(raw: Mapping[str, Any]) -> DayParts[int | None]:
    return DayParts(
        morning=_value(raw["manha"]),
        afternoon=_value(raw["tarde"]),
        night=_value(raw["noite"]),
    )


def _local_datetime(raw: str) -> datetime:
    return datetime.fromisoformat(raw).replace(tzinfo=TIMEZONE)


def _local_date(raw: str) -> date:
    return datetime.fromisoformat(raw).date()


def _parse_concellos(data: Any) -> list[Concello]:
    days = data["listaDiaConcellos"]
    if not days:
        return []
    return [
        Concello(id=int(item["idConcello"]), name=item["nomeConcello"])
        for item in days[0]["listaNiveisMaximos"]
    ]


def _parse_stations(data: Any) -> list[Station]:
    return [
        Station(
            id=int(item["idEstacion"]),
            name=item["estacion"],
            concello=item["concello"],
            province=item["provincia"],
            latitude=float(item["lat"]),
            longitude=float(item["lon"]),
            altitude=_float(item.get("altitude")),
        )
        for item in data["listaEstacionsMeteo"]
    ]


def _parse_daily(data: Any) -> list[DailyForecast]:
    return [
        DailyForecast(
            date=_local_date(day["dataPredicion"]),
            sky=_value(day["ceoDia"]),
            sky_parts=_parts(day["ceo"]),
            precipitation_probability=_parts(day["pchoiva"]),
            wind=_parts(day["vento"]),
            temperature_max=_value(day["tMax"]),
            temperature_min=_value(day["tMin"]),
            temperature_max_parts=_parts(day["tmaxFranxa"]),
            temperature_min_parts=_parts(day["tminFranxa"]),
            uv_max=_value(day.get("uvMax")),
            alert_level=_value(day.get("nivelAviso")),
        )
        for day in data["predConcello"]["listaPredDiaConcello"]
    ]


def _parse_hourly(data: Any) -> list[HourlyForecast]:
    return [
        HourlyForecast(
            time=_local_datetime(hour["dataPredicion"]),
            sky=_value(hour["icoCeo"]),
            wind=_value(hour["icoVento"]),
            temperature=_value(hour["tMedia"]),
        )
        for day in data["predHoraria"]["listaPredDiaHoraria"]
        for hour in day["listaPredHora"]
    ]


def _parse_medium_term(data: Any) -> list[MediumTermForecast]:
    result = []
    for day in data["predMPrazo"]["listaPredDiaMPrazo"]:
        skies = tuple(
            SkyProbability(sky=sky, probability=_value(day.get(f"probIcoCeo{n}")))
            for n in (1, 2, 3)
            if (sky := _value(day.get(f"icoCeo{n}"))) is not None
        )
        result.append(
            MediumTermForecast(
                date=_local_date(day["dataPredicion"]),
                day=int(day["dia"]),
                sky=skies,
                wind=_value(day["icoVento"]),
                temperature_max=_value(day["tMax"]),
                temperature_max_low=_value(day["tMaxLI"]),
                temperature_max_high=_value(day["tMaxLS"]),
                temperature_min=_value(day["tMin"]),
                temperature_min_low=_value(day["tMinLI"]),
                temperature_min_high=_value(day["tMinLS"]),
            )
        )
    return result


def _parse_observation(data: Any) -> ConcelloObservation | None:
    items = data["listaObservacionConcellos"]
    if not items:
        return None
    item = items[0]
    return ConcelloObservation(
        concello_id=int(item["idConcello"]),
        time=_local_datetime(item["dataLocal"]),
        sky=_value(item["icoEstadoCeo"]),
        wind=_value(item["icoVento"]),
        temperature=_float(item["temperatura"]),
        apparent_temperature=_float(item.get("sensacionTermica")),
    )


def _parse_warnings(data: Any) -> list[WeatherWarning]:
    # Por si un aviso que cruza la medianoche aparece en dos días: uno por id.
    warnings: dict[int, WeatherWarning] = {}
    for day in data["listaDiaConcellos"]:
        for item in day["listaAvisosConcellos"]:
            level = _value(item["idNivel"])
            if not level:  # 0: normalidad
                continue
            warning = WeatherWarning(
                id=int(item["id"]),
                type_id=int(item["idTipoAlerta"]),
                level=level,
                start=_local_datetime(item["dataIni"]),
                end=_local_datetime(item["dataFin"]),
            )
            warnings.setdefault(warning.id, warning)
    return list(warnings.values())


def _measures(items: list[dict[str, Any]]) -> dict[str, float]:
    return {
        item["codigoParametro"]: float(item["valor"])
        for item in items
        if item.get("lnCodigoValidacion") in VALID_CODES
        and item.get("valor") is not None
        and item["valor"] != MISSING
    }


def _parse_station_reading(data: Any) -> StationReading | None:
    items = data["listUltimos10min"]
    if not items:
        return None
    item = items[0]
    return StationReading(
        station_id=int(item["idEstacion"]),
        # En UTC, aunque sin zona.
        time=datetime.fromisoformat(item["instanteLecturaUTC"]).replace(tzinfo=UTC),
        values=_measures(item["listaMedidas"]),
    )


def _parse_station_day(data: Any) -> StationDay | None:
    days = data["listDatosDiarios"]
    if not days or not days[0]["listaEstacions"]:
        return None
    station = days[0]["listaEstacions"][0]
    return StationDay(
        station_id=int(station["idEstacion"]),
        date=_local_date(days[0]["data"]),
        values=_measures(station["listaMedidas"]),
    )


def _parse_cameras(data: Any) -> list[Camera]:
    return [
        Camera(
            key=item["imaxeCamara"].rstrip("/").split("/")[-2],
            id=int(item["identificador"]),
            name=item["nomeCamara"],
            concello_id=int(item["idConcello"]),
            latitude=float(item["lat"]),
            longitude=float(item["lon"]),
            image_url=item["imaxeCamara"],
            time=_local_datetime(item["dataUltimaAct"]),
        )
        for item in data["listaCamaras"]
    ]
