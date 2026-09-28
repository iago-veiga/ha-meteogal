# Estación y cámara de cada ubicación

Fecha: 2026-09-27. Uso para el usuario en el README (secciones «Estación», «Cámara» y «El tiempo»).

## Fuentes (sin clave)

| Servicio | Qué da | Cada cuánto |
|---|---|---|
| `observacion/ultimos10minEstacionsMeteo.action?idEst=` | Última lectura de 10 min (hora en UTC) | Cada 10 min, ~5 min de retraso |
| `observacion/ultimos10minEstacionsMeteo.action` (sin `idEst`) | La última lectura de las 166 estaciones (~320 KB, 0,2 s), solo al elegir la estación | Al abrir el formulario |
| `observacion/datosDiariosEstacionsMeteo.action?idEst=` | Acumulados y extremos de hoy hasta ahora | Con cada lectura |
| `observacion/listaEstacionsMeteo.action` | Nombre y coordenadas (una vez, para el diagnóstico) | — |
| `observacion/jsonCamaras.action` | Las 33 cámaras con la URL y la hora de su última foto | Cada ~5 min |

Cada medida trae un código de validación: se aceptan **0** (sin validar, lo más reciente), **1** (válido) y **5** (interpolado); se descartan 2 (sospechoso), 3 (erróneo) y 9 (no registrado). Una estación inexistente o sin datos devuelve listas vacías.

## Sensores

Solo se crean los de los códigos que la estación manda en su primera lectura (si al arrancar no hay datos, se crean con la primera que llegue). Catálogo en `station.py`:

| Clave | Código | Lectura | Unidad | Por defecto |
|---|---|---|---|---|
| `station_temperature` | `TA_AVG_1.5m` | 10 min | °C | Activado |
| `station_humidity` | `HR_AVG_1.5m` | 10 min | % | Activado |
| `station_rain_10min` | `PP_SUM_1.5m` | 10 min | mm | Activado |
| `station_rain_today` | `PP_SUM_1.5m` | hoy | mm (`total_increasing`) | Activado |
| `station_wind_speed` | `VV_AVG_10m` | 10 min | m/s (HA lo muestra en km/h) | Activado |
| `station_wind_gust` | `VV_RACHA_10m` | 10 min | m/s | Activado |
| `station_pressure` | `PRED_AVG_1.5m` | 10 min | hPa (reducida al nivel del mar) | Activado |
| `station_water_temperature` | `TSA_AVG_-1m` | 10 min | °C | Activado |
| `station_wind_direction` | `DV_AVG_10m` | 10 min | ° | Desactivado |
| `station_dew_point` | `TO_AVG_1.5m` | 10 min | °C | Desactivado |
| `station_temperature_max_today`, `_min_today` | `TA_MAX_1.5m`, `TA_MIN_1.5m` | hoy | °C | Desactivados |
| `station_wind_max_today` | `VV_MAX_10m` | hoy | m/s | Desactivado |
| `station_sun_hours_today` | `HSOL_SUM_1.5m` | hoy | h | Desactivado |
| `station_evapotranspiration_today` | `ET0_SUM_1.5m` | hoy | mm | Desactivado |
| `station_solar_radiation`, `station_uv_radiation` | `RS_AVG_1.5m`, `BIO_AVG_1.5m` | 10 min | W/m² | Desactivados |
| `station_ground_temperature`, `station_soil_temperature` | `TA_AVG_0.1m`, `TS_AVG_-0.1m` | 10 min | °C | Desactivados |
| `station_soil_moisture` | `HS_CV_AVG_-0.2m` | 10 min | % (de m³/m³) | Desactivado |
| `station_updated` | — | 10 min | hora | Activado (diagnóstico) |

- `station_updated`: hora de la última lectura; atributos `station_id`, `station_name` y `distance` (km desde la ubicación).
- Justo después de medianoche el servicio diario ya devuelve el día nuevo, pero con todos los valores a `-9999` y código 9 (visto a las 00:09 del 2026-09-28): los de hoy quedan «Desconocido» hasta que hay datos. Si en ese momento el día no trae ninguna medida válida, los sensores de hoy se crean igual, deducidos de la lectura de 10 minutos (`requires` en `station.py`).
- Lectura de más de **1 hora**: valores «Desconocido» (la estación ha dejado de enviar). Datos de hoy de otro día (justo después de medianoche): «Desconocido».
- **Viento todo a cero** (velocidad, racha y desviación de la dirección exactamente 0): se quita el viento de esa lectura. Visto en Coruña-Dique el 2026-09-27 a las 21:40Z con la dirección de la racha en 13°, cuando las horas de antes y después tenían rachas de 2–5 m/s.

## Elegir la estación

En el paso de confirmación, cada estación de la lista lleva lo que le falta de lo que usa el [tiempo actual](#tiempo-actual), según su última lectura (`station_gaps` en `station.py`):

| Marca | Cuándo |
|---|---|
| «sin viento» | La lectura no trae `VV_AVG_10m` (113 de 166 lo miden, 2026-09-28) |
| «sin presión» | La lectura no trae `PRED_AVG_1.5m` (109 de 166) |
| «sin viento ni presión» | Las dos |
| «sin datos ahora» | No está en la lectura, o su lectura va más de 1 h por detrás de la más reciente de todas. Se compara con esa y no con el reloj, para no marcarlas todas si MeteoGalicia va con retraso. El 2026-09-28, Marroxo y Serra do Faro, sin enviar desde el 19 y el 23 |

Se mira si llega el código, aunque su valor sea 0: importa que la estación lo mida. Temperatura, humedad y lluvia no se marcan porque las miden casi todas (165–166).

**Estación propuesta:** sigue siendo la más cercana. Si le falta algo, un aviso en la descripción del paso nombra la siguiente más cercana que lo da y envía datos: «La estación más cercana, Coruña-Torre de Hércules, no mide viento ni presión. Coruña-Dique (3,5 km) sí.» Solo sale cuando la estación elegida en el formulario es la más cercana: al reconfigurar con otra ya elegida, no.

Si la lectura de todas falla, la lista queda sin marcas y sin aviso: es una ayuda, no bloquea nada. Textos en gl, es y en, construidos en `config_flow.py` porque las opciones de un desplegable dinámico no pasan por las traducciones de HA.

## Tiempo actual

Con **Usar la estación para el tiempo actual** (dato de la ubicación `station_weather`, por defecto sí), la entidad `weather` toma de la estación, si su lectura es reciente: temperatura, humedad, presión, punto de rocío, racha y viento (velocidad y rumbo solo si están los dos). Si falta algo, sigue con MeteoSIX o con la observación del concello (orden completo en el README). El cielo nunca sale de la estación. Es lo mismo que hace AEMET en el núcleo de HA (allí sin opción).

## Estación que deja de enviar (reparación)

Si la última lectura de la estación tiene **más de un día**, se abre un aviso en Ajustes → Reparaciones (`repairs.py`): «La estación de A Coruña no envía datos», con la estación y desde cuándo. Pasa de verdad: el 2026-09-28, Marroxo llevaba sin enviar desde el 19 y Serra do Faro desde el 23; el servicio sigue devolviendo esa última lectura vieja, con su hora.

- Al arreglarlo se ofrece la lista de estaciones con sus marcas; la propuesta es la más cercana que envía datos, sin contar la actual. Vacía, la ubicación se queda sin estación. Se guarda en la ubicación y MeteoGal se recarga.
- El aviso se cierra solo cuando la estación vuelve a enviar, al quitar la estación o la ubicación, y al borrar MeteoGal.
- Un día y no una hora: una estación puede pasar horas sin enviar (mantenimiento) y no hace falta molestar. Mientras tanto, los sensores ya quedan «Desconocido» a la hora.
- Si el servicio no devuelve ninguna lectura, no se avisa: no se sabe desde cuándo.

## Cámara

Dato de la ubicación `camera_id` (o ninguno): la **carpeta de la foto** (`Corunha`, `Onsplaya`…), no el identificador, porque Ons (playa y puerto) y Cíes (faro norte y sur) tienen dos cámaras con el mismo identificador. En la configuración se ofrecen las 33 cámaras de la más cercana a la más lejana; por defecto, la de la estación elegida si comparten identificador (si tiene dos, la primera) (19 de las 33 cámaras están en una estación). Entidad `image` con `image_url` de la foto grande y `image_last_updated` con su hora: cuando cambia la hora, se vacía la caché y HA descarga la foto nueva.

## Pendiente

- Servicio de rayos (`JSON_Raios`), sin revisar.
