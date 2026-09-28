"""Guarda respuestas reales de MeteoSIX para los tests del cliente.

- `meteosix_forecast.json`: Santiago, la costa de A Coruña y un punto en Estados
  Unidos (sin datos), con todas las variables que usa MeteoGal.
- `meteosix_out_of_bounds.json`: solo el punto de Estados Unidos (excepción global).

Ojo: el modelo de 36 km cubre buena parte del Atlántico (p. ej. -30,40 tiene datos).

La clave se lee de la variable de entorno METEOSIX_API_KEY y no se guarda.

Uso: METEOSIX_API_KEY=... python scripts/capture_meteosix.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

BASE_URL = "https://servizos.meteogalicia.gal/apiv5/getNumericForecastInfo"
FIXTURES = Path(__file__).parent.parent / "tests" / "api" / "fixtures"

VARIABLES = (
    "sky_state,temperature,precipitation_amount,relative_humidity,"
    "cloud_area_fraction,air_pressure_at_sea_level,snow_level,wind"
)
# Longitud,latitud, como las quiere MeteoSIX.
SANTIAGO = "-8.5448,42.8782"
CORUNA_COAST = "-8.4000,43.3700"
OUTSIDE = "-80.0000,40.0000"


def fetch(key: str, coords: str) -> dict:
    query = urllib.parse.urlencode(
        {"coords": coords, "variables": VARIABLES, "API_KEY": key}
    )
    with urllib.request.urlopen(f"{BASE_URL}?{query}", timeout=60) as response:
        body = response.read().decode("utf-8")
    if key in body:
        sys.exit("La respuesta contiene la clave: no se guarda nada")
    return json.loads(body)


def save(name: str, data: dict) -> None:
    path = FIXTURES / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"{path.relative_to(Path.cwd())}: {path.stat().st_size // 1024} KB")


def main() -> None:
    key = os.environ.get("METEOSIX_API_KEY")
    if not key:
        sys.exit("Falta la variable de entorno METEOSIX_API_KEY")
    save(
        "meteosix_forecast.json",
        fetch(key, ";".join((SANTIAGO, CORUNA_COAST, OUTSIDE))),
    )
    save("meteosix_out_of_bounds.json", fetch(key, OUTSIDE))


if __name__ == "__main__":
    main()
