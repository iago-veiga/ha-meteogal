# Cliente de la API

Código en `custom_components/meteogal/api/`, sin dependencias de Home Assistant (D2 en [diseno.md](diseno.md)). Tests en `tests/api/` con respuestas reales guardadas (Santiago, 2026-09-26).

## Métodos

| Método | Endpoint | Devuelve |
|---|---|---|
| `get_concellos()` | `jsonConcellosNivelMax?dia=0` | Los 313 concellos (código INE y nombre) |
| `get_stations()` | `listaEstacionsMeteo` | 155 estaciones con coordenadas, altitud y concello |
| `get_daily_forecast(id)` | `jsonPredConcellos` | Días desde hoy: cielo, lluvia, viento y temperaturas por franja, UV y nivel de aviso |
| `get_hourly_forecast(id)` | `jsonPredHorariaConcellos` | Horas desde las 00:00 de hoy: cielo, viento y temperatura |
| `get_medium_term_forecast(id)` | `jsonPredMedioPrazo?dia=-1` | Días siguientes: 3 cielos con probabilidad, viento, máx/mín con márgenes |

## Criterios

- Códigos de cielo y viento tal cual: traducirlos a HA es cosa de la integración.
- `-9999` ("no disponible") → `None`. En medio plazo, un cielo sin dato se omite.
- Fechas en hora local de Galicia (`Europe/Madrid`); las horas llegan con zona.
- Errores: `MeteoGalConnectionError` (red, tiempo de espera), `MeteoGalResponseError` (HTTP distinto de 200, no es JSON o formato inesperado), `MeteoGalNotFoundError` (concello inexistente: `predConcello: null` o `idConcello: 0`).

## Validación con la API real (2026-09-26)

24 concellos, 6 por provincia: sin errores ni valores `None`.

- Horaria: **96 horas** (días 0–3 completos), no las ~74 que vimos el 2026-09-25. El alcance depende de la hora de la consulta o de la pasada del modelo.
- Medio plazo: días **4–7**, no 4–8 como el 2026-09-24. Con el corto plazo (0–3) salen **8 días**, a veces 9.

## Nombres de concello

MeteoGalicia usa dos formatos: la lista de concellos pone el artículo al final ("Coruña (A)") y la de estaciones, delante y en mayúsculas ("A CORUÑA"). Además, 54 de sus 313 nombres tienen errores: mayúsculas indebidas ("Santiago De Compostela"), una errata ("Pontes De Garcáa Rodríguez (As)"), un artículo que falta ("Pobra Do Caramiñal") y los 12 cambios del Nomenclátor de 2026 sin aplicar.

Regla: **nunca mostrar un nombre de concello que venga de la API**. Todo va por código INE y el nombre sale de `toponyms.py` (Nomenclátor de Galicia 2026). Ver [toponimos.md](toponimos.md).

## Pendiente de validar

- Cambio de hora (2026-10-25): cómo vienen las horas repetidas de 02:00 a 03:00 en la horaria. Hoy se asume la primera.
