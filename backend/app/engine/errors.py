class GameError(Exception):
    """Base para todos los errores del motor de juego."""


class InvalidPhaseError(GameError):
    """La acción no está permitida en la fase actual."""


class NotYourTurnError(GameError):
    """El jugador que intenta actuar no tiene el turno."""


class InvalidDeclarationError(GameError):
    """La declaración no respeta las reglas (mínimo / debe superar la anterior)."""


class InvalidCategoryError(GameError):
    """La categoría no cumple el mínimo de respuestas posibles configurado."""


class DuplicateAnswerError(GameError):
    """El jugador intentó repetir la misma respuesta dos veces."""


class AnswerSlotsFullError(GameError):
    """Ya se completaron todos los casilleros de respuesta declarados."""


class InvalidAnswerIndexError(GameError):
    """Índice de respuesta inexistente al intentar borrar."""


class NotEnoughPlayersError(GameError):
    """No hay suficientes jugadores para arrancar la partida."""
