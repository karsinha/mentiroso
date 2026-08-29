from enum import Enum


class GamePhase(str, Enum):
    """Fases de la partida. Estados imposibles de saltear: toda transición
    pasa por el GameEngine, nunca la decide el cliente."""

    WAITING_FOR_PLAYERS = "WAITING_FOR_PLAYERS"
    CATEGORY_SELECTION = "CATEGORY_SELECTION"
    BETTING = "BETTING"
    ANSWERING = "ANSWERING"
    RESULT = "RESULT"
    FINISHED = "FINISHED"
