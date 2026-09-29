"""Cliente del modelo de calidad del aire CHIMERE de MeteoGalicia (THREDDS), sin clave.

Una pasada al día (00 UTC) con el ICA y los contaminantes de cada hora, unas 76 horas,
en una malla de ~7 km sobre Galicia (`chimere_2d_gal`). Se consulta por punto con
NCSS, en CSV. De momento solo se usa el ICA: las concentraciones del modelo están
sin validar frente a las estaciones (docs/calidad-aire.md).
"""

from __future__ import annotations

import csv
from datetime import datetime
import io
import re
from typing import Final

import aiohttp

from .exceptions import MeteoGalConnectionError, MeteoGalResponseError
from .models import AirModelHour

BASE_URL: Final = "https://thredds.meteogalicia.gal/thredds"
CATALOG: Final = "catalog/chimere_2d_gal/fmrc/files/catalog.xml"
DEFAULT_TIMEOUT = 30

_FILE = re.compile(r'urlPath="(chimere_2d_gal/[^"]+\.nc)"')


class ChimereClient:
    """Última pasada publicada y el ICA de cada hora en un punto."""

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

        `…/chimere_surface_gal3_AAAAMMDD_00.nc`: los nombres llevan la fecha, el
        mayor es el más reciente.
        """
        catalog = await self._get(f"{self._base_url}/{CATALOG}", {})
        files = sorted(_FILE.findall(catalog))
        if not files:
            raise MeteoGalResponseError("CHIMERE: catálogo sin ficheros")
        return str(files[-1])

    async def get_point(
        self, run: str, latitude: float, longitude: float
    ) -> list[AirModelHour]:
        """ICA de todas las horas de la pasada en el punto de malla más cercano."""
        text = await self._get(
            f"{self._base_url}/ncss/grid/{run}",
            {
                "var": "ica",
                "latitude": f"{latitude:.4f}",
                "longitude": f"{longitude:.4f}",
                "temporal": "all",
                "accept": "csv",
            },
        )
        try:
            return _parse_point(text)
        except (IndexError, ValueError) as err:
            raise MeteoGalResponseError(
                f"CHIMERE: formato inesperado: {err!r}"
            ) from err

    async def _get(self, url: str, params: dict[str, str]) -> str:
        try:
            async with self._session.get(
                url, params=params, timeout=self._timeout
            ) as response:
                if response.status != 200:
                    raise MeteoGalResponseError(
                        f"CHIMERE: respuesta HTTP {response.status}"
                    )
                return await response.text()
        except (TimeoutError, aiohttp.ClientConnectionError) as err:
            raise MeteoGalConnectionError(f"CHIMERE: {err!r}") from err
        except aiohttp.ClientError as err:
            raise MeteoGalResponseError(f"CHIMERE: {err!r}") from err


def _parse_point(text: str) -> list[AirModelHour]:
    """CSV de NCSS: `time,station,latitude,longitude,ica`, una fila por hora."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0][0] != "time":
        raise ValueError("sin cabecera")
    hours = []
    for row in rows[1:]:
        if not row:
            continue
        value = row[4]
        index = None if value in ("", "NaN") else float(value)
        hours.append(
            AirModelHour(
                time=datetime.fromisoformat(row[0]),
                index=None if index is None or index < 0 else index,
            )
        )
    return hours
