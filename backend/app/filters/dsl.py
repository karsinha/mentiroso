"""DSL de filtros para construir categorías.

Diseño deliberadamente simple para el MVP (según feedback: "la interfaz
debe mantenerse sencilla"):

- Una categoría es una lista de `Condition` combinadas con un único
  operador top-level (AND u OR) — sin anidamiento arbitrario de
  paréntesis. Cubre la enorme mayoría de los ejemplos del documento
  ("actuales que ganaron Champions Y Mundial", "jugaron en Barcelona O
  Real Madrid").
- Cada condición puede marcarse `negate=True` para soportar NOT
  ("ganó Champions pero NUNCA Mundial").
- Los `min_count` en achievement dejan preparado el terreno para
  "ganó 2+ Champions" sin tener que migrar el esquema después.

Esto es JSON puro (Pydantic) que viaja por WebSocket — nunca SQL, nunca
texto libre interpretado como query.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# Whitelist de tipos de condición soportados. Agregar uno nuevo implica
# agregar también su función de resolución en query_builder.py — nunca
# se generan condiciones "libres".
ConditionType = Literal["achievement", "nationality", "status", "club"]


class AchievementCondition(BaseModel):
    type: Literal["achievement"] = "achievement"
    achievement_code: str  # debe existir en AchievementType.code (whitelisteado en DB)
    min_count: int = Field(default=1, ge=1)
    negate: bool = False


class NationalityCondition(BaseModel):
    type: Literal["nationality"] = "nationality"
    nationality: str
    negate: bool = False


class StatusCondition(BaseModel):
    type: Literal["status"] = "status"
    status: Literal["ACTIVE", "RETIRED"]
    negate: bool = False


class ClubCondition(BaseModel):
    type: Literal["club"] = "club"
    club_name: str
    current_only: bool = False
    negate: bool = False


Condition = AchievementCondition | NationalityCondition | StatusCondition | ClubCondition


class CategoryFilter(BaseModel):
    entity_type: Literal["player"] = "player"  # único soportado en el MVP
    operator: Literal["AND", "OR"] = "AND"
    conditions: list[Condition]
    description: Optional[str] = None  # si no se manda, se autogenera

    def build_description(self) -> str:
        if self.description:
            return self.description
        parts = []
        for c in self.conditions:
            parts.append(_describe_condition(c))
        joiner = " y " if self.operator == "AND" else " o "
        return "Jugadores que " + joiner.join(parts)


def _describe_condition(c: Condition) -> str:
    prefix = "nunca " if c.negate else ""
    if isinstance(c, AchievementCondition):
        extra = f" ({c.min_count}+)" if c.min_count > 1 else ""
        return f"{prefix}ganaron {c.achievement_code}{extra}"
    if isinstance(c, NationalityCondition):
        return f"{prefix}son de nacionalidad {c.nationality}"
    if isinstance(c, StatusCondition):
        label = "en actividad" if c.status == "ACTIVE" else "retirados"
        return f"{prefix}están {label}"
    if isinstance(c, ClubCondition):
        where = "actualmente en" if c.current_only else "alguna vez en"
        return f"{prefix}jugaron {where} {c.club_name}"
    return "cumplen la condición"
