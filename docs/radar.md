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

## Cobertura y umbral (validado con pluviómetros)

Comprobado el 2026-10-11 con las 154 estaciones de MeteoGalicia durante 41 días (2026-09-01 a 10-11; 148.784 horas, 7.260 con lluvia): la reflectividad máxima de las pasadas de cada hora, en el punto de la estación, frente a la lluvia medida esa hora .

- **El fichero no distingue «sin lluvia» de «sin cobertura»**: ambos son `NaN`. Casi toda la rejilla de 390 km (toda Galicia) da algún valor en algún momento, así que no hay un contorno de cobertura que sacar de los datos. Lo que cambia con la distancia es cuánta lluvia ve.
- **Alcance:** de la lluvia de **≥1 mm/h** con 20 dBZ, el radar detecta el 91 % a menos de 50 km de Xesteiras, el 84–87 % de 50 a 100 km, el **71 % de 100 a 120 km y el 58–64 % de 120 a 150 km**. Por eso la imagen marca como «ve peor la lluvia» lo que queda a más de **100 km**: rayas diagonales tenues sobre el radar, círculo discontinuo y una línea más en la leyenda (solo si la imagen llega a esa zona). La posición del radar es la de la estación de Xesteiras (Cuntis); no está confirmada en el fichero.
- **Umbral de 20 dBZ:** se mantiene. Con 20 dBZ, de lo que dice «lluvia» llueve de verdad el 83 % de las horas, y solo da lluvia en el 0,5 % de las horas secas; bajarlo a 12 dBZ pasa del 43 % al 55 % de las horas de lluvia detectadas, pero más que duplica las falsas alarmas en seco (de 0,5 % a 1,2 %) y baja la precisión al 71 %. De la lluvia **débil (0,1–0,5 mm/h, el orballo)** detecta el 19 % con 20 dBZ y el 42 % ni con 5 dBZ: el radar no la ve y no hay umbral que lo arregle.
- **Ecos falsos fijos:** hay estaciones con más lluvia de radar en seco (1–1,5 % de las horas secas a 20 dBZ: Aldea Nova, Burela, Lourenzá, Punta Candieira, Serra do Eixe…), todas del norte y a 105–156 km. Parece ruido de la lejanía, no ecos fijos de terreno; sin tratar.

## Pendiente

- Repetir con más meses (en invierno la lluvia es más frontal y la nieve cambia la reflectividad).
- Comprobar la posición real del radar.
