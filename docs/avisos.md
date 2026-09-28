# Avisos meteorológicos

Fecha: 2026-09-27. Avisos de MeteoGalicia por concello, sin clave, en cada ubicación. Diseño basado en la revisión de GeoSphere Austria Warnings en el núcleo de HA, en la que los revisores fijaron cómo exponer los avisos ([PR #173563](https://github.com/home-assistant/core/pull/173563) y [PR #178358](https://github.com/home-assistant/core/pull/178358)).

## Fuente

`predicion/adversos/jsonAvisosConcellos.action?idConcello=<INE>&dia=-1`: avisos de hoy, mañana y pasado con nivel (1 amarillo, 2 naranja, 3 rojo), tipo, inicio y fin (hora local). Sin avisos, o con un concello inexistente, listas vacías. Un aviso que apareciera en dos días cuenta una vez (por `id`). Se descarga con el resto de datos públicos, cada 30 minutos; si falla, se mantienen los últimos avisos buenos.

Tipos (anexo II): `high_temperature`, `low_temperature`, `rain_1h`, `rain_12h`, `fog`, `snow`, `thunderstorm`, `wind_gust`, `wind_at_sea` (9, "Vento no mar") y `waves` (10, "Ondas"). Los dos últimos son avisos de mar que MeteoGalicia asigna también a los concellos de la costa (documentado, sin comprobar en vivo porque no había ninguno activo).

## Entidades por ubicación

| Entidad | Estado | Notas |
|---|---|---|
| Nivel de aviso | enum `none`/`yellow`/`orange`/`red`, el más alto de los **vigentes ahora** | Atributos del aviso principal: `type`, `level`, `start`, `end`, `warning_id` |
| Nivel de aviso próximo | Ídem, de los **emitidos que aún no han empezado** (hasta pasado mañana, sin ventana inventada) | Ídem |
| Avisos vigentes / próximos | Número | Desactivados por defecto |

- **Aviso principal:** el de nivel más alto; a igual nivel, el que acaba antes, luego el que empieza antes y por último el `id`, para que el orden no cambie entre actualizaciones.
- **Atributos fuera del recorder** (`_unrecorded_attributes`), para no llenar la base de datos.
- **Cambio de estado exacto:** cada entidad programa el siguiente inicio o fin de un aviso y se actualiza en ese momento, sin pedir datos.
- Valores de `type` y `level` como slugs estables, no textos. Los atributos tienen traducción (`state_attributes` en las traducciones): en **⋮ → Atributos** se ve «Tipo: Racha máxima de viento», «Nivel: Amarillo», «Inicio», «Fin».

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
  {"type": "wind_gust", "level": "yellow", "start": "2026-09-29T15:00:00+02:00",
   "end": "2026-09-29T21:00:00+02:00", "warning_id": 1224130978, "active": false}
]}}
```

## Qué no se hizo (y por qué)

- **Atributos numerados** (`warning_1_*`, como DWD): los índices cambian cuando acaba un aviso y una plantilla lee otro sin dar error. Los revisores de HA lo rechazan.
- **Toda la lista en atributos**: se guarda en la base de datos en cada cambio y puede pasar de 16 KB. Para eso está la acción.
- **Nivel por día** (hoy, mañana, pasado): MeteoGalicia lo da así, pero el patrón de HA es vigentes y próximos. El detalle por día sale de la acción.

## Pendiente

- Comentario de cada aviso ("Chuvia de máis de 40 litros/m2"): está en `rssAdversos`, por zonas; habría que cruzar concello y zona.
- Avisos por zona marítima, para quien navega o pesca.
- Adaptador `meteogal` para `weather_alerts_card` cuando MeteoGal esté publicado.
