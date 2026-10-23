# Cambios

Todos los cambios importantes de MeteoGal. Las versiones se numeran por año y mes de publicación (`2026.10.0` es la primera de octubre de 2026). Cada versión está en la página de [versiones](https://github.com/iago-veiga/ha-meteogal/releases).

## Sin publicar

### Cambios

- **Calidad del aire:** los seis niveles usan ahora los nombres oficiales del Índice Nacional de Calidad del Aire (MITECO): buena, razonablemente buena (antes «adecuada»), regular (antes «moderada»), desfavorable, muy desfavorable y extremadamente desfavorable. El estado interno (`good`, `fair`, `moderate`…) no cambia.

## 2026.10.0

### Novedades

- **Calidad del aire.** Un sensor con el nivel (buena, adecuada, moderada, desfavorable, muy desfavorable, extremadamente desfavorable) y otro, desactivado, con el índice de 0 a 6. Sale de la **estación de calidad del aire** de la Xunta si eliges una (por defecto, la más cercana si está a menos de 10 km), y si no, de la predicción del día de tu concello; el modelo CHIMERE queda de último recurso. Con estación, además, sensores de PM2,5, PM10, dióxido de nitrógeno y ozono (y, desactivados, dióxido de azufre, monóxido de carbono y monóxido de nitrógeno), que valen para los disparadores y condiciones de calidad del aire de Home Assistant. Nueva acción `meteogal.get_air_quality` con el nivel de cada hora y de cada día. Si la estación de aire deja de enviar durante más de un día, Home Assistant lo avisa en Reparaciones y te deja elegir otra. [Detalle](README.md#calidad-del-aire).
- **Rachas de viento previstas.** La previsión por horas y por días de la entidad del tiempo incluye ahora la racha (`wind_gust_speed`), con el modelo WRF de 4 km de MeteoGalicia, sin clave. El estado actual la usa si no hay estación. Sin clave de MeteoSIX, la previsión por horas gana además velocidad del viento, humedad y presión. [Detalle](docs/wrf.md).
- **Avisos con el comentario de MeteoGalicia.** Cada aviso lleva su descripción («Rachas superando los 80 km/h») y su zona, en gallego o castellano según el idioma de Home Assistant, en los sensores de nivel y en la acción `meteogal.get_warnings`.
- **Estaciones en el mapa.** Las entidades de la estación meteorológica y de la de aire llevan `latitude` y `longitude`, así que valen en una tarjeta de mapa. No se guardan en el historial.
- **El radar marca lo que ve peor.** A más de 100 km del radar (el este de Ourense y de Lugo) la imagen sale rayada, con un círculo discontinuo en el límite y una línea en la leyenda: ahí se le escapa en torno a una de cada tres lluvias moderadas. Validado con 154 pluviómetros durante 41 días; el umbral de 20 dBZ se mantiene. [Detalle](docs/radar.md).

### Cambios

- **Los sensores «de hoy» de la estación van por tu día, no por el UTC.** MeteoGalicia cierra el día de las estaciones en hora UTC: «Lluvia hoy» quedaba en «Desconocido» de 00:00 a ~02:30 y la lluvia de esas horas se contaba para el día anterior. Ahora la lluvia, la máxima y la mínima de hoy empiezan a medianoche. Justo después de medianoche la lluvia de hoy es 0 y la máxima y la mínima esperan a que acabe la primera hora; el viento máximo sigue siendo el del día UTC. [Detalle](docs/estaciones.md).
- **La previsión pública de la calidad del aire da 3 o 4 días**, no solo hoy.
- El manifiesto ya no declara Pillow, que Home Assistant trae de serie (la validación de hassfest lo rechaza).

### Si actualizas

- No hace falta hacer nada: las entidades y automatizaciones que ya tienes siguen igual. La calidad del aire aparece sola; si quieres sus sensores de contaminantes, reconfigura la ubicación (**Cambiar ubicación**) y elige una estación de aire.
- Los sensores de la estación de «hoy» que tenías desactivados siguen desactivados; actívalos en Ajustes → Entidades si los quieres.

## 2026.9.0

Primera versión pública.

- Entidad del tiempo por concello, con previsión diaria de 8 o 9 días y por horas, con la previsión oficial de MeteoGalicia, sin clave.
- Con clave opcional de MeteoSIX: lluvia, viento, humedad, nubosidad y presión por horas; sensores «Lluvia esta hora», «Próxima lluvia» y «Cota de nieve».
- Avisos meteorológicos por concello (nivel vigente y próximo, acción `meteogal.get_warnings`).
- Radar animado de MeteoGalicia por ubicación, con escala, mapa y leyenda propios.
- Estación meteorológica de cada ubicación, con sus sensores, y cámara de MeteoGalicia opcional.
- Configuración desde el mapa: el concello, la estación y la cámara se deducen de las coordenadas. Varias ubicaciones por entrada.
- Textos en gallego, castellano e inglés; nombres oficiales de los concellos; diagnósticos y reparaciones.
