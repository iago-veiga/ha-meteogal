"""Nombres oficiales de los concellos de Galicia.

Todo nombre de concello que vea el usuario sale de aquí, nunca de la API de
MeteoGalicia (sus nombres traen erratas y mayúsculas mal puestas). Los topónimos no
se traducen: su única forma oficial es la gallega (Lei 3/1983, art. 10).

Fuente: Nomenclátor de Galicia (Xunta de Galicia, CC BY-SA 4.0). Se regenera con
`scripts/generate_data.py`.

Sin dependencias de Home Assistant. `load_toponyms()` lee un fichero: en Home
Assistant hay que llamarlo en el executor, no en el bucle de eventos.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "toponimos.json"


def load_toponyms(path: Path = DATA_FILE) -> dict[int, str]:
    """Código INE → nombre oficial (lee un fichero: bloquea)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {int(code): name for code, name in data["concellos"].items()}
