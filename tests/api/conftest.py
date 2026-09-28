"""MeteoGalicia simulado con respuestas reales guardadas (Santiago, 2026-09-26).

El entorno de tests de Home Assistant bloquea la red, así que las peticiones se
simulan con `aioclient_mock`.
"""

import asyncio
from collections.abc import AsyncIterator
import json
from pathlib import Path
import re
from typing import Any

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.meteogal.api import MeteoGalClient
from custom_components.meteogal.api.client import BASE_URL
from custom_components.meteogal.api.meteosix import BASE_URL as METEOSIX_URL

FIXTURES = Path(__file__).parent / "fixtures"

SANTIAGO = 15078
UNKNOWN = 99999

DAILY = f"{BASE_URL}/predicion/jsonPredConcellos.action"
HOURLY = f"{BASE_URL}/predicion/jsonPredHorariaConcellos.action"
MEDIUM_TERM = f"{BASE_URL}/predicion/jsonPredMedioPrazo.action"
CONCELLOS = f"{BASE_URL}/predicion/adversos/jsonConcellosNivelMax.action"
STATIONS = f"{BASE_URL}/observacion/listaEstacionsMeteo.action"
OBSERVATION = f"{BASE_URL}/observacion/observacionConcellos.action"
CAMERAS = f"{BASE_URL}/observacion/jsonCamaras.action"
STATION_NOW = f"{BASE_URL}/observacion/ultimos10minEstacionsMeteo.action"
STATION_DAY = f"{BASE_URL}/observacion/datosDiariosEstacionsMeteo.action"
WARNINGS = f"{BASE_URL}/predicion/adversos/jsonAvisosConcellos.action"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def mock_meteogalicia(
    aioclient_mock: AiohttpClientMocker, concello: int | None = None
) -> None:
    """Registra las respuestas guardadas.

    Sin `concello`: todos los endpoints, con Santiago y un concello inexistente.
    Con `concello`: los endpoints por concello de ese código, con datos de Santiago.
    """
    pairs = (
        [(concello, SANTIAGO)]
        if concello
        else [(SANTIAGO, SANTIAGO), (UNKNOWN, "unknown")]
    )
    for code, suffix in pairs:
        aioclient_mock.get(
            DAILY,
            params={"idConc": code},
            json=load(f"jsonPredConcellos_{suffix}.json"),
        )
        aioclient_mock.get(
            HOURLY,
            params={"idConc": code},
            json=load(f"jsonPredHorariaConcellos_{suffix}.json"),
        )
        aioclient_mock.get(
            MEDIUM_TERM,
            params={"idConc": code, "dia": -1},
            json=load(f"jsonPredMedioPrazo_{suffix}.json"),
        )
        aioclient_mock.get(
            WARNINGS,
            params={"idConcello": code, "dia": -1},
            json=load(f"jsonAvisosConcellos_{suffix}.json"),
        )
        aioclient_mock.get(
            OBSERVATION,
            params={"idConcello": code},
            json=(
                load("observacionConcellos_15078.json")
                if suffix == SANTIAGO
                else {"listaObservacionConcellos": []}
            ),
        )
    if concello:
        return
    aioclient_mock.get(
        CONCELLOS, params={"dia": 0}, json=load("jsonConcellosNivelMax.json")
    )
    aioclient_mock.get(STATIONS, json=load("listaEstacionsMeteo.json"))
    aioclient_mock.get(CAMERAS, json=load("jsonCamaras.json"))
    # Cualquier estación: lecturas reales de Coruña-Dique (2026-09-27, 21:40Z).
    aioclient_mock.get(
        re.compile(re.escape(STATION_NOW) + r"\?idEst="),
        json=load("ultimos10minEstacionsMeteo_14000.json"),
    )
    # Todas a la vez (2026-09-28, 15:30Z).
    aioclient_mock.get(STATION_NOW, json=load("ultimos10minEstacionsMeteo.json"))
    aioclient_mock.get(STATION_DAY, json=load("datosDiariosEstacionsMeteo_14000.json"))


@pytest.fixture
async def client(
    aioclient_mock: AiohttpClientMocker,
) -> AsyncIterator[MeteoGalClient]:
    mock_meteogalicia(aioclient_mock)
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield MeteoGalClient(session)
    await session.close()


METEOSIX_FORECAST = f"{METEOSIX_URL}/getNumericForecastInfo"
# Claves de prueba: válida, rechazada por MeteoSIX y sin conexión.
METEOSIX_KEY = "clave-valida"
METEOSIX_BAD_KEY = "clave-mala"
METEOSIX_DOWN_KEY = "clave-sin-conexion"


def mock_meteosix(aioclient_mock: AiohttpClientMocker) -> None:
    """MeteoSIX responde según la clave, con respuestas reales de un solo punto."""
    forecast = load("meteosix_forecast.json")
    forecast["features"] = forecast["features"][:1]
    aioclient_mock.get(
        METEOSIX_FORECAST, params={"API_KEY": METEOSIX_KEY}, json=forecast
    )
    aioclient_mock.get(
        METEOSIX_FORECAST,
        params={"API_KEY": METEOSIX_BAD_KEY},
        json=load("meteosix_invalid_key.json"),
    )
    aioclient_mock.get(
        METEOSIX_FORECAST,
        params={"API_KEY": METEOSIX_DOWN_KEY},
        exc=aiohttp.ClientConnectionError(),
    )


RADAR_FRAME = FIXTURES / "radar_frame_20260927T2005.png"


def mock_radar(
    aioclient_mock: AiohttpClientMocker,
    days: dict[str, list[str] | int],
) -> None:
    """THREDDS del radar: por día UTC (`AAAAMMDD`), su lista de pasadas
    (`"HH:MM:SS.000Z"`) o un código HTTP de error. Todas las pasadas devuelven la
    misma imagen real en grises (A Coruña, 2026-09-27 20:05Z)."""
    for day, steps in days.items():
        base = re.escape(f"PPI_{day}_10m.nc") + r"\?"
        if isinstance(steps, int):
            aioclient_mock.get(
                re.compile(base), status=steps, text="<html>Error</html>"
            )
            continue
        aioclient_mock.get(
            re.compile(base + r".*item=timesteps"), json={"timesteps": steps}
        )
        aioclient_mock.get(
            re.compile(base + r".*request=GetMap"),
            content=RADAR_FRAME.read_bytes(),
            headers={"Content-Type": "image/png"},
        )


def radar_steps(start: str, end: str) -> list[str]:
    """Pasadas cada 10 min entre dos horas UTC (`HH:MM`), ambas incluidas."""
    h, m = map(int, start.split(":"))
    last = tuple(map(int, end.split(":")))
    steps = []
    while (h, m) <= last:
        steps.append(f"{h:02d}:{m:02d}:00.000Z")
        m += 10
        h, m = h + m // 60, m % 60
    return steps
