"""Errores del cliente de MeteoGalicia."""


class MeteoGalError(Exception):
    """Error base del cliente."""


class MeteoGalConnectionError(MeteoGalError):
    """No se pudo contactar con MeteoGalicia (red o tiempo de espera)."""


class MeteoGalResponseError(MeteoGalError):
    """MeteoGalicia respondió con un error o con datos que no se entienden."""


class MeteoGalNotFoundError(MeteoGalError):
    """El concello pedido no existe para MeteoGalicia."""


class MeteoSixError(MeteoGalResponseError):
    """MeteoSIX devolvió una excepción (siempre con HTTP 200, en el cuerpo)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"MeteoSIX {code}: {message}")
        self.code = code


class MeteoSixAuthError(MeteoSixError):
    """Falta la clave de MeteoSIX o no es válida (códigos 005 y 006)."""
