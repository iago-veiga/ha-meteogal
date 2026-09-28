# Entidad del tiempo

Fecha: 2026-09-27. Una entidad `weather` por ubicación. Sin clave, con los servicios públicos; con clave de MeteoSIX, más detalle ([sección propia](#con-clave-de-meteosix)).

## Qué muestra

| Dato | Fuente | Detalle |
|---|---|---|
| Estado actual (cielo, temperatura, sensación térmica, rumbo del viento) | `observacionConcellos` | Si no hay observación, cielo, temperatura y viento salen de la previsión de la hora en curso |
| Previsión diaria | `jsonPredConcellos` (días 0-3) + `jsonPredMedioPrazo` (4-7 u 8) | 8 o 9 días |
| Previsión horaria | `jsonPredHorariaConcellos` | Desde la hora en curso hasta el final del día 3 |

Se actualiza cada 30 minutos. Si falla la previsión diaria u horaria, la entidad queda no disponible; si falla solo el medio plazo o la observación, se mantiene el último dato bueno.

## Traducción de códigos

Tabla oficial: anexos II y III de `JSON_Pred_Concello`, en `codes.py`. Decisiones:

- **Día y noche:** los códigos 1xx son de día y los 2xx de noche. "Despejado" de noche es `clear-night`; el resto de estados es igual de día y de noche.
- **Nublado 75 % (x04)** → `cloudy`, no `partlycloudy`.
- **Calima (x24)** → `fog`: HA no tiene un estado para polvo en suspensión, y lo que se nota es la visibilidad.
- **Tormenta (x13)** → `lightning-rainy`; **tormenta con pocas nubes (x19)** → `lightning`.

## Decisiones de la previsión

- **Probabilidad de lluvia diaria (días 0-3):** la máxima de las tres franjas.
- **Medio plazo:** trae tres cielos con su probabilidad. La condición es la del más probable (si empatan, el primero de la lista, que suele ser el más despejado) y la probabilidad de lluvia es la suma de las probabilidades de los cielos con precipitación.
- **Viento:** solo el rumbo. MeteoGalicia da tramos (flojo 5-20 km/h, moderado 20-40…), no una velocidad, así que no se inventa un número. En la previsión diaria, el rumbo de la franja con más viento; si empatan, la que tiene rumbo (el variable cuenta como flojo pero no tiene dirección) y después tarde, mañana y noche. Calma y variable no tienen rumbo.
- **UV:** el máximo del día, solo en la previsión diaria.

## Con estación

Si la ubicación tiene estación y **Usar la estación para el tiempo actual**, el estado actual toma primero lo medido en ella (temperatura, humedad, presión, punto de rocío, rachas y viento). Orden completo en el README y detalle en [estaciones.md](estaciones.md).

## Con clave de MeteoSIX

La clave suma, no sustituye: las mismas entidades y `unique_id`, solo se rellenan más campos. Si MeteoSIX falla o sus datos se quedan viejos, todo sale de la previsión pública.

| Dato | Con clave |
|---|---|
| Estado actual: cielo y temperatura | Igual que sin clave (lo medido en el concello) |
| Estado actual: humedad, presión, nubosidad | Hora de MeteoSIX más cercana a ahora (a menos de una hora) |
| Estado actual: viento | Velocidad **y** rumbo de MeteoSIX, para no mezclar fuentes en el mismo dato |
| Previsión por horas | Entera de MeteoSIX desde su primera hora útil; antes (a veces la hora en curso), de la pública. Hasta una hora antes del final de MeteoSIX (ver abajo): hoy, el día +4 a la 01:00 |
| Previsión diaria | Igual que sin clave, y en los días que MeteoSIX cubre enteros (hoy desde la hora en curso, y hasta el día +3) se añaden la **lluvia total** (mm) y el **viento máximo** con el rumbo de esa misma hora |

**Cielo, lluvia y nubosidad van con la hora que empieza.** En MeteoSIX, la lluvia de cada hora es la acumulada en la hora anterior, y el estado del cielo y la nubosidad también describen esa hora:

- Cielo y lluvia: en 522 horas de 6 concellos (captura del 2026-09-27) coinciden siempre en la misma marca de tiempo (nunca cielo seco con lluvia ni cielo de lluvia sin ella); con la hora siguiente, solo en el 89 %.
- Cielo y nubosidad (unas 850 horas, dos capturas): en la misma marca, "despejado" tiene un 6 % de nubosidad media y "cubierto" un 91 %, y ningún despejado llega al 50 %; con la hora anterior, 12 %, 67 % y 4 despejados por encima del 50 %. Visto en el HA real: sin correrla salía "soleado" con un 50 % de nubes.

Home Assistant (como met.no) espera en cada hora lo de la hora que empieza, así que en la hora H el cielo, la lluvia y la nubosidad salen del dato de H+1 y el resto (temperatura, viento, humedad, presión, instantáneos) del de H. La última hora de MeteoSIX se descarta porque no tiene cielo ni lluvia. En el estado actual, la nubosidad es la de la hora más cercana (la hora que acaba de pasar, como mucho).

**Lluvia y viento del día.** La lluvia es la suma de las horas del día con el mismo desplazamiento que la previsión por horas (de 00:00 a 24:00; hoy, desde la hora en curso, como hace met.no). Solo si están todas: un día a medias (el +4) no se completa. Las horas se cuentan en tiempo real, así que el día del cambio de hora suma 23 o 25. El viento es la velocidad máxima prevista (no son rachas: MeteoSIX no las da) con el rumbo de esa misma hora. Cielo, máxima y mínima, probabilidad de lluvia y UV siguen siendo los de la previsión pública, aunque a veces no cuadren con los mm (por ejemplo, 55 % de probabilidad y 0,0 mm): son dos predicciones distintas y no se corrigen entre sí.

**Hasta dónde llega MeteoSIX.** El modelo de 1 km sale de la pasada de las 00:00 UTC (lista hacia las 09:30 hora local) y prevé 96 horas: termina a las 00:00 UTC del día +4, que son las 02:00 en horario de verano y la 01:00 en invierno. Como la última hora se descarta, la previsión por horas acaba a la 01:00 (verano) o a las 00:00 (invierno) del día +4. El día +3 queda completo en los dos casos. Comprobado con las capturas del 2026-09-27 (pasada 00:00Z, última hora 00:00Z del 1 de octubre, 96 h). Antes de que salga la pasada del día (hasta ~09:30), MeteoSIX da la del día anterior y el alcance es un día menos.

**Velocidades con un decimal.** MeteoSIX da dos, que no aportan nada.

**Estados del cielo de MeteoSIX** → los mismos criterios que el código público equivalente (el nombre del icono lo dice: `nubes75` → x04, `cuberto` → x05…), en `codes.py`. Día o noche, del icono (`.../night/...`). `STORM_THEN_CLOUDY` → `lightning`, como "tormenta con pocas nubes".

**Pendiente de validar con más días de capturas:** coherencia entre MeteoSIX y la pública en temperatura y cielo, y si conviene que la condición actual con clave siga siendo la medida.

## Identificadores

- Dispositivo por ubicación: nombre oficial del concello, fabricante "MeteoGalicia", tipo servicio.
- `unique_id` de la entidad: `<id de la subentrada>_weather`. No debe cambiar nunca.
- `entity_id`: sale del nombre del dispositivo, sin prefijo de la integración (`weather.a_coruna`), como recomienda HA. Decidido el 2026-09-27; no cambiar.
- La atribución ("MeteoGalicia · Xunta de Galicia") no se traduce: HA la muestra tal cual.

## Validación con datos reales (2026-09-27)

Seis concellos de las cuatro provincias (Santiago, Vigo, Lugo, Ourense, A Coruña, Ribadeo): 8 días, 67 horas desde la hora en curso, ningún código sin traducir.

## Prueba en un Home Assistant real (2026-09-27)

HA 2026.9.3 (Home Assistant OS), instalado a mano en `custom_components` y configurado desde la interfaz con A Coruña:

- `weather.a_coruna`: nublado, 18,4 °C, igual que la observación publicada por MeteoGalicia.
- 8 días y 65 horas de previsión; ningún error ni aviso en el registro.
- Encontrado y corregido: el rumbo diario salía vacío cuando la tarde tenía viento variable y otra franja viento flojo con dirección.
