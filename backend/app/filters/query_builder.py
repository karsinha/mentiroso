"""Traductor de CategoryFilter -> conjuntos de jugadores.

Regla de oro (Punto 24 / seguridad): nunca se arma SQL concatenando
strings del cliente. Cada tipo de condición del DSL whitelisteado en
`dsl.py` tiene UNA función de resolución acá, predefinida, que devuelve
un `set[int]` de player_ids. Las condiciones se combinan en Python
(intersección / unión / complemento), nunca con SQL dinámico.

También vive acá:
- el cálculo (privado, solo server-side) de cuántas respuestas válidas
  tiene una categoría, usado para validar que sea jugable (Punto 5) y
  para el mínimo configurable — ese número NUNCA se le manda al
  cliente durante la partida (Punto 6).
- la búsqueda/autocompletado (Punto 8).
- la validación de una respuesta individual contra una categoría, para
  la fase de demostración.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.models import normalize_text

from ..db.models import (
    Achievement,
    AchievementType,
    Club,
    Player,
    PlayerAlias,
    PlayerClub,
    PlayerStatus,
)
from .dsl import (
    AchievementCondition,
    CategoryFilter,
    ClubCondition,
    Condition,
    NationalityCondition,
    StatusCondition,
)


def _all_player_ids(session: Session) -> set[int]:
    return set(session.scalars(select(Player.id)).all())


def _resolve_achievement(session: Session, c: AchievementCondition) -> set[int]:
    at_id = session.scalar(select(AchievementType.id).where(AchievementType.code == c.achievement_code))
    if at_id is None:
        return set()
    rows = session.execute(
        select(Achievement.entity_id, Achievement.id)
        .where(Achievement.achievement_type_id == at_id)
        .where(Achievement.entity_type == "PLAYER")
        .where(Achievement.result == c.result)
    ).all()
    counts: dict[int, int] = {}
    for entity_id, _ in rows:
        counts[entity_id] = counts.get(entity_id, 0) + 1
    return {pid for pid, n in counts.items() if n >= c.min_count}


def _resolve_nationality(session: Session, c: NationalityCondition) -> set[int]:
    target = normalize_text(c.nationality)
    return set(
        session.scalars(select(Player.id).where(Player.normalized_nationality == target)).all()
    )


def _resolve_status(session: Session, c: StatusCondition) -> set[int]:
    status = PlayerStatus(c.status)
    return set(session.scalars(select(Player.id).where(Player.status == status)).all())


def _resolve_club(session: Session, c: ClubCondition) -> set[int]:
    target = normalize_text(c.club_name)
    club_ids = set(session.scalars(select(Club.id).where(Club.normalized_name == target)).all())
    if not club_ids:
        return set()
    query = select(PlayerClub.player_id).where(PlayerClub.club_id.in_(club_ids))
    if c.current_only:
        query = query.where(PlayerClub.end_date.is_(None))
    return set(session.scalars(query).all())


_RESOLVERS = {
    AchievementCondition: _resolve_achievement,
    NationalityCondition: _resolve_nationality,
    StatusCondition: _resolve_status,
    ClubCondition: _resolve_club,
}


def resolve_condition(session: Session, condition: Condition, universe: set[int]) -> set[int]:
    resolver = _RESOLVERS[type(condition)]
    matched = resolver(session, condition)
    return (universe - matched) if condition.negate else matched


def resolve_category(session: Session, category: CategoryFilter) -> set[int]:
    """Devuelve el set de player_ids que cumplen la categoría. SOLO se usa
    server-side; nunca se serializa completo hacia el cliente."""
    if not category.conditions:
        return set()

    universe = _all_player_ids(session)
    sets = [resolve_condition(session, c, universe) for c in category.conditions]

    if category.operator == "AND":
        result = sets[0]
        for s in sets[1:]:
            result = result & s
        return result
    else:  # OR
        result: set[int] = set()
        for s in sets:
            result |= s
        return result


@dataclass
class CategoryValidation:
    valid: bool
    answer_count: int  # NUNCA exponer esto al cliente durante la partida
    reason: str | None = None


def validate_category(session: Session, category: CategoryFilter, min_answers: int) -> CategoryValidation:
    matched = resolve_category(session, category)
    count = len(matched)
    if count < min_answers:
        return CategoryValidation(
            valid=False,
            answer_count=count,
            reason=f"La categoría solo tiene {count} respuestas posibles (mínimo {min_answers}).",
        )
    return CategoryValidation(valid=True, answer_count=count)


# ---------------------------------------------------------------------- #
# Autocompletado (Punto 8) — nunca filtra por si cumple o no la categoría,
# solo ayuda a escribir el nombre correctamente y a desambiguar.
# ---------------------------------------------------------------------- #

def search_players(session: Session, query_text: str, limit: int = 8) -> list[dict]:
    norm = normalize_text(query_text)
    if not norm:
        return []

    direct = session.execute(
        select(Player.id, Player.name, Player.nationality, Player.birth_date)
        .where(Player.normalized_name.like(f"{norm}%"))
        .limit(limit)
    ).all()

    alias_rows = session.execute(
        select(Player.id, Player.name, Player.nationality, Player.birth_date)
        .join(PlayerAlias, PlayerAlias.player_id == Player.id)
        .where(PlayerAlias.normalized_alias.like(f"{norm}%"))
        .limit(limit)
    ).all()

    seen: dict[int, dict] = {}
    for pid, name, nationality, birth_date in [*direct, *alias_rows]:
        if pid not in seen:
            seen[pid] = {
                "player_id": pid,
                "name": name,
                "nationality": nationality,
                "birth_year": birth_date.year if birth_date else None,
            }
    return list(seen.values())[:limit]


# ---------------------------------------------------------------------- #
# Validación de una respuesta cargada durante la demostración.
# ---------------------------------------------------------------------- #

def resolve_player_by_text(session: Session, text: str) -> int | None:
    """Intenta resolver un texto libre (modo hardcore, o cuando no vino
    ya como player_id de un autocompletado) a un único jugador. Si es
    ambiguo (ej. "Ronaldo") devuelve None: en el MVP una respuesta
    ambigua se considera inválida — mejora futura: desambiguar con
    apellido + club."""
    norm = normalize_text(text)
    direct = set(session.scalars(select(Player.id).where(Player.normalized_name == norm)).all())
    via_alias = set(
        session.scalars(
            select(PlayerAlias.player_id).where(PlayerAlias.normalized_alias == norm)
        ).all()
    )
    candidates = direct | via_alias
    if len(candidates) == 1:
        return next(iter(candidates))
    return None


def resolve_answer_player_id(session: Session, text: str, player_id: int | None = None) -> int | None:
    """Fix: antes esto vivía inline dentro de `validate_answer` y se
    recalculaba (junto con `resolve_category`, ¡completa!) por cada
    respuesta de una demostración. Se separa para poder reusarlo desde
    `main.py` validando muchas respuestas contra un único cálculo de
    `resolve_category` (ver `_resolve_answering`).

    Si `player_id` ya vino resuelto por el autocompletado (modo
    normal), se usa directamente sin volver a "adivinar" por texto."""
    return player_id if player_id is not None else resolve_player_by_text(session, text)


def validate_answer(session: Session, category: CategoryFilter, text: str, player_id: int | None = None) -> bool:
    """`player_id` opcional: si la respuesta vino de un autocompletado
    (modo normal), ya trae el id resuelto sin ambigüedad. Si no, se
    intenta resolver por texto (modo hardcore).

    Nota: esta función queda para uso puntual (un solo chequeo, como en
    los tests). Para validar N respuestas de una misma demostración,
    usar `resolve_category` una sola vez + `resolve_answer_player_id`
    por cada respuesta (ver `main.py::_resolve_answering`), para no
    recalcular la categoría completa N veces."""
    pid = resolve_answer_player_id(session, text, player_id)
    if pid is None:
        return False
    valid_ids = resolve_category(session, category)
    return pid in valid_ids