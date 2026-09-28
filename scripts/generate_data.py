"""Genera los datos incluidos en la integración.

- `data/concellos.json`: contornos de los 313 concellos de Galicia y de los municipios
  limítrofes de Asturias, León y Zamora, desde el servicio WFS del IGN (CC BY 4.0),
  simplificados a ~100 m.
- `data/toponimos.json`: nombre oficial de cada concello según el Nomenclátor de
  Galicia de la Xunta (CC BY-SA 4.0), emparejado con su código INE.

Uso: python scripts/generate_data.py
"""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
import re
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

WFS_URL = "https://www.ign.es/wfs-inspire/unidades-administrativas"
NOMENCLATOR_URL = (
    "https://abertos.xunta.gal/catalogo/territorio-vivienda-transporte/-/dataset/"
    "0270/nomenclator-galicia/001/descarga-directa-ficheiro.csv"
)

# Prefijo del código nacional del IGN: país (34) + comunidad + provincia.
GALICIA = {"15": "341215", "27": "341227", "32": "341232", "36": "341236"}
NEIGHBOURS = {"33": "340333", "24": "340724", "49": "340749"}
PROVINCE_NAMES = {"A CORUÑA": "15", "LUGO": "27", "OURENSE": "32", "PONTEVEDRA": "36"}

EXPECTED_CONCELLOS = 313
TOLERANCE_M = 100
# Municipios vecinos que se guardan: los que tienen algún punto a esta distancia.
NEIGHBOUR_MARGIN_KM = 3
DECIMALS = 4

DATA_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "meteogal" / "data"
)

NS = {
    "wfs": "http://www.opengis.net/wfs/2.0",
    "gml": "http://www.opengis.net/gml/3.2",
    "au": "http://inspire.ec.europa.eu/schemas/au/4.0",
    "gn": "http://inspire.ec.europa.eu/schemas/gn/4.0",
}

type Ring = list[tuple[float, float]]
type Polygon = list[Ring]


def fetch_units(prefix: str) -> dict[str, tuple[str, list[Polygon]]]:
    """Municipios con código nacional `prefix*`: código INE → (nombre, polígonos)."""
    fes = (
        '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0" '
        'xmlns:au="http://inspire.ec.europa.eu/schemas/au/4.0">'
        '<fes:PropertyIsLike wildCard="*" singleChar="." escapeChar="!">'
        "<fes:ValueReference>au:nationalCode</fes:ValueReference>"
        f"<fes:Literal>{prefix}*</fes:Literal></fes:PropertyIsLike></fes:Filter>"
    )
    query = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typenames": "au:AdministrativeUnit",
            "filter": fes,
        }
    )
    with urllib.request.urlopen(f"{WFS_URL}?{query}", timeout=600) as response:
        root = ET.fromstring(response.read())

    units = {}
    for unit in root.iterfind("wfs:member/au:AdministrativeUnit", NS):
        code = unit.findtext("au:nationalCode", namespaces=NS)
        if not code or code.endswith("00000"):  # provincia o comunidad
            continue
        name = unit.findtext(".//gn:text", namespaces=NS)
        polygons = []
        for polygon in unit.iterfind(".//gml:Polygon", NS):
            rings = [
                _ring(pos.text or "")
                for pos in polygon.iterfind(".//gml:LinearRing/gml:posList", NS)
            ]
            polygons.append(rings)
        units[code[-5:]] = (name, polygons)
    return units


def _ring(pos_list: str) -> Ring:
    # EPSG:4258 viene en orden latitud, longitud; se guarda longitud, latitud.
    values = [float(v) for v in pos_list.split()]
    return [(values[i + 1], values[i]) for i in range(0, len(values), 2)]


def simplify(ring: Ring, tolerance_m: float) -> Ring:
    """Douglas-Peucker iterativo en un plano local (metros)."""
    if len(ring) < 5:
        return ring
    lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
    kx, ky = 111_320 * math.cos(lat0), 110_570
    pts = [(x * kx, y * ky) for x, y in ring]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    # Un anillo cerrado empieza y acaba en el mismo punto: se parte por el más lejano.
    far = max(range(len(pts)), key=lambda i: math.dist(pts[0], pts[i]))
    keep[far] = True
    stack = [(0, far), (far, len(pts) - 1)]
    while stack:
        start, end = stack.pop()
        (x1, y1), (x2, y2) = pts[start], pts[end]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-9
        best, index = 0.0, None
        for i in range(start + 1, end):
            d = abs(dy * pts[i][0] - dx * pts[i][1] + x2 * y1 - y2 * x1) / norm
            if d > best:
                best, index = d, i
        if index is not None and best > tolerance_m:
            keep[index] = True
            stack += [(start, index), (index, end)]
    return [p for p, k in zip(ring, keep, strict=True) if k]


def simplified(polygons: list[Polygon]) -> list:
    out = []
    for polygon in polygons:
        exterior, *holes = (simplify(r, TOLERANCE_M) for r in polygon)
        if len(exterior) < 4:  # islote que desaparece al simplificar
            continue
        rings = [exterior, *(h for h in holes if len(h) >= 4)]
        out.append(
            [[[round(x, DECIMALS), round(y, DECIMALS)] for x, y in r] for r in rings]
        )
    return out


def near_galicia(polygons: list[Polygon], grid: set[tuple[int, int]]) -> bool:
    cell = NEIGHBOUR_MARGIN_KM / 100  # ~3 km en grados, de sobra
    return any(
        (int(x // cell) + dx, int(y // cell) + dy) in grid
        for polygon in polygons
        for x, y in polygon[0]
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
    )


def fetch_toponyms() -> list[tuple[str, str, set[str]]]:
    """(provincia, nombre oficial NG2025, nombres anteriores) de cada concello."""
    with urllib.request.urlopen(NOMENCLATOR_URL, timeout=120) as response:
        text = response.read().decode("utf-8-sig")
    concellos: dict[tuple[str, str], set[str]] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        key = (PROVINCE_NAMES[row["Provincia"]], row["Nome concello NG2025"])
        concellos.setdefault(key, set()).add(
            row["Nome concello NG2003"] or row["Nome concello NG2025"]
        )
    return [(p, name, olds) for (p, name), olds in concellos.items()]


def official_name(raw: str) -> str:
    """'BAÑA, A' → 'A Baña'; 'SAN CIBRAO DAS VIÑAS' → 'San Cibrao das Viñas'."""
    match = re.fullmatch(r"(.+), (A|O|AS|OS)", raw)
    words = ([match[2]] if match else []) + (match[1] if match else raw).split(" ")
    return " ".join(
        w.lower()
        if i and w.lower() in {"de", "do", "da", "dos", "das", "e"}
        else w[:1] + w[1:].lower()
        for i, w in enumerate(words)
    )


def _key(name: str) -> str:
    plain = "".join(
        c
        for c in unicodedata.normalize("NFD", name.upper())
        if unicodedata.category(c) != "Mn"
    )
    if match := re.fullmatch(r"(.+)(?:, | \()(A|O|AS|OS)\)?", plain):
        plain = f"{match[2]} {match[1]}"
    return plain.replace("-", " ")


def main() -> None:
    galicia: dict[str, tuple[str, list[Polygon]]] = {}
    for prefix in GALICIA.values():
        galicia |= fetch_units(prefix)
    if len(galicia) != EXPECTED_CONCELLOS:
        raise SystemExit(f"Se esperaban {EXPECTED_CONCELLOS} concellos: {len(galicia)}")

    cell = NEIGHBOUR_MARGIN_KM / 100
    grid = {
        (int(x // cell), int(y // cell))
        for _, polygons in galicia.values()
        for polygon in polygons
        for x, y in polygon[0]
    }
    neighbours = []
    for prefix in NEIGHBOURS.values():
        neighbours += [
            polygons
            for _, polygons in fetch_units(prefix).values()
            if near_galicia(polygons, grid)
        ]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    concellos_file = DATA_DIR / "concellos.json"
    concellos_file.write_text(
        json.dumps(
            {
                "source": "Instituto Geográfico Nacional (IGN), WFS de unidades "
                f"administrativas; simplificado a {TOLERANCE_M} m",
                "license": "CC BY 4.0",
                "concellos": {
                    code: simplified(polygons)
                    for code, (_, polygons) in sorted(galicia.items())
                },
                "outside": [p for n in neighbours for p in simplified(n)],
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    by_key: dict[tuple[str, str], str] = {
        (code[:2], _key(name)): code for code, (name, _) in galicia.items()
    }
    toponyms = {}
    for province, name, olds in fetch_toponyms():
        codes = {by_key.get((province, _key(n))) for n in {name, *olds}} - {None}
        if len(codes) != 1:
            raise SystemExit(f"No se puede emparejar {name!r}: {codes}")
        toponyms[codes.pop()] = official_name(name)
    if set(toponyms) != set(galicia):
        raise SystemExit("El Nomenclátor y el IGN no tienen los mismos concellos")

    toponyms_file = DATA_DIR / "toponimos.json"
    toponyms_file.write_text(
        json.dumps(
            {
                "source": "Nomenclátor de Galicia (Xunta de Galicia), datos abertos",
                "license": "CC BY-SA 4.0",
                "concellos": dict(sorted(toponyms.items())),
            },
            ensure_ascii=False,
            indent=0,
        ),
        encoding="utf-8",
    )

    changed = {
        code: (galicia[code][0], name)
        for code, name in toponyms.items()
        if name != galicia[code][0]
    }
    print(
        f"{concellos_file.name}: {concellos_file.stat().st_size // 1024} KB, "
        f"{len(galicia)} concellos, {len(neighbours)} municipios vecinos"
    )
    print(
        f"{toponyms_file.name}: {len(toponyms)} nombres; distintos del IGN: {changed}"
    )


if __name__ == "__main__":
    main()
