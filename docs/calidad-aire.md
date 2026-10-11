# Calidad del aire

Fecha: 2026-09-29. Calidad del aire de MeteoGalicia en cada ubicación, sin clave. Uso para el usuario en el README (sección «Calidad del aire»).

## Fuentes (sin clave, CC BY-SA 4.0)

| Fuente | Qué da | Cada cuánto |
|---|---|---|
| `caire/jsonICAActual.action` | ICA actual de todas las estaciones de la Rede de Calidade do Aire, en una petición: número, nivel (en es, gl y en), contaminante que manda y hora local | Cada 30 min (las estaciones publican cada hora) |
| `caire/jsonDatosActualesEstacion.action?idEstacion=` | Medidas actuales de la estación elegida, con marca: `T` temporal, `D` canal desactivado, `M` mantenimiento (estas dos se descartan) | Cada 30 min |
| `caire/jsonEstacionesCaire.action` | Estaciones: nombre, coordenadas, **tipo** (tráfico, industrial, fondo) | Al configurar y una vez al arrancar |
| `caire/jsonPrediccionIcaDiarioConcello.action?idConcello=` | ICA previsto de hoy y los días siguientes para el concello (3 o 4 días en total), con el contaminante que manda y la hora del peor momento | Cada hora |
| THREDDS, `chimere_2d_gal` (modelo CHIMERE) | ICA de cada hora (~76 h) en una malla de ~7 km; se consulta en el punto de cada ubicación con NCSS | Cada hora se mira si hay pasada nueva (una al día, 00 UTC) y solo entonces se piden los puntos |

Documentación oficial: IT/052 «JSON» de MeteoGalicia (2021). Conjuntos 0055 (calidad del aire) y 0485 (THREDDS) de abertos.xunta.gal.

## Niveles

El ICA es un número de 0 a 6: 0–1 `good`, 1–2 `fair`, 2–3 `moderate`, 3–4 `poor`, 4–5 `very_poor`, 5–6 `extremely_poor` (los niveles del índice europeo de la EEA, que sigue el ICA español). `-1` es «sin datos».

- **Estación:** el nivel que da MeteoGalicia (`icaEn`), porque el número llega redondeado: el mismo 2,0 sale unas veces «Fair» y otras «Moderate» (visto el 2026-09-29). Si el texto no es uno conocido, del número.
- **Modelo y predicción:** del número (no traen texto).
- Textos propios en gl, es y en. En castellano, los de MeteoGalicia para los tres primeros (Buena, Adecuada, Moderada) y los del ICA de MITECO para los otros tres, que MeteoGalicia no mostraba ese día (Desfavorable, Muy desfavorable, Extremadamente desfavorable). En gallego, los de MeteoGalicia (Boa, Favorable, Regular…).

## Entidades por ubicación

| Entidad | Estado | Por defecto |
|---|---|---|
| `sensor.<ubicación>_calidad_del_aire` | `enum` con los seis niveles. Atributos: `source` (`station`, `forecast` o `model`) y `main_pollutant` (`no2`, `o3`, `pm25`, `pm10`, `so2`; sin él con el modelo) | Activada |
| `sensor.<ubicación>_indice_de_calidad_del_aire` | El número (clase `aqi`) | Desactivada |
| Con estación de aire: PM2,5, PM10, NO₂, O₃ | µg/m³, con la clase de dispositivo de cada contaminante (así valen los disparadores y condiciones de calidad del aire de HA) | Activadas |
| Con estación de aire: SO₂, CO (mg/m³), NO | Ídem | Desactivadas |
| Con estación de aire: «Estación de aire: última medida» | Hora de la última medida; atributos `station_id`, `station_name`, `station_type` (`traffic`, `industrial`, `background`) y `distance` (km) | Activada (diagnóstico) |

Solo se crean los contaminantes que mide la estación. Medidas de más de 3 horas: «Desconocido».

## De dónde sale el nivel actual

Como la entidad del tiempo, **lo medido primero**:

1. **Estación de aire**, si la ubicación la tiene, la usa (**Usar la estación para la calidad del aire actual**) y su dato tiene menos de 3 horas.
2. **Predicción del día** para el concello (el nivel más alto que se espera hoy).
3. **Modelo CHIMERE** en el punto de la ubicación, a la hora en curso.

El modelo va el último porque, validado con 2 semanas de estaciones (`docs/analysis/validacion-chimere.md` del workspace, 2026-09-29 a 10-11), da el mismo nivel que la estación en el 49 % de las horas (más alto en el 46 %) y casi igual en todas partes (1,3–1,5 de media, cuando lo medido va de 0,15 a 1,74); la predicción del concello acierta el nivel en el 65–67 % (hoy y los tres días siguientes), con un sesgo de +0,2, porque el máximo del día es más fácil de acertar que cada hora. La contrapartida es que el nivel no cambia a lo largo del día. Si no hay ninguno, la entidad queda no disponible. Se recalcula en cada cambio de hora.

**Del modelo solo se usa el nivel**, no las concentraciones: el 2026-09-29 a las 07:00Z acertaba el nivel en A Coruña («Adecuada») pero daba PM2,5 1,3 µg/m³ frente a los 10 medidos en Torre Hércules. Validado: NO₂ y O₃ siguen algo el ciclo del día (correlación ~0,5, el O₃ con +12 µg/m³ de sesgo); PM2,5, PM10 y SO₂ no (correlación 0–0,2, y las PM10 la mitad de lo medido).

## Configuración

En la confirmación de cada ubicación:

- **Estación de calidad del aire:** de la más cercana a la más lejana, con concello, distancia, tipo y «sin datos ahora» si no tiene ICA. Solo las que calculan el ICA (las de un solo contaminante de la industria, no). Por defecto, **la más cercana con datos si está a menos de 10 km**; si no, ninguna: de mediana, la más cercana está a 17 km del concello (hasta 56 km) y la predicción del concello y el modelo cubren la ubicación.
- **Usar la estación para la calidad del aire actual** (por defecto sí). Una de tráfico o industrial mide la calle o la fábrica, no el barrio: desmarcándolo, sus sensores siguen y el nivel sale de la predicción del concello.

Ubicaciones configuradas antes de la calidad del aire: sin estación de aire, con el nivel de la predicción del concello; al reconfigurarlas se propone como en una nueva.

## Acción `meteogal.get_air_quality`

Sobre el sensor de calidad del aire. Devuelve el dato actual, cada hora del modelo desde la en curso y cada día previsto para el concello:

```yaml
action: meteogal.get_air_quality
target:
  entity_id: sensor.a_coruna_calidad_del_aire
response_variable: aire
```

```json
{"sensor.a_coruna_calidad_del_aire": {
  "now": {"level": "fair", "index": 1.8, "main_pollutant": "pm10", "source": "station"},
  "hourly": [{"datetime": "2026-09-29T08:00:00+02:00", "level": "fair", "index": 1.5}],
  "daily": [{"date": "2026-09-29", "level": "fair", "index": 1.8,
             "main_pollutant": "o3", "peak": "2026-09-29T21:00:00+02:00"}]
}}
```

Sin sensores por día ni por hora, como con el tiempo (`weather.get_forecasts`) y como la acción `get_forecast` de Google Air Quality en el núcleo.

## Otras fuentes revisadas

La única red pública y abierta en Galicia es la de la Xunta (la que republican WAQI, IQAir, la EEA y MITECO). La red municipal de A Coruña tiene API, pero pide credenciales; Sensor.Community no tiene sensores en Galicia.

## Pendiente

- Repetir la validación con un mes y en invierno (menos ozono, más partículas).
- Confirmar los textos de MeteoGalicia de los niveles 4–6 cuando aparezcan.
- Aviso de reparación si la estación de aire deja de enviar, como con la meteorológica.
