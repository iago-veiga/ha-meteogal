# Clientes de la API

Código en `custom_components/meteogal/api/`, asíncrono, con la sesión de `aiohttp` que le pasa Home Assistant y sin nada más de HA (D2 en [diseno.md](diseno.md)), para poder sacarlo a una librería. Tests en `tests/api/` con respuestas reales guardadas en `tests/api/fixtures/` (licencia en `NOTICE`).

## Servicios públicos (`MeteoGalClient`, sin clave)

Base `https://servizos.meteogalicia.gal/mgrss`.

| Método | Servicio | Devuelve |
|---|---|---|
| `get_concellos()` | `jsonConcellosNivelMax?dia=0` | Los 313 concellos (código INE y nombre). No lo usa la integración: los nombres salen del Nomenclátor |
| `get_stations()` | `listaEstacionsMeteo` | 155 estaciones con coordenadas, altitud y concello |
| `get_daily_forecast(id)` | `jsonPredConcellos` | Días 0–3: cielo, lluvia y viento por franja (mañana, tarde, noche), temperaturas, UV y nivel de aviso |
| `get_hourly_forecast(id)` | `jsonPredHorariaConcellos` | Horas desde las 00:00 de hoy: cielo, viento y temperatura |
| `get_medium_term_forecast(id)` | `jsonPredMedioPrazo?dia=-1` | Días 4–7 u 8: 3 cielos con probabilidad, viento, máximas y mínimas con márgenes |
| `get_concello_observation(id)` | `observacionConcellos` | Estado actual del concello: cielo, viento, temperatura y sensación térmica |
| `get_warnings(id)` | `jsonAvisosConcellos?dia=-1` | Avisos de hoy, mañana y pasado ([avisos.md](avisos.md)) |
| `get_station_reading(id)` | `ultimos10minEstacionsMeteo?idEst=` | Última lectura de 10 minutos de una estación ([estaciones.md](estaciones.md)) |
| `get_station_readings()` | `ultimos10minEstacionsMeteo` | Última lectura de las 166 estaciones, en una petición (~320 KB) |
| `get_station_day(id)` | `datosDiariosEstacionsMeteo?idEst=` | Acumulados y extremos de hoy de una estación |
| `get_cameras()` | `jsonCamaras` | Las 33 cámaras con coordenadas, concello y su última foto |
| `get_air_stations()` | `caire/jsonEstacionesCaire` | Estaciones de la Rede de Calidade do Aire: coordenadas, concello, tipo (tráfico, industrial, fondo) ([calidad-aire.md](calidad-aire.md)) |
| `get_air_indexes()` | `caire/jsonICAActual` | ICA actual de todas las estaciones, en una petición |
| `get_air_measurements(id)` | `caire/jsonDatosActualesEstacion?idEstacion=` | Medidas actuales de una estación de aire (sin las marcadas como desactivadas o en mantenimiento) |
| `get_air_forecast(id)` | `caire/jsonPrediccionIcaDiarioConcello?idConcello=` | ICA previsto de hoy y dos días más para un concello |

## MeteoSIX (`MeteoSixClient`, con clave)

Base `https://servizos.meteogalicia.gal/apiv5`. Detalle de uso en [weather.md](weather.md).

| Método | Servicio | Devuelve |
|---|---|---|
| `get_forecast(points)` | `getNumericForecastInfo` | Previsión por horas de hasta 20 puntos (`MAX_POINTS`) en una petición: cielo, temperatura, lluvia, viento, humedad, nubosidad, presión y cota de nieve |
| `check_key()` | `getNumericForecastInfo` mínima: un punto, una variable, una hora | Nada si la clave vale; si no, `MeteoSixAuthError` |

MeteoSIX responde con HTTP 200 también cuando hay error, con un código en el cuerpo: `005` y `006` son clave inválida (`MeteoSixAuthError`); `216` y `217`, sin datos para ese punto; `318`, fin del periodo en el pasado. La clave nunca aparece en mensajes de error ni en registros.

## Radar (`RadarClient`, sin clave)

WMS del servidor THREDDS, producto PPI (`https://thredds.meteogalicia.gal/thredds/wms/observacion/RADAR/PPI`). Detalle en [radar.md](radar.md).

| Método | Petición | Devuelve |
|---|---|---|
| `get_times(day)` | `GetMetadata&item=timesteps` | Pasadas de un día UTC. Si el fichero del día aún no existe, el servidor da 500 |
| `get_frame(time, bbox, width, height)` | `GetMap` | PNG en grises (10–70 dBZ) con transparencia, del recuadro pedido |

## Calidad del aire, modelo CHIMERE (`ChimereClient`, sin clave)

THREDDS de MeteoGalicia, `chimere_2d_gal`: una pasada al día con el ICA de cada hora (~76 h) en una malla de ~7 km.

| Método | Petición | Devuelve |
|---|---|---|
| `get_latest_run()` | Catálogo de `chimere_2d_gal/fmrc/files` | Ruta del último fichero (el nombre lleva la fecha) |
| `get_point(run, lat, lon)` | NCSS en CSV, `var=ica`, todas las horas | ICA de cada hora en el punto de malla más cercano |

## Criterios

- Códigos de cielo y viento tal cual: traducirlos a HA es cosa de la integración (`codes.py`).
- `-9999` («no disponible») → `None`. En medio plazo, un cielo sin dato se omite.
- Fechas de los servicios públicos en hora local de Galicia (`Europe/Madrid`); las de las estaciones, en UTC. Todas salen con zona.
- Medidas de estación: solo las de código de validación 0, 1 o 5.
- Errores: `MeteoGalConnectionError` (red, tiempo de espera), `MeteoGalResponseError` (HTTP distinto de 200, no es JSON o formato inesperado), `MeteoGalNotFoundError` (concello inexistente: `predConcello: null` o `idConcello: 0`), `MeteoSixAuthError` (clave rechazada). Todos heredan de `MeteoGalError`.

## Validación con la API real (2026-09-26)

24 concellos, 6 por provincia: sin errores ni valores `None`.

- Horaria: **96 horas** (días 0–3 completos). El alcance depende de la hora de la consulta y de la pasada del modelo: el 2026-09-25 eran ~74.
- Medio plazo: días **4–7**; algún día, 4–8. Con el corto plazo salen **8 días**, a veces 9.

## Nombres de concello

MeteoGalicia usa dos formatos: la lista de concellos pone el artículo al final («Coruña (A)») y la de estaciones, delante y en mayúsculas («A CORUÑA»). Además, 54 de sus 313 nombres tienen errores: mayúsculas indebidas («Santiago De Compostela»), una errata («Pontes De Garcáa Rodríguez (As)»), un artículo que falta («Pobra Do Caramiñal») y los 12 cambios del Nomenclátor de 2026 sin aplicar.

Regla: **nunca mostrar un nombre de concello que venga de la API**. Todo va por código INE y el nombre sale de `toponyms.py` (Nomenclátor de Galicia 2026). Ver [toponimos.md](toponimos.md).

## Pendiente de validar

- Cambio de hora (2026-10-25): cómo vienen las horas repetidas de 02:00 a 03:00 en la previsión horaria. Hoy se toma la primera.
