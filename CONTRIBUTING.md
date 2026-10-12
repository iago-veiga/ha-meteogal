# Colaborar

Gracias por querer ayudar. MeteoGal es una integración pequeña y se mantiene a ratos, así que lo más útil es:

- **Preguntas y ejemplos en [Discussions](https://github.com/iago-veiga/ha-meteogal/discussions).** Si algo no es un error, ahí es el sitio.
- **Una incidencia bien descrita.** Mira [Problemas frecuentes](README.md#problemas-frecuentes) y adjunta los **diagnósticos** (Ajustes → Dispositivos y servicios → MeteoGal → ⋮ → Descargar diagnósticos). No llevan tu clave ni tus coordenadas.
- **Datos de otro sitio de Galicia.** Si algo sale mal en tu concello (una estación que mide algo raro, un nombre, un aviso), dime cuál: la integración se prueba con unos pocos concellos.
- **Traducciones.** Los textos están en gallego, castellano e inglés (`custom_components/meteogal/translations/`). Si ves una errata o una forma mejor de decirlo, un cambio pequeño es bienvenido.
- **Código.** Abre antes una incidencia para comentar la idea; así no se pierde trabajo. Las decisiones de diseño están en [docs/diseno.md](docs/diseno.md).

## Preparar el entorno

Python 3.14 (la CI también pasa con la versión mínima, Home Assistant 2025.11 y Python 3.13):

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
ruff check . && ruff format --check .
mypy custom_components/meteogal
pytest
```

Los tests usan respuestas reales de MeteoGalicia guardadas en `tests/api/fixtures/`: no necesitan red ni clave.

## Antes de enviar un cambio

- Que pasen `ruff`, `mypy` y `pytest`.
- Si cambia lo que ve el usuario, actualiza el [README](README.md) (con todas las opciones y un ejemplo) y el documento de `docs/` de esa parte, y añade una línea al [CHANGELOG](CHANGELOG.md).
- Los textos nuevos, en gallego, castellano e inglés.
- Los nombres de concello salen siempre de `toponyms.py`, nunca de la API.

## Licencia

Al colaborar aceptas que tu aportación se publique con la [licencia Apache 2.0](LICENSE) del proyecto.
