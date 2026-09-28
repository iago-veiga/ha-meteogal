"""Cliente asíncrono de MeteoSIX v5 (predicción numérica de MeteoGalicia, con clave)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
import logging
from typing import Any, Final

import aiohttp

from .client import TIMEZONE, _parse
from .exceptions import (
    MeteoGalConnectionError,
    MeteoGalResponseError,
    MeteoSixAuthError,
    MeteoSixError,
)
from .models import MeteoSixHour

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://servizos.meteogalicia.gal/apiv5"
DEFAULT_TIMEOUT = 30

# Límite de la API: más puntos en una petición devuelve la excepción 202.
MAX_POINTS: Final = 20

# Punto con datos seguro para comprobar la clave (Santiago de Compostela).
CHECK_POINT: Final = (42.8782, -8.5448)

AUTH_ERRORS: Final = frozenset({"005", "006"})
# Sin datos para ese punto o ese intervalo: no es un fallo del servicio.
NO_DATA_ERRORS: Final = frozenset({"216", "217"})

# Variable de MeteoSIX → campo de MeteoSixHour. El viento se trata aparte.
_FIELDS: Final = {
    "sky_state": "sky",
    "temperature": "temperature",
    "precipitation_amount": "precipitation",
    "relative_humidity": "humidity",
    "cloud_area_fraction": "cloud_coverage",
    "air_pressure_at_sea_level": "pressure",
    "snow_level": "snow_level",
}
WIND: Final = "wind"

DEFAULT_VARIABLES: Final = (*_FIELDS, WIND)


class MeteoSixClient:
    """Cliente de `getNumericForecastInfo`.

    Las coordenadas se reciben como (latitud, longitud), igual que en Home
    Assistant; MeteoSIX las quiere al revés y eso queda dentro del cliente.
    La clave nunca aparece en los mensajes de error ni en el registro.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def get_forecast(
        self,
        points: Sequence[tuple[float, float]],
        variables: Sequence[str] = DEFAULT_VARIABLES,
        *,
        end: datetime | None = None,
    ) -> list[list[MeteoSixHour] | None]:
        """Previsión por horas desde la hora actual para cada punto, en su orden.

        Un punto sin datos (fuera de los límites o sin datos en el intervalo) da
        None en su posición; el resto de puntos se devuelven igual.
        """
        if not points or len(points) > MAX_POINTS:
            raise ValueError(f"Hacen falta entre 1 y {MAX_POINTS} puntos")
        params = {
            "coords": ";".join(f"{lon:.4f},{lat:.4f}" for lat, lon in points),
            "variables": ",".join(variables),
        }
        if end is not None:
            params["endTime"] = end.astimezone(TIMEZONE).strftime("%Y-%m-%dT%H:%M:%S")
        data = await self._get("getNumericForecastInfo", **params)
        if (error := _exception(data)) is not None:
            if error.code in NO_DATA_ERRORS:
                return [None] * len(points)
            raise error
        result = _parse(data, _parse_forecast)
        if len(result) != len(points):
            raise MeteoGalResponseError(
                f"MeteoSIX devolvió {len(result)} puntos de {len(points)}"
            )
        return result

    async def check_key(self) -> None:
        """Comprueba la clave con una petición mínima (una variable, una hora).

        Lanza MeteoSixAuthError si no es válida.
        """
        # Un endTime anterior al momento de la petición da la excepción 318.
        await self.get_forecast(
            [CHECK_POINT],
            ["temperature"],
            end=datetime.now(TIMEZONE) + timedelta(hours=1),
        )

    async def _get(self, path: str, **params: Any) -> Any:
        url = f"{self._base_url}/{path}"
        # Los errores de aiohttp llevan la URL con la clave: solo se guarda el tipo.
        try:
            async with self._session.get(
                url, params={**params, "API_KEY": self._api_key}, timeout=self._timeout
            ) as response:
                if response.status != 200:
                    raise MeteoGalResponseError(
                        f"{path}: respuesta HTTP {response.status}"
                    )
                return await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientConnectionError) as err:
            raise MeteoGalConnectionError(f"{path}: {type(err).__name__}") from None
        except (aiohttp.ClientError, ValueError) as err:
            raise MeteoGalResponseError(f"{path}: {type(err).__name__}") from None


def _exception(data: Any) -> MeteoSixError | None:
    """La excepción que viene en el cuerpo, ya con su clase, o None."""
    if not isinstance(data, Mapping) or not isinstance(
        exc := data.get("exception"), Mapping
    ):
        return None
    code = str(exc.get("code"))
    message = str(exc.get("message"))
    if code in AUTH_ERRORS:
        return MeteoSixAuthError(code, message)
    return MeteoSixError(code, message)


def _parse_forecast(data: Any) -> list[list[MeteoSixHour] | None]:
    result: list[list[MeteoSixHour] | None] = []
    for feature in data["features"]:
        if (error := _exception(feature)) is not None:
            if error.code in NO_DATA_ERRORS:
                result.append(None)
                continue
            raise error
        result.append(_parse_hours(feature["properties"]["days"] or ()))
    return result


def _parse_hours(days: Sequence[Mapping[str, Any]]) -> list[MeteoSixHour]:
    hours: dict[datetime, dict[str, Any]] = {}
    for day in days:
        # Entre las 23:00 y las 00:00, el trozo de hoy (de ahora a las 23:59) no
        # tiene ninguna hora en punto y llega con `variables: null`.
        for variable in day["variables"] or ():
            name = variable["name"]
            if name != WIND and name not in _FIELDS:
                continue
            for item in variable.get("values") or ():
                fields = hours.setdefault(
                    datetime.fromisoformat(item["timeInstant"]), {"model_run": None}
                )
                if fields["model_run"] is None and item.get("modelRun"):
                    fields["model_run"] = datetime.fromisoformat(item["modelRun"])
                if name == WIND:
                    fields["wind_speed"] = _number(item.get("moduleValue"))
                    fields["wind_bearing"] = _number(item.get("directionValue"))
                elif name == "sky_state":
                    fields["sky"] = item.get("value")
                    # Solo el icono dice si es de día o de noche (.../night/...).
                    if icon := item.get("iconURL"):
                        fields["night"] = "/night/" in icon
                else:
                    fields[_FIELDS[name]] = _number(item.get("value"))
    return [MeteoSixHour(time=time, **hours[time]) for time in sorted(hours)]


def _number(raw: Any) -> float | None:
    return None if raw is None else float(raw)
