# Radar

Fecha: 2026-09-27. Radar de MeteoGalicia por ubicación, sin clave.

## Fuente

THREDDS de MeteoGalicia, WMS del producto PPI (`observacion/RADAR/PPI/PPI_AAAAMMDD_10m.nc`): un fichero por día UTC, una pasada cada 10 min (00:05Z…), publicada con 10–15 min de retraso. Licencia CC BY-SA 4.0.

- `GetMetadata&item=timesteps&day=…`: pasadas del día (~2 KB). Si el fichero del día aún no existe (justo después de medianoche UTC), el servidor responde **500**: se sigue con las de ayer.
- `GetMap`: cada pasada ya reproyectada a lat/lon, en **grises** (`seq-GreysRev`, 250 bandas, `colorscalerange=10,70` dBZ, lo de debajo transparente). Comprobado: 26,25 dBZ exactos → gris 68 → 26,0 dBZ.

## Entidades por ubicación

| Entidad | Contenido | Por defecto |
|---|---|---|
| `image.<ubicación>_radar` | WEBP animado de las últimas horas (2 h: 13 fotogramas, ~400–500 KB) | Activada |
| `image.<ubicación>_radar_ultima_pasada` | PNG con la última pasada | Desactivada |

El estado es la **hora de la última pasada**: cambia solo cuando hay imagen nueva, y así la tarjeta la vuelve a pedir. La tarjeta estándar `picture-entity` la muestra y la anima, sin tarjeta propia (como ha-radarcat). Mismo dispositivo que la entidad del tiempo.

## Opciones (entrada MeteoGal → Configurar)

| Opción | Valores | Por defecto |
|---|---|---|
| Periodo | 1 h y 2 h (una pasada cada 10 min), 3 h (cada 20), 6 h (cada 30): siempre ~7–19 fotogramas | 2 h |
| Encuadre | 50 km o 100 km alrededor de cada ubicación, o toda Galicia | 100 km |

Con 25 km se ven los cuadros de 1 km y no da tiempo a ver llegar la lluvia; 12 h o más pesarían varios MB (para eso haría falta una tarjeta con línea de tiempo).

## Cómo se dibuja (`radar.py`, sin nada de HA)

Capas, de abajo arriba:

1. Fondo neutro (mar y fuera de Galicia, sin distinguir: no hay contorno de Portugal) y concellos de Galicia y municipios limítrofes en color tierra (contornos del IGN que ya lleva MeteoGal).
2. Radar con **nuestra escala** al ~70 % de opacidad: desde 20 dBZ **débil**, 28 **moderada**, 35 **fuerte**, 42 **muy fuerte**, 48 **intensa** y 54 **torrencial** (≈ 0,6 / 1,9 / 5,6 / 15 / 37 / 87 mm/h con Marshall-Palmer). Por debajo de 20 dBZ no se pinta (ecos débiles y ruido).
3. Contornos de los concellos **encima del radar**, para que con lluvia en todas partes se siga viendo el mapa.
4. Ubicación (punto blanco con borde negro) y el resto de ubicaciones configuradas (círculo pequeño).
5. Franja inferior con la hora local y la leyenda en el idioma de HA (gl, es o en), y la atribución "MeteoGalicia · CC BY-SA 4.0".

Fuente: DejaVu Sans reducida a latín (21 KB; `scripts/generate_font.py`), porque la de Pillow no tiene tildes.

## Actualización

Cada 5 min se mira la lista de pasadas. Si hay una nueva, se piden solo las que faltan (las demás quedan guardadas, ~20–40 KB cada una en grises) y se rehacen las imágenes en el executor. Si el THREDDS falla, las imágenes quedan no disponibles y el resto de MeteoGal sigue igual.

## Pendiente

- Marcar dónde acaba la cobertura del radar (el este de Ourense y Lugo): ahora "sin datos" y "sin lluvia" se ven igual.
- Ajustar la escala con datos de pluviómetros (el orballo puede quedar por debajo de 20 dBZ).
