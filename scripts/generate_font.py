"""Genera la fuente de las imágenes de radar: DejaVu Sans reducida a latín.

La fuente que trae Pillow no tiene tildes y la completa ocupa ~750 KB. Se queda
con los caracteres latinos (ASCII, Latin-1 y unos pocos signos), suficientes para
gallego, castellano e inglés.

- `data/DejaVuSans-latin.ttf`: la fuente reducida.
- `data/DejaVuSans-LICENSE.txt`: su licencia (Bitstream Vera + dominio público),
  que tiene que acompañar a la fuente.

Necesita `fonttools` (solo para generar, no en la integración).

Uso: python scripts/generate_font.py
"""

from __future__ import annotations

import io
from pathlib import Path
import urllib.request
import zipfile

from fontTools import subset

RELEASE = (
    "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/"
    "version_2_37/dejavu-fonts-ttf-2.37.zip"
)
DATA = Path(__file__).parent.parent / "custom_components" / "meteogal" / "data"
FONT = DATA / "DejaVuSans-latin.ttf"
LICENSE = DATA / "DejaVuSans-LICENSE.txt"

# ASCII imprimible, Latin-1 (tildes, ñ, ç, º, ª, ·) y signos tipográficos.
UNICODES = [*range(0x20, 0x7F), *range(0xA0, 0x100), 0x2013, 0x2014, 0x2026, 0x2212]


def main() -> None:
    with urllib.request.urlopen(RELEASE, timeout=120) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))
    names = archive.namelist()
    source = next(n for n in names if n.endswith("/ttf/DejaVuSans.ttf"))
    license_name = next(n for n in names if n.endswith("/LICENSE"))

    options = subset.Options()
    options.layout_features = ["kern", "liga"]
    options.hinting = False
    options.desubroutinize = True
    font = subset.load_font(io.BytesIO(archive.read(source)), options)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=UNICODES)
    subsetter.subset(font)
    subset.save_font(font, str(FONT), options)
    LICENSE.write_bytes(archive.read(license_name))
    print(f"{FONT.name}: {FONT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
