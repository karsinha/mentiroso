"""Modelos de datos puros del motor de juego.

Deliberadamente NO dependen de FastAPI, SQLAlchemy ni de nada externo,
para poder testear el motor con `pytest` sin levantar un server ni una DB
(Fase 3 / Fase 4 del documento de diseño).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Optional


def normalize_text(text: str) -> str:
    """Normaliza un string para comparación: minúsculas, sin acentos, sin
    espacios de más. Se usa para detectar duplicados en la demostración y
    para comparar nombres contra la base de datos (modo hardcore incluido)."""
    text = text.strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


@dataclass
class Player:
    id: str
    name: str
    connected: bool = True


@dataclass
class Declaration:
    player_id: str
    amount: int


@dataclass
class AnswerEntry:
    raw_text: str
    normalized: str


@dataclass
class RoundRecord:
    """Historial de una ronda ya finalizada (Fase 17: guardar historial)."""

    round_number: int
    category_description: str
    declarations: list[Declaration]
    declarant_id: str
    challenger_id: str
    declared_amount: int
    answers: list[str]
    valid_flags: list[bool]
    success: bool
    score_changes: dict[str, int]
    ended_by_timeout: bool = False


@dataclass
class CategorySpec:
    """Lo mínimo que el motor necesita saber de una categoría: una
    descripción para mostrar en pantalla. La validación de "cuántas
    respuestas existen" ocurre ANTES de esto, en la capa de filtros/DB
    (ver app/filters), y ese número nunca se le pasa al engine ni al
    cliente durante la partida (Punto 6 del documento: no revelar la
    cantidad)."""

    id: str
    description: str


@dataclass
class GameConfig:
    min_players: int = 2
    max_players: int = 8
    min_declare: int = 1
    betting_timeout_seconds: Optional[int] = 30
    answering_timeout_seconds: Optional[int] = 60
    points_win: int = 1
    points_loss: int = 1
