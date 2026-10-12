# Avisos meteorológicos

Fecha: 2026-09-27. Avisos de MeteoGalicia por concello, sin clave, en cada ubicación. Diseño basado en la revisión de GeoSphere Austria Warnings en el núcleo de HA, en la que los revisores fijaron cómo exponer los avisos ([PR #173563](https://github.com/home-assistant/core/pull/173563) y [PR #178358](https://github.com/home-assistant/core/pull/178358)).

## Fuente

`predicion/adversos/jsonAvisosConcellos.action?idConcello=<INE>&dia=-1`: avisos de hoy, mañana y pasado con nivel (1 amarillo, 2 naranja, 3 rojo), tipo, inicio y fin (hora local). Sin avisos, o con un concello inexistente, listas vacías. Un aviso que apareciera en dos días cuenta una vez (por `id`). Se descarga con el resto de datos públicos, cada 30 minutos; si falla, se mantienen los últimos avisos buenos.

Tipos (anexo II): `high_temperature`, `low_temperature`, `rain_1h`, `rain_12h`, `fog`, `snow`, `thunderstorm`, `wind_gust`, `wind_at_sea` (9, "Vento no mar") y `waves` (10, "Ondas"). Los dos últimos son avisos de mar que MeteoGalicia asigna también a los concellos de la costa (documentado, sin comprobar en vivo porque no había ninguno activo).

## Entidades por ubicación

| Entidad | Estado | Notas |
|---|---|---|
| Nivel de aviso | enum `none`/`yellow`/`orange`/`red`, el más alto de los **vigentes ahora** | Atributos del aviso principal: `type`, `level`, `start`, `end`, `warning_id`, `description` (comentario de MeteoGalicia) y `zone` (su zona) |
| Nivel de aviso próximo | Ídem, de los **emitidos que aún no han empezado** (hasta pasado mañana, sin ventana inventada) | Ídem |
| Avisos vigentes / próximos | Número | Desactivados por defecto |

- **Aviso principal:** el de nivel más alto; a igual nivel, el que acaba antes, luego el que empieza antes y por último el `id`, para que el orden no cambie entre actualizaciones.
- **Atributos fuera del recorder** (`_unrecorded_attributes`), para no llenar la base de datos.
- **Cambio de estado exacto:** cada entidad programa el siguiente inicio o fin de un aviso y se actualiza en ese momento, sin pedir datos.
- Valores de `type` y `level` como slugs estables, no textos. Los atributos tienen traducción (`state_attributes` en las traducciones): en **⋮ → Atributos** se ve «Tipo: Racha máxima de viento», «Nivel: Amarillo», «Inicio», «Fin».

## Comentario de cada aviso

`jsonAvisosConcellos` no trae el texto del aviso. Lo tiene el RSS de avisos (`predicion/rssAdversos.action?request_locale=gl|es`), pero **por zonas**: cada tipo de aviso lleva zonas y, en cada una, tramos con inicio, fin, nivel y comentario. Las zonas (documento «Definición de zonas de adverso meteorolóxico» de MeteoGalicia) son el concello, una de las **16 agrupaciones** («Noroeste de A Coruña»…), la provincia, toda Galicia y zonas de mar.

- `data/zonas_avisos.json`: por código INE, la zona del concello y la de su agrupación (`scripts/generate_warning_zones.py`, que comprueba que salen los 313 y que cada agrupación tiene los concellos que dice el documento). La provincia sale del código INE y Galicia es la 320.
- A cada aviso del concello se le une el tramo del **mismo tipo, nivel, inicio y fin** de una zona que incluya al concello; si hay varios, el de la zona más concreta. Los avisos de mar (viento en el mar y olas) van en zonas marítimo-costeras, que no están en la tabla: valen si todos los tramos iguales dicen lo mismo.
- Sin tramo, el aviso queda sin comentario (por ejemplo, uno que ya terminó: el RSS solo trae los vigentes y próximos).
- En gallego o en castellano según el idioma de HA; en inglés, en castellano (MeteoGalicia no lo publica en inglés).
- Una petición más cada 30 minutos por ubicación (~13 KB). Si falla, se usan los últimos comentarios buenos; los avisos no dependen de ella.

Ejemplo real (2026-09-29): en A Coruña, «Racha máxima de viento» amarilla de 09:00 a 21:00 → «Rachas superando los 80 km/h.» (zona «A Coruña (provincia)»). En Cee, la lluvia en 1 hora amarilla y naranja a la misma hora salen de la provincia («más de 15 l/m2») y de «Oeste de A Coruña» («más de 30 litros/m2»).

## Acción `meteogal.get_warnings`

Sobre un sensor de nivel de aviso (solo acepta los enum de MeteoGal). Devuelve todos los avisos de la ubicación, vigentes primero y después los próximos, cada grupo ordenado como arriba:

```yaml
action: meteogal.get_warnings
target:
  entity_id: sensor.a_coruna_nivel_de_aviso
response_variable: avisos
```

```json
{"sensor.a_coruna_nivel_de_aviso": {"warnings": [
  {"type": "wind_gust", "level": "yellow", "start": "2026-09-29T09:00:00+02:00",
   "end": "2026-09-29T21:00:00+02:00", "warning_id": 1077489894,
   "description": "Rachas superando los 80 km/h.", "zone": "A Coruña (provincia)",
   "active": true}
]}}
```

## Qué no se hizo (y por qué)

- **Atributos numerados** (`warning_1_*`, como DWD): los índices cambian cuando acaba un aviso y una plantilla lee otro sin dar error. Los revisores de HA lo rechazan.
- **Toda la lista en atributos**: se guarda en la base de datos en cada cambio y puede pasar de 16 KB. Para eso está la acción.
- **Nivel por día** (hoy, mañana, pasado): MeteoGalicia lo da así, pero el patrón de HA es vigentes y próximos. El detalle por día sale de la acción.

## Pendiente

- Avisos por zona marítima, para quien navega o pesca.
- Adaptador `meteogal` para `weather_alerts_card`.
