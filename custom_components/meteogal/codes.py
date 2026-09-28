"""Códigos de cielo y viento de MeteoGalicia traducidos a Home Assistant.

Fuente: anexos II y III de la documentación oficial `JSON_Pred_Concello` (la misma
tabla usan la previsión horaria, el medio plazo y la observación por concello).
Los códigos 1xx son de día y los 2xx de noche; los dos últimos dígitos son el
mismo estado del cielo.

MeteoSIX usa nombres en vez de códigos (tabla de `sky_state` en su manual). Se
traducen con los mismos criterios que su código equivalente de la tabla anterior,
que es el que indica el nombre de su icono.
"""

from __future__ import annotations

from homeassistant.components.weather import (
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_CLOUDY,
    ATTR_CONDITION_FOG,
    ATTR_CONDITION_HAIL,
    ATTR_CONDITION_LIGHTNING,
    ATTR_CONDITION_LIGHTNING_RAINY,
    ATTR_CONDITION_PARTLYCLOUDY,
    ATTR_CONDITION_RAINY,
    ATTR_CONDITION_SNOWY,
    ATTR_CONDITION_SNOWY_RAINY,
    ATTR_CONDITION_SUNNY,
)

# Dos últimos dígitos del código de cielo → condición de HA.
_SKY: dict[int, str] = {
    1: ATTR_CONDITION_SUNNY,  # Despejado (de noche: clear-night)
    2: ATTR_CONDITION_PARTLYCLOUDY,  # Nubes altas
    3: ATTR_CONDITION_PARTLYCLOUDY,  # Nubes y claros
    4: ATTR_CONDITION_CLOUDY,  # Nublado 75 %
    5: ATTR_CONDITION_CLOUDY,  # Muy nublado / cubierto
    6: ATTR_CONDITION_FOG,  # Nieblas
    7: ATTR_CONDITION_RAINY,  # Chubasco
    8: ATTR_CONDITION_RAINY,  # Chubasco (75 %)
    9: ATTR_CONDITION_SNOWY,  # Chubasco de nieve
    10: ATTR_CONDITION_RAINY,  # Llovizna
    11: ATTR_CONDITION_RAINY,  # Lluvia
    12: ATTR_CONDITION_SNOWY,  # Nieve
    13: ATTR_CONDITION_LIGHTNING_RAINY,  # Tormenta
    14: ATTR_CONDITION_FOG,  # Bruma
    15: ATTR_CONDITION_FOG,  # Bancos de niebla
    16: ATTR_CONDITION_PARTLYCLOUDY,  # Nubes medias
    17: ATTR_CONDITION_RAINY,  # Lluvia débil
    18: ATTR_CONDITION_RAINY,  # Chubascos débiles
    19: ATTR_CONDITION_LIGHTNING,  # Tormenta con pocas nubes
    20: ATTR_CONDITION_SNOWY_RAINY,  # Aguanieve
    21: ATTR_CONDITION_HAIL,  # Granizo
    22: ATTR_CONDITION_RAINY,  # Nublado con chubascos débiles
    23: ATTR_CONDITION_SNOWY,  # Nublado con nieve
    24: ATTR_CONDITION_FOG,  # Calima: HA no tiene polvo en suspensión
    25: ATTR_CONDITION_CLOUDY,  # Cubierto
}

# Estado del cielo de MeteoSIX → condición de HA, entre paréntesis el icono.
_METEOSIX_SKY: dict[str, str] = {
    "SUNNY": ATTR_CONDITION_SUNNY,  # despexado (de noche: clear-night)
    "HIGH_CLOUDS": ATTR_CONDITION_PARTLYCLOUDY,  # nubesaltas
    "PARTLY_CLOUDY": ATTR_CONDITION_PARTLYCLOUDY,  # nubescraros
    "MID_CLOUDS": ATTR_CONDITION_PARTLYCLOUDY,  # nubes medias
    "CLOUDY": ATTR_CONDITION_CLOUDY,  # nubes75
    "OVERCAST": ATTR_CONDITION_CLOUDY,  # cuberto
    "FOG": ATTR_CONDITION_FOG,
    "MIST": ATTR_CONDITION_FOG,
    "FOG_BANK": ATTR_CONDITION_FOG,
    "SHOWERS": ATTR_CONDITION_RAINY,  # chubasco
    "OVERCAST_AND_SHOWERS": ATTR_CONDITION_RAINY,  # chubasco75
    "WEAK_SHOWERS": ATTR_CONDITION_RAINY,  # chubascosdebiles
    "DRIZZLE": ATTR_CONDITION_RAINY,  # orballo
    "WEAK_RAIN": ATTR_CONDITION_RAINY,  # chuviadebil
    "RAIN": ATTR_CONDITION_RAINY,  # chuvia
    "INTERMITENT_SNOW": ATTR_CONDITION_SNOWY,
    "SNOW": ATTR_CONDITION_SNOWY,
    "MELTED_SNOW": ATTR_CONDITION_SNOWY_RAINY,  # aguanieve
    "RAIN_HAIL": ATTR_CONDITION_HAIL,
    "STORMS": ATTR_CONDITION_LIGHTNING_RAINY,
    "STORM_THEN_CLOUDY": ATTR_CONDITION_LIGHTNING,  # como "tormenta con pocas nubes"
}

PRECIPITATION_CONDITIONS = frozenset(
    {
        ATTR_CONDITION_RAINY,
        ATTR_CONDITION_SNOWY,
        ATTR_CONDITION_SNOWY_RAINY,
        ATTR_CONDITION_LIGHTNING_RAINY,
        ATTR_CONDITION_HAIL,
    }
)

# Viento: 299 calma, 300 variable, 301-332 en 4 tramos de 8 rumbos.
WIND_CALM = 299
WIND_VARIABLE = 300
_WIND_FIRST = 301
_WIND_LAST = 332
_BEARINGS = (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0)  # N, NE ... NO


def condition(code: int | None) -> str | None:
    """Condición de HA para un código de cielo, o None si no se conoce."""
    if code is None or not is_sky_code(code):
        return None
    result = _SKY[code % 100]
    if result == ATTR_CONDITION_SUNNY and is_night(code):
        return ATTR_CONDITION_CLEAR_NIGHT
    return result


def meteosix_condition(sky: str | None, night: bool | None) -> str | None:
    """Condición de HA para un estado del cielo de MeteoSIX, o None si no se conoce."""
    result = _METEOSIX_SKY.get(sky) if sky else None
    if result == ATTR_CONDITION_SUNNY and night:
        return ATTR_CONDITION_CLEAR_NIGHT
    return result


def is_sky_code(code: int) -> bool:
    return code // 100 in (1, 2) and code % 100 in _SKY


def is_night(code: int) -> bool:
    return code // 100 == 2


def wind_bearing(code: int | None) -> float | None:
    """Rumbo del que viene el viento, en grados; None en calma o variable."""
    if code is None or not _WIND_FIRST <= code <= _WIND_LAST:
        return None
    return _BEARINGS[(code - _WIND_FIRST) % 8]


def wind_intensity(code: int | None) -> int | None:
    """0 calma, 1 variable o flojo, 2 moderado, 3 fuerte, 4 muy fuerte."""
    if code is None:
        return None
    if code == WIND_CALM:
        return 0
    if code == WIND_VARIABLE:
        return 1
    if _WIND_FIRST <= code <= _WIND_LAST:
        return 1 + (code - _WIND_FIRST) // 8
    return None
