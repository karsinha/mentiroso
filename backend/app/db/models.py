"""Modelo de datos futbolístico.

Diseño revisado respecto al borrador inicial del documento:

- Los logros (títulos + premios individuales) se generalizan en una única
  tabla `Achievement` con `entity_type` (en vez de PLAYER_TITLE y
  PLAYER_AWARD separadas), para poder agregar clubes/selecciones/DTs en
  el futuro sin duplicar esquema.
- `PlayerAlias` para apodos y variantes de nombre (Kun Agüero, etc.),
  clave tanto para el autocompletado como para el modo hardcore.
- `PlayerClub` NO tiene unicidad por (player, club): un jugador puede
  tener múltiples pasos por el mismo club (préstamo + vuelta).
- Todo texto "buscable" se guarda también normalizado
  (`normalized_name` / `normalized_alias`) para comparar sin acentos ni
  mayúsculas.
"""

from __future__ import annotations

import enum
from datetime import date

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PlayerStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EntityType(str, enum.Enum):
    """Preparado para crecer más allá de jugadores sin tocar el esquema
    de Achievement."""

    PLAYER = "PLAYER"
    CLUB = "CLUB"
    NATIONAL_TEAM = "NATIONAL_TEAM"
    COACH = "COACH"


class Player(Base):
    __tablename__ = "player"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    normalized_name: Mapped[str] = mapped_column(String(120), index=True)
    birth_date: Mapped[date | None] = mapped_column(nullable=True)
    nationality: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[PlayerStatus] = mapped_column(SAEnum(PlayerStatus), index=True)

    aliases: Mapped[list["PlayerAlias"]] = relationship(back_populates="player", cascade="all, delete-orphan")
    clubs: Mapped[list["PlayerClub"]] = relationship(back_populates="player", cascade="all, delete-orphan")


class PlayerAlias(Base):
    __tablename__ = "player_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id"))
    alias: Mapped[str] = mapped_column(String(120))
    normalized_alias: Mapped[str] = mapped_column(String(120), index=True)

    player: Mapped["Player"] = relationship(back_populates="aliases")



class PlayerClub(Base):
    """Múltiples filas por el mismo (player, club) están permitidas
    a propósito: representan pasos distintos (ej. préstamo y vuelta)."""

    __tablename__ = "player_club"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id"), index=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("club.id"), index=True)
    start_date: Mapped[date | None] = mapped_column(nullable=True)
    end_date: Mapped[date | None] = mapped_column(nullable=True)  # NULL = actual

    player: Mapped["Player"] = relationship(back_populates="clubs")
    club: Mapped["Club"] = relationship()


class Competition(Base):
    __tablename__ = "competition"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(60), nullable=True)
    continent: Mapped[str | None] = mapped_column(String(60), nullable=True)


class AchievementType(Base):
    """Catálogo whitelisteado de tipos de logro. El constructor de
    categorías en el frontend solo puede ofrecer los `code` que existen
    acá — así el DSL de filtros nunca acepta un tipo arbitrario."""

    __tablename__ = "achievement_type"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True)  # champions, mundial, balon_de_oro...
    name: Mapped[str] = mapped_column(String(120))
    is_individual_award: Mapped[bool] = mapped_column(default=False)


class Achievement(Base):
    """Tabla genérica de logros. `entity_type` + `entity_id` permite
    reutilizar esta misma tabla para jugadores, clubes, selecciones o
    DTs sin duplicar esquema (a diferencia de PLAYER_TITLE/PLAYER_AWARD
    separadas)."""

    __tablename__ = "achievement"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[EntityType] = mapped_column(SAEnum(EntityType), index=True)
    entity_id: Mapped[int] = mapped_column(index=True)
    achievement_type_id: Mapped[int] = mapped_column(ForeignKey("achievement_type.id"), index=True)
    competition_id: Mapped[int | None] = mapped_column(ForeignKey("competition.id"), nullable=True)
    year: Mapped[int | None] = mapped_column(nullable=True)
    club_id: Mapped[int | None] = mapped_column(ForeignKey("club.id"), nullable=True)

    achievement_type: Mapped["AchievementType"] = relationship()
    competition: Mapped["Competition | None"] = relationship()
    club: Mapped["Club | None"] = relationship()

class Club(Base):
    __tablename__ = "club"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    normalized_name: Mapped[str] = mapped_column(String(120), index=True)
    country: Mapped[str] = mapped_column(String(60))
    league_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tier: Mapped[int | None] = mapped_column(nullable=True)