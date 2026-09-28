# Diseño de MeteoGal

Principios, estructura y decisiones. El detalle de cada función está en su documento: [weather.md](weather.md), [avisos.md](avisos.md), [radar.md](radar.md), [estaciones.md](estaciones.md); los servicios de MeteoGalicia, en [api.md](api.md).

## 1. Objetivo

Una sola integración para lo que ofrece MeteoGalicia, publicable en HACS:

- **Sin clave**, una experiencia completa, no una demo.
- **Con la clave de MeteoSIX**, más detalle, sin cambiar lo que ya tenía el usuario.

## 2. Principios

1. **Un dominio, `meteogal`, para todo.** HACS admite una integración por repositorio.
2. **La clave suma, no sustituye.** Añadir o quitar la clave no borra entidades ni cambia `unique_id`: como mucho, aparecen entidades nuevas o se rellenan datos que antes faltaban.
3. **Estable desde el principio.** `unique_id` y datos de configuración pensados para no cambiar nunca; si hace falta, migraciones de la entrada.
4. **Asíncrono y sin dependencias externas** salvo Pillow, para el radar: cliente HTTP propio con `aiohttp` y la sesión de HA.
5. **Paso a paso.** Cada función se valida con datos reales antes de proponerla, y se mira cómo lo resuelven otras integraciones del núcleo.
6. **Por defecto, poco ruido.** Lo esencial activado; lo demás, desactivado y fácil de activar.
7. **Complementos que no tumban nada.** MeteoSIX, radar, estación y cámaras pueden fallar sin que falle lo demás: solo la previsión pública es imprescindible para arrancar.

## 3. Qué da cada nivel

| Capacidad | Sin clave (servicios públicos) | Con clave (MeteoSIX) |
|---|---|---|
| Previsión diaria | Días 0–3 (`jsonPredConcellos`) y 4–7 u 8 (`jsonPredMedioPrazo`) | Además, lluvia total y viento máximo de los días 0–3 |
| Previsión por horas | Días 0–3 con cielo, temperatura y rumbo del viento (`jsonPredHorariaConcellos`) | Entera de MeteoSIX: lluvia, viento, humedad, nubosidad y presión, hasta el día +4 |
| Probabilidad de lluvia | Por día (la máxima de las franjas) | Igual: MeteoSIX no la da |
| Estado actual | Estación elegida y observación del concello | Además, humedad, presión, nubosidad y viento donde no llega la estación |
| Avisos | Por concello, hasta pasado mañana (`jsonAvisosConcellos`) | Igual |
| Radar | Observado, THREDDS de MeteoGalicia | Igual |
| Estación y cámara | `ultimos10minEstacionsMeteo`, `datosDiariosEstacionsMeteo`, `jsonCamaras` | Igual |
| Lluvia prevista | — | Lluvia esta hora, próxima lluvia, cota de nieve |

## 4. Configuración

Objetivo: **cero escritura**. Todo sale de unas coordenadas y el usuario solo confirma o corrige.

- **Estructura (D1):** una entrada `MeteoGal` y cada ubicación como **subentrada**, como `google_weather` en el núcleo.
- **Añadir una ubicación** (igual en la primera instalación y después):
  1. Punto en el mapa, por defecto la casa de HA. Fuera de Galicia, error y se elige otro.
  2. Confirmar lo deducido del punto: concello, estación (la más cercana, con lo que le falta a cada una), si la estación manda en el tiempo actual y cámara (la de la estación, si tiene).
- **Reconfigurar una ubicación:** los mismos dos pasos, sin perder entidades. Si no cambia el concello, se respeta lo elegido.
- **Clave de MeteoSIX:** en la entrada, con «Reconfigurar»; se comprueba antes de guardarla y, vacía, se quita. Si MeteoSIX deja de aceptarla, la reautenticación pide otra o permite quitarla.
- **Opciones del radar** (periodo y encuadre): en «Configurar» de la entrada, para todas las ubicaciones.
- **Textos:** traducciones propias en gallego, castellano e inglés, tuteando. «Concello» en gallego y castellano; «municipality» en inglés.

**Qué guarda cada ubicación (D7):** coordenadas, código INE del concello, estación (opcional), si la estación manda en el tiempo actual y cámara (opcional).

- El concello alimenta lo público: previsión, avisos y observación.
- Las coordenadas sirven para MeteoSIX, el radar y la estación más cercana.
- Concello desde coordenadas: contornos municipales del IGN incluidos en la integración (~465 KB). Validado en [concello-por-coordenadas.md](concello-por-coordenadas.md).
- Nombres de concello: siempre el topónimo oficial del Nomenclátor de Galicia, nunca el de la API ([toponimos.md](toponimos.md)).

## 5. Estructura del código

| Pieza | Qué hace |
|---|---|
| `api/` | Clientes de MeteoGalicia, MeteoSIX y radar, sin nada de HA |
| `coordinator.py` | Un coordinador por ubicación (previsión, observación y avisos) y por estación; uno por entrada para MeteoSIX, radar y cámaras |
| `weather.py`, `sensor.py`, `image.py` | Entidades, todas en el dispositivo de su ubicación |
| `radar.py`, `station.py`, `warnings.py`, `codes.py` | Lógica sin HA: dibujo del radar, sensores de estación, avisos y códigos de cielo |
| `repairs.py` | Aviso y arreglo cuando la estación deja de enviar |
| `diagnostics.py` | Estado de cada fuente, sin clave ni coordenadas |

Cumple todas las reglas de la escala de calidad de Home Assistant, de bronce a platino (`quality_scale.yaml`), con tipado estricto (mypy) en la CI.

## 6. Decisiones

| # | Pregunta | Decisión |
|---|---|---|
| D1 | ¿Una entrada por ubicación, con la clave repetida, o la clave una sola vez? | Entrada con la clave y ubicaciones como subentradas |
| D2 | ¿Cliente dentro de la integración o librería en PyPI? | Dentro (`api/`), asíncrono y sin nada de HA, para poder sacarlo a PyPI |
| D3 | Idioma | README y documentación en castellano; traducciones gl, es y en |
| D4 | Versiones | Año y mes, como HA (`2026.10.0`, `2026.10.1`…) |
| D5 | Licencia | Apache 2.0, la del núcleo de HA. Los datos de terceros mantienen la suya (`NOTICE`) |
| D6 | Icono | Galicia con sol, claro y oscuro (`docs/brand/`) |
| D7 | ¿Qué guarda cada ubicación? | Coordenadas, concello, estación, uso de la estación y cámara; todo deducido de las coordenadas y confirmado por el usuario |
| D8 | ¿Sensores de previsión (lluvia en 24 h, máxima de mañana…)? | No: para eso está `weather.get_forecasts`, como pide HA. Solo lluvia esta hora, próxima lluvia y cota de nieve |
| D9 | ¿Cómo exponer los avisos? | Nivel vigente y próximo (enum), contadores desactivados y la acción `meteogal.get_warnings`, como GeoSphere en el núcleo ([avisos.md](avisos.md)) |
| D10 | ¿La estación manda en el tiempo actual? | Sí por defecto, como AEMET, pero es una opción por ubicación: no siempre representa el punto |
| D11 | ¿Radar como imagen de MeteoGalicia o dibujado? | Dibujado por MeteoGal a partir de los datos en grises: escala, mapa y leyenda propios, centrado en cada ubicación ([radar.md](radar.md)) |
