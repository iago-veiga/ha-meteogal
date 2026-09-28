# Diseño de MeteoGal

Fecha: 2026-09-26. Borrador: fija el enfoque, no la implementación. Servicios de MeteoGalicia que usa el cliente: [api.md](api.md).

## 1. Objetivo

Una sola integración para todo lo que ofrece MeteoGalicia, publicable en la lista por defecto de HACS:

- **Sin clave** tiene que dar una experiencia completa, no una demo.
- **Con la clave de MeteoSIX** se gana detalle, sin cambiar lo que ya tenía el usuario.

## 2. Principios

1. **Un dominio, `meteogal`, para todo.** HACS admite una integración por repo.
2. **La clave suma, no sustituye.** Añadir o quitar la clave no borra entidades ni cambia `unique_id`. Como mucho, activa entidades nuevas o rellena atributos que antes venían vacíos.
3. **Estable desde el principio.** `unique_id` y datos de configuración pensados para no cambiar nunca; si hace falta, migraciones de config entry.
4. **Asíncrono.** Cliente HTTP propio con `aiohttp` y la sesión de HA; sin dependencias externas mientras sea posible.
5. **Paso a paso.** Una capacidad por versión, validada con datos reales antes de proponerla.
6. **Por defecto, poco ruido.** Lo esencial activado; lo demás, desactivado y fácil de activar.

## 3. Niveles

Lo marcado "por validar" hay que comprobarlo con datos reales antes de comprometerlo.

| Capacidad | Sin clave (servicios públicos) | Con clave (MeteoSIX) |
|---|---|---|
| Previsión diaria | Días 0–3 (`jsonPredConcellos`) + días 4–7 u 8 (`jsonPredMedioPrazo`) | Por coordenadas (`getNumericForecastInfo`); alcance por validar |
| Previsión horaria | ~74 h con cielo, temperatura y rumbo del viento (`jsonPredHorariaConcellos`) | Añade lluvia (mm), viento (velocidad), humedad, nubosidad y presión |
| Probabilidad de lluvia | Por franja (mañana, tarde, noche) | Por validar si MeteoSIX la da por hora o hay que derivarla |
| Estado actual | Estación elegida (`ultimos10minEstacionsMeteo`) y concello (`observacionConcellos`) | Igual |
| Avisos | Por concello, hoy y mañana (`jsonAvisosConcellos`, `jsonConcellosNivelMax`) | Igual |
| Día y noche | Del código de cielo | Del código de cielo + `getSolarInfo` |
| Ubicación | Concello (código) | Coordenadas exactas o lugar (`findPlaces`) |
| Mareas | `jsonMareas` (por validar) | `getTidesInfo` |
| Más adelante | Calidad del aire, playas, cámaras, texto de previsión de Galicia | — |

## 4. Configuración

Objetivo: **cero escritura**. Todo sale de unas coordenadas y el usuario solo confirma o corrige.

**Estructura (D1):** una entrada `MeteoGal` con la clave de MeteoSIX (opcional) y cada ubicación como **subentrada**, como hace `google_weather` en core. La clave se añade, cambia o quita reconfigurando la entrada, sin tocar las ubicaciones.

**Primera instalación:**

1. **Ubicación:** mapa con la casa de HA por defecto. Si el punto cae fuera de Galicia, error y se elige otro.
2. **Confirmar:** formulario ya relleno que solo hay que aceptar:
   - **Concello** detectado a partir de las coordenadas (lista de 313 con búsqueda, por si hay que corregirlo).
   - **Estación** más cercana, con su concello y distancia (opcional: se puede dejar vacía).

La **clave de MeteoSIX** no se pide en la primera instalación: se añade, cambia o quita con «Reconfigurar» en la entrada MeteoGal, sin tocar las ubicaciones. Se comprueba con MeteoSIX antes de guardarla; vacía, se quita. Se guarda en los datos de la entrada. Si MeteoSIX deja de aceptarla (`005`/`006`), la reautenticación pide otra o permite quitarla para seguir sin clave.

**Textos:** traducciones propias en gallego, castellano e inglés, tuteando. En gallego y castellano se dice "concello"; en inglés, "municipality".

**Después:** añadir más ubicaciones (subentrada con los mismos dos pasos, sin la clave) y reconfigurar cualquiera de ellas sin perder entidades.

**Qué guarda cada ubicación (D7):** coordenadas, `idConcello` y estación (opcional).

- El concello alimenta todo lo público: previsión diaria y horaria, medio plazo, avisos y observación.
- Las coordenadas sirven para MeteoSIX y para la estación más cercana.
- Concello desde coordenadas: contornos municipales del IGN incluidos en la integración (~465 KB). Validado en [concello-por-coordenadas.md](concello-por-coordenadas.md).
- Nombres de concello: siempre el topónimo oficial del Nomenclátor de Galicia, nunca el de la API ([toponimos.md](toponimos.md)).

## 5. Decisiones

| # | Pregunta | Decisión |
|---|---|---|
| D1 | ¿Una entrada por ubicación, con la clave repetida en cada una, o la clave guardada una sola vez? | **Cerrada:** entrada con la clave y ubicaciones como subentradas |
| D2 | ¿Cliente dentro de la integración o librería propia en PyPI? | **Cerrada:** dentro (`custom_components/meteogal/api/`), asíncrono y sin nada de HA, para poder sacarlo a PyPI |
| D3 | Idioma de README, textos y traducciones | **Cerrada:** README en castellano de momento; traducciones gl, es y en, tuteando |
| D4 | Esquema de versiones | **Cerrada:** año y mes, como HA (`2026.10.0`, `2026.10.1`…), sin cero delante del mes |
| D5 | Licencia | **Cerrada:** Apache 2.0, la de HA core. Los datos incluidos de terceros (contornos del IGN) mantienen la suya y se citan en `NOTICE` |
| D6 | Icono propio para `brand/` | Cerrada: Galicia con sol, claro y oscuro (`docs/brand/`) |
| D7 | ¿Qué guarda cada ubicación y cómo se elige? | **Cerrada:** coordenadas + concello + estación; concello y estación se deducen de las coordenadas y el usuario confirma |

## 6. Primer hito (0.1)

Entidad `weather` **sin clave** para un concello: estado actual, previsión diaria (8 o 9 días) y horaria. Configuración por UI con concello y estación deducidos de las coordenadas. Nada más.
