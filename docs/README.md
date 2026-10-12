# Documentación

Si buscas **cómo usar MeteoGal**, lo tienes todo en el [README](../README.md): instalación, configuración, todas las opciones, las entidades y ejemplos. Para empezar con un panel entero: [panel de ejemplo](panel.md).

Esta carpeta es la documentación **técnica**: cómo funciona cada parte, con las decisiones tomadas y los datos reales con que se validaron. Sirve para entender por qué MeteoGal se comporta como lo hace, o para colaborar.

| Documento | Qué cuenta |
|---|---|
| [Diseño](diseno.md) | Principios, estructura del código y decisiones |
| [El tiempo](weather.md) | La entidad `weather`: de dónde sale cada dato, con y sin clave de MeteoSIX, y con el modelo WRF |
| [Modelo WRF](wrf.md) | Racha prevista y respaldo de viento, humedad y presión: fuente, validación y límites |
| [Avisos](avisos.md) | Avisos por concello, su comentario y la acción `meteogal.get_warnings` |
| [Radar](radar.md) | De dónde sale, cómo se dibuja, la zona lejana y el umbral validado |
| [Estación y cámara](estaciones.md) | Sensores de estación, el día local frente al día UTC y la reparación |
| [Calidad del aire](calidad-aire.md) | Estaciones, predicción y modelo, con su validación |
| [Servicios de MeteoGalicia](api.md) | Los clientes de la API y lo que devuelve cada servicio |
| [Concello a partir de coordenadas](concello-por-coordenadas.md) | Cómo se deduce el concello de un punto |
| [Nombres de concello](toponimos.md) | Por qué se usan los nombres oficiales |

Otros ficheros del repositorio: [CHANGELOG](../CHANGELOG.md), [CONTRIBUTING](../CONTRIBUTING.md), [SECURITY](../SECURITY.md) y [NOTICE](../NOTICE) (licencias de los datos).
