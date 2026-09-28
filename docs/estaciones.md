# Estación y cámara de cada ubicación

Fecha: 2026-09-27. Uso para el usuario en el README (secciones «Estación», «Cámara» y «El tiempo»).

## Fuentes (sin clave)

| Servicio | Qué da | Cada cuánto |
|---|---|---|
| `observacion/ultimos10minEstacionsMeteo.action?idEst=` | Última lectura de 10 min (hora en UTC) | Cada 10 min, ~5 min de retraso |
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

## Tiempo actual

Con **Usar la estación para el tiempo actual** (dato de la ubicación `station_weather`, por defecto sí), la entidad `weather` toma de la estación, si su lectura es reciente: temperatura, humedad, presión, punto de rocío, racha y viento (velocidad y rumbo solo si están los dos). Si falta algo, sigue con MeteoSIX o con la observación del concello (orden completo en el README). El cielo nunca sale de la estación. Es lo mismo que hace AEMET en el núcleo de HA (allí sin opción).

## Cámara

Dato de la ubicación `camera_id` (o ninguno): la **carpeta de la foto** (`Corunha`, `Onsplaya`…), no el identificador, porque Ons (playa y puerto) y Cíes (faro norte y sur) tienen dos cámaras con el mismo identificador. En la configuración se ofrecen las 33 cámaras de la más cercana a la más lejana; por defecto, la de la estación elegida si comparten identificador (si tiene dos, la primera) (19 de las 33 cámaras están en una estación). Entidad `image` con `image_url` de la foto grande y `image_last_updated` con su hora: cuando cambia la hora, se vacía la caché y HA descarga la foto nueva.

## Pendiente

- Indicar en el desplegable qué mide cada estación (por ejemplo, que Torre de Hércules no mide viento y Coruña-Dique sí).
- Servicio de rayos (`JSON_Raios`), sin revisar.
