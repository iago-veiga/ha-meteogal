# Seguridad

## Versiones con soporte

Solo la última versión publicada.

## Cómo avisar de un problema de seguridad

Si encuentras algo que pueda comprometer a quien usa MeteoGal (por ejemplo, que la clave de MeteoSIX o las coordenadas de una ubicación acaben en un registro, un diagnóstico o una petición donde no deberían), **no abras una incidencia pública**. Usa el aviso privado de GitHub: pestaña **Security** → **Report a vulnerability**.

Responderé en cuanto pueda y, cuando haya arreglo, lo publicaré en una versión nueva con una nota en el [registro de cambios](CHANGELOG.md).

## Qué guarda MeteoGal

- La **clave de MeteoSIX**, si la pones, en la configuración de Home Assistant, como cualquier integración. No sale en los diagnósticos ni en los mensajes de error.
- Las **coordenadas de tus ubicaciones**, en la misma configuración. No salen en los diagnósticos. Para pedir datos de tu punto se envían, con la precisión que cada servicio pide, a servidores de MeteoGalicia (el modelo WRF, el modelo de calidad del aire y el radar, y MeteoSIX solo si pones clave); el detalle está en [Privacidad](README.md#privacidad).
