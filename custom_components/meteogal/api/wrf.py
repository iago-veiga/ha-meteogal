"""Cliente del modelo WRF de 4 km de MeteoGalicia (THREDDS), sin clave.

El WRF determinista de MeteoGalicia (`wrf_2d_04km`): de hora en hora, unas 84 horas,
dos pasadas al día (00 y 12 UTC). Se consulta por punto con NCSS, en CSV, como el
CHIMERE. Es el mismo sistema que MeteoSIX (que lo da en malla de 1 km y con clave);
de aquí salen la racha, que MeteoSIX no da, y el respaldo de viento, humedad y presión
cuando no hay MeteoSIX (docs/wrf.md).

Unidades de entrada: viento y racha en m/s, humedad como fracción y presión en Pa.
"""

from __future__ import annotations

import csv
from datetime import datetime
import io
import re
from typing import Final

import aiohttp

from .exceptions import MeteoGalConnectionError, MeteoGalResponseError
from .models import WrfHour

BASE_URL: Final = "https://thredds.meteogalicia.gal/thredds"
CATALOG: Final = "catalog/wrf_2d_04km/fmrc/files/catalog.xml"
VARIABLES: Final = "wind_gust,mod,dir,rh,mslp"
DEFAULT_TIMEOUT = 30

MS_TO_KMH: Final = 3.6

_FILE = re.compile(
    r'urlPath="(wrf_2d_04km/fmrc/files/\d{8}/wrf_arw_det_history_d03_\d{8}_\d{4}\.nc4)"'
)


class WrfClient:
    """Última pasada publicada y la previsión de cada hora en un punto."""

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

    async def get_latest_run(self) -> str:
        """Ruta del fichero de la última pasada.

        `…/AAAAMMDD/wrf_arw_det_history_d03_AAAAMMDD_HH00.nc4`: la ruta lleva la fecha
        y la hora, la mayor es la más reciente.
        """
        catalog = await self._get(f"{self._base_url}/{CATALOG}", {})
        files = sorted(_FILE.findall(catalog))
        if not files:
            raise MeteoGalResponseError("WRF: catálogo sin ficheros")
        return str(files[-1])

    async def get_point(
        self, run: str, latitude: float, longitude: float
    ) -> list[WrfHour]:
        """Todas las horas de la pasada en el punto de malla más cercano."""
        text = await self._get(
            f"{self._base_url}/ncss/grid/{run}",
            {
                "var": VARIABLES,
                "latitude": f"{latitude:.4f}",
                "longitude": f"{longitude:.4f}",
                "temporal": "all",
                "accept": "csv",
            },
        )
        try:
            return _parse_point(text)
        except (IndexError, KeyError, ValueError) as err:
            raise MeteoGalResponseError(f"WRF: formato inesperado: {err!r}") from err

    async def _get(self, url: str, params: dict[str, str]) -> str:
        try:
            async with self._session.get(
                url, params=params, timeout=self._timeout
            ) as response:
                if response.status != 200:
                    raise MeteoGalResponseError(
                        f"WRF: respuesta HTTP {response.status}"
                    )
                return await response.text()
        except (TimeoutError, aiohttp.ClientConnectionError) as err:
            raise MeteoGalConnectionError(f"WRF: {err!r}") from err
        except aiohttp.ClientError as err:
            raise MeteoGalResponseError(f"WRF: {err!r}") from err


def _number(row: dict[str, str], name: str, scale: float = 1.0) -> float | None:
    value = row.get(name, "")
    return None if value in ("", "NaN") else round(float(value) * scale, 1)


def _parse_point(text: str) -> list[WrfHour]:
    """CSV de NCSS: `time,station,latitude,longitude` y una columna por variable (con
    su unidad entre corchetes), una fila por hora."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0][0] != "time":
        raise ValueError("sin cabecera")
    names = [column.split("[")[0] for column in rows[0]]
    hours = []
    for values in rows[1:]:
        if not values:
            continue
        row = dict(zip(names, values, strict=False))
        pressure = _number(row, "mslp", 0.01)
        humidity = _number(row, "rh", 100.0)
        hours.append(
            WrfHour(
                time=datetime.fromisoformat(row["time"]),
                gust=_number(row, "wind_gust", MS_TO_KMH),
                wind_speed=_number(row, "mod", MS_TO_KMH),
                wind_bearing=_number(row, "dir"),
                humidity=None if humidity is None else min(humidity, 100.0),
                pressure=pressure,
            )
        )
    return hours
