"""Carga una base inicial pequeña de jugadores reales para poder probar
categorías del MVP. No pretende ser exhaustiva ni 100% precisa en años -
es una base de arranque para desarrollo, pensada para ampliarse después
con una fuente de datos más completa (Fase 10/25 del documento).

Correr con: python -m app.db.seed
"""
from __future__ import annotations

from datetime import date

from app.engine.models import normalize_text


from . import database
from .models import (
    Achievement,
    AchievementType,
    Club,
    Competition,
    EntityType,
    Player,
    PlayerAlias,
    PlayerClub,
    PlayerStatus,
)

ACHIEVEMENT_TYPES = [
    # code, name, is_individual_award
    ("champions", "UEFA Champions League", False),
    ("mundial", "Copa Mundial de la FIFA", False),
    ("libertadores", "Copa Libertadores", False),
    ("copa_america", "Copa América", False),
    ("eurocopa", "Eurocopa", False),
    ("balon_de_oro", "Balón de Oro", True),
    ("the_best", "The Best FIFA", True),
    ("bota_de_oro", "Bota de Oro", True),
]

CLUBS = [
    ("FC Barcelona", "España"),
    ("Real Madrid", "España"),
    ("Paris Saint-Germain", "Francia"),
    ("Inter Miami CF", "Estados Unidos"),
    ("Manchester United", "Inglaterra"),
    ("Juventus", "Italia"),
    ("Al Nassr", "Arabia Saudita"),
    ("Real Madrid CF", "España"),
    ("Boca Juniors", "Argentina"),
    ("River Plate", "Argentina"),
    ("Bayern Múnich", "Alemania"),
    ("Liverpool", "Inglaterra"),
    ("Manchester City", "Inglaterra"),
    ("AC Milan", "Italia"),
]

# nombre, apodos, nacionalidad, estado, logros[(code, year, club)], clubes[(club, actual)]
PLAYERS = [
    (
        "Lionel Messi", ["Leo Messi", "La Pulga", "Kun"],
        "Argentina", PlayerStatus.ACTIVE,
        [("champions", 2015, "FC Barcelona"), ("champions", 2011, "FC Barcelona"),
         ("champions", 2009, "FC Barcelona"), ("mundial", 2022, None),
         ("copa_america", 2021, None), ("balon_de_oro", 2023, None),
         ("balon_de_oro", 2021, None), ("balon_de_oro", 2019, None)],
        [("FC Barcelona", False), ("Paris Saint-Germain", False), ("Inter Miami CF", True)],
    ),
    (
        "Cristiano Ronaldo", ["CR7", "El Bicho"],
        "Portugal", PlayerStatus.ACTIVE,
        [("champions", 2008, "Manchester United"), ("champions", 2014, "Real Madrid"),
         ("champions", 2016, "Real Madrid"), ("champions", 2017, "Real Madrid"),
         ("champions", 2018, "Real Madrid"), ("eurocopa", 2016, None),
         ("balon_de_oro", 2017, None), ("balon_de_oro", 2016, None)],
        [("Manchester United", False), ("Real Madrid", False), ("Juventus", False), ("Al Nassr", True)],
    ),
    (
        "Xavi Hernández", ["Xavi"],
        "España", PlayerStatus.RETIRED,
        [("champions", 2006, "FC Barcelona"), ("champions", 2009, "FC Barcelona"),
         ("champions", 2011, "FC Barcelona"), ("mundial", 2010, None), ("eurocopa", 2008, None),
         ("eurocopa", 2012, None)],
        [("FC Barcelona", False)],
    ),
    (
        "Andrés Iniesta", ["Iniesta", "El Ilusionista"],
        "España", PlayerStatus.RETIRED,
        [("champions", 2006, "FC Barcelona"), ("champions", 2009, "FC Barcelona"),
         ("champions", 2011, "FC Barcelona"), ("mundial", 2010, None), ("eurocopa", 2008, None),
         ("eurocopa", 2012, None)],
        [("FC Barcelona", False)],
    ),
    (
        "Luka Modrić", ["Modric"],
        "Croacia", PlayerStatus.ACTIVE,
        [("champions", 2016, "Real Madrid"), ("champions", 2017, "Real Madrid"),
         ("champions", 2018, "Real Madrid"), ("champions", 2022, "Real Madrid"),
         ("balon_de_oro", 2018, None)],
        [("Real Madrid", True)],
    ),
    (
        "Sergio Agüero", ["Kun Agüero", "El Kun"],
        "Argentina", PlayerStatus.RETIRED,
        [("copa_america", 2021, None)],
        [("Manchester City", False)],
    ),
    (
        "Ángel Di María", ["Fideo"],
        "Argentina", PlayerStatus.ACTIVE,
        [("champions", 2014, "Real Madrid"), ("mundial", 2022, None), ("copa_america", 2021, None)],
        [("Paris Saint-Germain", False), ("Juventus", False)],
    ),
    (
        "Karim Benzema", ["Benzema"],
        "Francia", PlayerStatus.ACTIVE,
        [("champions", 2014, "Real Madrid"), ("champions", 2016, "Real Madrid"),
         ("champions", 2017, "Real Madrid"), ("champions", 2018, "Real Madrid"),
         ("champions", 2022, "Real Madrid"), ("balon_de_oro", 2022, None)],
        [("Real Madrid", False), ("Al Nassr", True)],
    ),
    (
        "Thibaut Courtois", ["Courtois"],
        "Bélgica", PlayerStatus.ACTIVE,
        [("champions", 2022, "Real Madrid")],
        [("Real Madrid", True)],
    ),
    (
        "Toni Kroos", ["Kroos"],
        "Alemania", PlayerStatus.RETIRED,
        [("champions", 2014, "Real Madrid"), ("champions", 2016, "Real Madrid"),
         ("champions", 2017, "Real Madrid"), ("champions", 2018, "Real Madrid"),
         ("champions", 2022, "Real Madrid"), ("champions", 2024, "Real Madrid"),
         ("mundial", 2014, None)],
        [("Real Madrid", False)],
    ),
    (
        "Juan Román Riquelme", ["Román"],
        "Argentina", PlayerStatus.RETIRED,
        [("libertadores", 2000, "Boca Juniors"), ("libertadores", 2001, "Boca Juniors"),
         ("libertadores", 2007, "Boca Juniors")],
        [("Boca Juniors", False)],
    ),
    (
        "Carlos Tevez", ["Apache Tevez"],
        "Argentina", PlayerStatus.RETIRED,
        [("libertadores", 2003, "Boca Juniors")],
        [("Boca Juniors", False)],
    ),
    (
        "Marcelo", ["Marcelo Vieira"],
        "Brasil", PlayerStatus.RETIRED,
        [("champions", 2014, "Real Madrid"), ("champions", 2016, "Real Madrid"),
         ("champions", 2017, "Real Madrid"), ("champions", 2018, "Real Madrid"),
         ("champions", 2022, "Real Madrid")],
        [("Real Madrid", False)],
    ),
    (
        "Manuel Neuer", ["Neuer"],
        "Alemania", PlayerStatus.ACTIVE,
        [("champions", 2013, "Bayern Múnich"), ("champions", 2020, "Bayern Múnich"),
         ("mundial", 2014, None)],
        [("Bayern Múnich", True)],
    ),
    (
        "Mohamed Salah", ["Salah", "El Faraón"],
        "Egipto", PlayerStatus.ACTIVE,
        [("champions", 2019, "Liverpool")],
        [("Liverpool", True)],
    ),
    (
        "Kylian Mbappé", ["Mbappé"],
        "Francia", PlayerStatus.ACTIVE,
        [("mundial", 2018, None)],
        [("Paris Saint-Germain", False), ("Real Madrid", True)],
    ),
    (
        "Erling Haaland", ["Haaland"],
        "Noruega", PlayerStatus.ACTIVE,
        [("champions", 2023, "Manchester City")],
        [("Manchester City", True)],
    ),
    (
        "Gabriel Batistuta", ["Batigol"],
        "Argentina", PlayerStatus.RETIRED,
        [],
        [("Boca Juniors", False)],
    ),
    (
        "Diego Maradona", ["Pelusa", "El Diez"],
        "Argentina", PlayerStatus.RETIRED,
        [("mundial", 1986, None)],
        [("Boca Juniors", False)],
    ),
    (
        "Enzo Fernández", ["Enzo"],
        "Argentina", PlayerStatus.ACTIVE,
        [("mundial", 2022, None), ("copa_america", 2021, None)],
        [("River Plate", False), ("Liverpool", False)],
    ),
]


def run_seed() -> None:
    database.init_db()
    session = database.SessionLocal()
    try:
        if session.query(Player).first():
            print("La base ya tiene datos, no se vuelve a sembrar.")
            return

        achievement_types = {}
        for code, name, is_award in ACHIEVEMENT_TYPES:
            at = AchievementType(code=code, name=name, is_individual_award=is_award)
            session.add(at)
            achievement_types[code] = at

        clubs = {}
        for name, country in CLUBS:
            club = Club(name=name, normalized_name=normalize_text(name), country=country)
            session.add(club)
            clubs[name] = club

        session.flush()  # asigna IDs

        for name, aliases, nationality, status, achievements, played_clubs in PLAYERS:
            player = Player(
                name=name,
                normalized_name=normalize_text(name),
                nationality=nationality,
                status=status,
            )
            session.add(player)
            session.flush()

            for alias in aliases:
                session.add(
                    PlayerAlias(
                        player_id=player.id,
                        alias=alias,
                        normalized_alias=normalize_text(alias),
                    )
                )

            for club_name, is_current in played_clubs:
                club = clubs.get(club_name)
                if club is None:
                    club = Club(name=club_name, normalized_name=normalize_text(club_name), country="")
                    session.add(club)
                    session.flush()
                    clubs[club_name] = club
                session.add(
                    PlayerClub(
                        player_id=player.id,
                        club_id=club.id,
                        end_date=None if is_current else date(2020, 1, 1),  # fechas exactas: TODO fuente de datos real
                    )
                )

            for code, year, club_name in achievements:
                at = achievement_types[code]
                club = clubs.get(club_name) if club_name else None
                session.add(
                    Achievement(
                        entity_type=EntityType.PLAYER,
                        entity_id=player.id,
                        achievement_type_id=at.id,
                        year=year,
                        club_id=club.id if club else None,
                    )
                )

        session.commit()
        print(f"Sembrados {len(PLAYERS)} jugadores.")
    finally:
        session.close()


if __name__ == "__main__":
    run_seed()
