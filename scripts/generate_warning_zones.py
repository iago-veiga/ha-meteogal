"""Genera `data/zonas_avisos.json`: las zonas de avisos de cada concello.

El RSS de avisos de MeteoGalicia (`rssAdversos`) da el comentario de cada aviso por
zona: el concello, su agrupación, su provincia o toda Galicia. Esta tabla dice, por
código INE, cuál es la zona del concello y la de su agrupación (docs/avisos.md).

Fuente: «Definición de zonas de adverso meteorolóxico» de MeteoGalicia,
https://www.meteogalicia.gal/datosred/infoweb/meteo/docs/adversos/DefinicionZonasAdversos_es.pdf
pasado a texto con `pdftotext -layout`. Los nombres se emparejan con los de
`jsonConcellosNivelMax` (mismo formato: «Coruña (A)»), que da el código INE.

Uso:
    pdftotext -layout DefinicionZonasAdversos_es.pdf zonas.txt
    python3 scripts/generate_warning_zones.py zonas.txt

Comprueba que las 313 salen, que cada concello está en una sola agrupación y que
cada agrupación tiene los concellos que dice el documento.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unicodedata
import urllib.request

OUT = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "meteogal"
    / "data"
    / "zonas_avisos.json"
)
CONCELLOS_URL = (
    "https://servizos.meteogalicia.gal/mgrss/predicion/adversos/"
    "jsonConcellosNivelMax.action?dia=0"
)
# Erratas de la API frente al documento: nombre del documento → de la API.
ALIASES = {"Pontes de García Rodríguez (As)": "Pontes De Garcáa Rodríguez (As)"}


def norm(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]+", " ", name.lower()).strip()


def main(path: str) -> None:
    text = Path(path).read_text(encoding="utf-8")
    part1, rest = text.split("2. Agrupación de municipios", 1)
    part2 = rest.split("3. Provincia", 1)[0]

    # 1. Municipio: «Coruña (A) [213]» (a veces sin el corchete de cierre).
    own = {
        name.strip(): int(zone)
        for name, zone in re.findall(r"([^\[\]\n]+?)\s*\[(\d+)\]?", part1)
        if name.strip() and "Municipio" not in name
    }
    if len(own) != 313:
        raise SystemExit(f"Esperaba 313 concellos, salen {len(own)}")

    # 2. Agrupaciones: cabecera «Nombre [id]» y la lista de sus concellos.
    known = sorted(((norm(n), n) for n in own), key=lambda item: -len(item[0]))
    heads = list(
        re.finditer(
            r"^\s*([^\n\[]+?)\s*\[(\d+)\]\s*\n\s*Está formado por (\d+) municipios",
            part2,
            re.M,
        )
    )
    group: dict[str, int] = {}
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(part2)
        body = " " + norm(part2[head.end() : end].split(":", 1)[-1]) + " "
        found = []
        for key, name in known:
            if f" {key} " in body:
                found.append(name)
                body = body.replace(f" {key} ", " | ", 1)
        if len(found) != int(head.group(3)):
            raise SystemExit(f"{head.group(1)}: {len(found)} de {head.group(3)}")
        for name in found:
            if name in group:
                raise SystemExit(f"{name} en dos agrupaciones")
            group[name] = int(head.group(2))
    if len(group) != 313:
        raise SystemExit(f"Sin agrupación: {sorted(set(own) - set(group))}")

    with urllib.request.urlopen(CONCELLOS_URL, timeout=30) as response:
        api = json.load(response)
    ine = {
        norm(item["nomeConcello"]): int(item["idConcello"])
        for item in api["listaDiaConcellos"][0]["listaNiveisMaximos"]
    }
    zones = {}
    for name, zone in own.items():
        code = ine.get(norm(ALIASES.get(name, name)))
        if code is None:
            raise SystemExit(f"Sin código INE: {name}")
        zones[str(code)] = [zone, group[name]]

    OUT.write_text(
        json.dumps(
            {
                "source": "MeteoGalicia, Definición de zonas de adverso meteorolóxico",
                "zones": dict(sorted(zones.items())),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{OUT}: {len(zones)} concellos, {len(heads)} agrupaciones")


if __name__ == "__main__":
    main(sys.argv[1])
