"""Cliente del radar de MeteoGalicia (THREDDS, WMS), sin clave.

Un fichero por día UTC con una pasada cada 10 minutos (00:05Z, 00:15Z…). El WMS
devuelve cada pasada ya reproyectada, en escala de grises: el gris codifica la
reflectividad entre `DBZ_MIN` y `DBZ_MAX` (lineal), y lo que queda por debajo sale
transparente. Los colores los pone la integración. Detalle en docs/radar.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
import logging
from typing import Any, Final

import aiohttp

from .exceptions import MeteoGalConnectionError, MeteoGalResponseError

_LOGGER = logging.getLogger(__name__)

BASE_URL: Final = "https://thredds.meteogalicia.gal/thredds/wms/observacion/RADAR/PPI"
LAYER: Final = "equivalent_reflectivity_factor"
DEFAULT_TIMEOUT = 30

# Rango de reflectividad que codifica el gris: 0 = DBZ_MIN, 255 = DBZ_MAX.
# Comprobado con el valor exacto del servidor: 26,25 dBZ → gris 68 → 26,0 dBZ.
DBZ_MIN: Final = 10.0
DBZ_MAX: Final = 70.0


@dataclass(frozen=True, slots=True)
class BBox:
    """Recuadro en grados: sur, oeste, norte, este."""

    south: float
    west: float
    north: float
    east: float


class RadarClient:
    """Lista de pasadas publicadas e imagen de cada pasada."""

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

    async def get_times(self, day: date) -> list[datetime]:
        """Pasadas publicadas de un día UTC, de la más antigua a la más nueva.

        Si el fichero del día aún no existe (justo después de medianoche UTC), el
        servidor responde 500: lanza MeteoGalResponseError.
        """
        data = await self._get(
            day,
            "json",
            request="GetMetadata",
            item="timesteps",
            layerName=LAYER,
            day=day.isoformat(),
        )
        try:
            return [
                datetime.combine(day, time.fromisoformat(step.rstrip("Z")), UTC)
                for step in data["timesteps"]
            ]
        except (KeyError, TypeError, ValueError) as err:
            raise MeteoGalResponseError(f"Pasadas del radar: {err!r}") from err

    async def get_frame(
        self, when: datetime, bbox: BBox, width: int, height: int
    ) -> bytes:
        """PNG en grises y con transparencia de una pasada, para el recuadro."""
        when = when.astimezone(UTC)
        return await self._get(
            when.date(),
            "png",
            service="WMS",
            version="1.3.0",
            request="GetMap",
            layers=LAYER,
            styles="default-scalar/seq-GreysRev",
            crs="EPSG:4326",
            # En WMS 1.3.0 con EPSG:4326 el orden es latitud, longitud.
            bbox=f"{bbox.south},{bbox.west},{bbox.north},{bbox.east}",
            width=width,
            height=height,
            format="image/png",
            transparent="true",
            time=when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            colorscalerange=f"{DBZ_MIN:g},{DBZ_MAX:g}",
            numcolorbands=250,
            belowmincolor="transparent",
            abovemaxcolor="extend",
        )

    async def _get(self, file_day: date, kind: str, **params: Any) -> Any:
        url = f"{self._base_url}/PPI_{file_day:%Y%m%d}_10m.nc"
        name = f"radar {file_day:%Y-%m-%d}"
        try:
            async with self._session.get(
                url, params=params, timeout=self._timeout
            ) as response:
                if response.status != 200:
                    raise MeteoGalResponseError(
                        f"{name}: respuesta HTTP {response.status}"
                    )
                if kind == "json":
                    return await response.json(content_type=None)
                content_type = response.headers.get("Content-Type", "")
                if not content_type.startswith("image/png"):
                    raise MeteoGalResponseError(f"{name}: no es PNG ({content_type})")
                return await response.read()
        except (TimeoutError, aiohttp.ClientConnectionError) as err:
            raise MeteoGalConnectionError(f"{name}: {err!r}") from err
        except (aiohttp.ClientError, ValueError) as err:
            raise MeteoGalResponseError(f"{name}: {err!r}") from err
