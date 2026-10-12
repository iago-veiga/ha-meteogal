# Modelo WRF de 4 km

Fecha: 2026-10-12. Sin clave. Para la racha prevista y como respaldo del viento, la humedad y la presión de la entidad del tiempo ([weather.md](weather.md)).

## Fuente

El **WRF determinista de MeteoGalicia** (`wrf_2d_04km`, nido `d03`) en su servidor THREDDS: de hora en hora, unas 84 horas, **dos pasadas al día (00 y 12 UTC)**. Es el mismo sistema que MeteoSIX, que lo da con la malla de 1 km y con clave. Licencia CC BY-SA 4.0 (conjunto 0485 de abertos.xunta.gal, como el CHIMERE y el radar). 45 variables; MeteoGal pide cinco por punto:

| Variable | Qué es | Llega en | Sale en |
|---|---|---|---|
| `wind_gust` | Racha a 10 m | m/s | km/h |
| `mod` | Viento medio a 10 m | m/s | km/h |
| `dir` | Rumbo del que viene el viento | grados | grados (misma convención que MeteoSIX: la diferencia media es de 20°) |
| `rh` | Humedad relativa a 2 m | fracción 0–1 | % |
| `mslp` | Presión reducida al nivel del mar | Pa | hPa |

Una petición NCSS por ubicación y pasada (`temporal=all`), 0,3 s y unos 10 KB.

## Cómo se usa

- **`WrfCoordinator`** (uno por entrada, como el del CHIMERE): cada hora mira el catálogo y solo pide los puntos si hay pasada nueva. Si una pasada llega a medias (la última hora está a menos de 60 h de su inicio: se estaba escribiendo), se usa lo que hay y se vuelve a pedir la siguiente vez. Si el THREDDS falla, se sigue con la última buena; sin ninguna, el coordinador queda sin datos y MeteoGal funciona como antes.
- **En la entidad del tiempo**: racha en la previsión por horas y por días; racha, viento, humedad y presión en el estado actual y en las horas sin MeteoSIX. Detalle en [weather.md](weather.md#con-el-wrf-de-4-km-sin-clave).
- **La racha nunca queda por debajo del viento medio** de la misma hora: el WRF de 4 km se queda por debajo del viento de MeteoSIX en el 13 % de las horas.
- **No da lluvia ni cielo**: aunque acierta la lluvia tan bien como MeteoSIX, sus horas de lluvia no coinciden con los iconos de la previsión pública (en el 42 % de las horas de lluvia del WRF, el icono no es de lluvia), y MeteoGal no mezcla fuentes en una misma hora.

## A qué hora corresponde cada valor

Con la hora de las estaciones (el final de la hora) y 13 días, la racha casa mejor con la medida de su misma hora (correlación 0,72; con la hora siguiente, 0,71), la radiación con la hora que empieza en ese instante y la lluvia con la que acaba. Por eso la racha, el viento, la humedad y la presión van como **valores instantáneos de la hora de la entrada**, igual que la temperatura y el viento de MeteoSIX.

## Validación (2026-09-28 a 2026-10-10, 6 estaciones)

Previsión de la pasada de las 00 UTC del día anterior (24–47 h de plazo), 1.872 horas-estación:

| | Resultado |
|---|---|
| Racha por hora frente a la racha medida | Prevista 20,2 km/h de media, medida 19,4 (sesgo +0,9 km/h); error medio **8 km/h**; correlación **0,72** |
| Por estación (sesgo / error) | Santiago −0,7 / 7,2; A Coruña −3,6 / 7,9; Vigo −3,6 / 8,6; Lugo +5,4 / 7,9; Ourense +5,8 / 8,6; O Cebreiro +1,8 / 7,9 km/h: **corta en la costa, larga en el interior** |
| Racha máxima del día | Error medio 7,6 km/h, correlación **0,78**; de 9 días con racha de 50 km/h o más, 5 acertados y 1 falso |
| Temperatura, humedad y presión frente a las medidas | Casi igual que MeteoSIX: error de 1,69 °C, 8,7 % y 0,80 hPa (MeteoSIX: 1,62 °C, 8,8 % y 0,79 hPa) |
| Viento medio frente a MeteoSIX | 10,7 frente a 10,5 km/h, error de 3,5 km/h, correlación 0,77 |

Son 13 días de otoño en 6 estaciones; MeteoSIX se consultó en el centro del concello y el WRF en la estación. 

## Límites

- Es una previsión de 4 km: no ve el relieve fino. Las rachas locales fuertes (valles, montaña) se le escapan.
- Dos pasadas al día: entre una y otra, la previsión no cambia. No se ha medido cuánto tarda en publicarse cada pasada; MeteoGal mira el catálogo cada hora.
- El THREDDS cambió de dirección una vez en 15 años; si vuelve a cambiar, el modelo queda sin datos y el resto de MeteoGal sigue (ver el aviso en el README).
