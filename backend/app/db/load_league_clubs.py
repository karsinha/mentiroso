"""backend/app/db/load_league_clubs.py

Loader: toma la salida de import_wikipedia_clubs.fetch_league_clubs y
hace upsert en la tabla Club real.

Reglas:
- Match por normalized_name (mismo criterio que usa search_players para
  jugadores). Se prueba primero contra display_name, y si no matchea,
  contra wiki_title -- por si seed.py ya cargó el club con el nombre
  largo en vez del corto (o viceversa).
- Si ya existe: se actualiza league_name/tier/country (piso lo que
  tenía antes -- esto es un snapshot de temporada, no un historial, así
  que la versión más reciente gana).
- Si no existe: se crea nuevo, con name=display_name (el nombre "de
  cancha", no el título largo de Wikipedia).
- No hace commit por club individual -- se comitea una sola vez al
  final de todo el batch, para no dejar la DB en estado intermedio si
  algo falla a mitad de camino.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.models import normalize_text

from .import_wikipedia_clubs import LeagueClub
from .models import Club


@dataclass
class LoadReport:
    created: list[str]
    updated: list[str]


def load_league_clubs(session: Session, clubs: list[LeagueClub]) -> LoadReport:
    report = LoadReport(created=[], updated=[])

    for lc in clubs:
        normalized_display = normalize_text(lc.display_name)
        normalized_wiki = normalize_text(lc.wiki_title)

        existing = session.scalar(
            select(Club).where(Club.normalized_name == normalized_display)
        )
        if existing is None and normalized_wiki != normalized_display:
            existing = session.scalar(
                select(Club).where(Club.normalized_name == normalized_wiki)
            )

        if existing is not None:
            existing.country = lc.country
            existing.league_name = lc.league_name
            existing.tier = lc.tier
            report.updated.append(lc.display_name)
        else:
            club = Club(
                name=lc.display_name,
                normalized_name=normalized_display,
                country=lc.country,
                league_name=lc.league_name,
                tier=lc.tier,
            )
            session.add(club)
            report.created.append(lc.display_name)

    return report


if __name__ == "__main__":
    from . import database
    from .import_wikipedia_clubs import fetch_league_clubs

    database.init_db()
    session = database.SessionLocal()
    try:
        clubs = fetch_league_clubs(
            "2026 AFA Liga Profesional de Fútbol",
            country="Argentina",
            league_name="AFA Liga Profesional de Fútbol",
            tier=1,
        )
        report = load_league_clubs(session, clubs)
        session.commit()

        print(f"Creados ({len(report.created)}):")
        for name in report.created:
            print(f"  + {name}")
        print(f"Actualizados ({len(report.updated)}):")
        for name in report.updated:
            print(f"  ~ {name}")
    finally:
        session.close()