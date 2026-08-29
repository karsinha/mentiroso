"""backend/app/db/import_wikipedia_clubs.py

Fase A: snapshot de qué clubes juegan en qué liga/división en la
temporada 2025-26, a partir del artículo de temporada de cada liga
(ej. "2025–26 Argentine Primera División").

ADVERTENCIA: a diferencia de import_wikipedia_squads.py, esto NO está
validado contra un wikitext real todavía. El parser de abajo es un
diseño razonable basado en cómo Wikipedia arma tablas de posiciones en
general (filas '|-' seguidas de celdas '|', con el nombre de club como
primer wikilink de la fila) -- el mismo patrón de "fila por '|-'" que
usamos para parse_final_lineup. Pero no vimos el wikitext real de
ningún artículo de liga. Antes de confiar en esto para carga en lote,
correr fetch_league_clubs contra 1-2 casos y revisar la salida a mano
(ver bloque de prueba en __main__)."""

from __future__ import annotations

import re
from dataclasses import dataclass

import mwparserfromhell

from app.engine.models import normalize_text

from .wiki_common import find_section_index, get_section_wikitext


@dataclass
class LeagueClub:
    wiki_title: str
    display_name: str
    country: str
    league_name: str
    tier: int


def parse_league_table(wikitext: str, country: str, league_name: str, tier: int) -> list[LeagueClub]:
    """Extrae los clubes de una tabla de posiciones de liga.

    Supuesto (sin validar): cada club aparece como el primer wikilink
    dentro de una fila de tabla ('|-' seguido de celdas '|...'). Filas
    de encabezado (que empiezan con '!') se descartan.

    Si esto no matchea nada, es señal de que el artículo real usa un
    formato distinto (por ejemplo, plantillas tipo {{fb r|Club}} en vez
    de wikilinks planos, como pasa en algunos artículos de fútbol
    inglés) -- en ese caso hay que revisar el wikitext a mano y
    ajustar, igual que tuvimos que hacer con parse_final_lineup."""
    code = mwparserfromhell.parse(wikitext)
    raw = str(code)

    clubs: list[LeagueClub] = []
    seen_titles: set[str] = set()

    current_row: list[str] = []

    def _flush_row():
        if not current_row:
            return
        row_text = "\n".join(current_row)
        links = mwparserfromhell.parse(row_text).filter_wikilinks()
        if not links:
            return
        link = links[0]
        wiki_title = str(link.title).strip()
        if wiki_title in seen_titles:
            return
        seen_titles.add(wiki_title)
        display_name = str(link.text).strip() if link.text else wiki_title
        clubs.append(
            LeagueClub(
                wiki_title=wiki_title,
                display_name=display_name,
                country=country,
                league_name=league_name,
                tier=tier,
            )
        )

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("|-"):
            _flush_row()
            current_row = []
            continue
        if stripped.startswith("!"):
            continue  # fila de encabezado, no es un club
        current_row.append(line)
    _flush_row()

    return clubs


NAME_PARAM_RE = re.compile(r"\|\s*name_\w+\s*=\s*(\[\[[^\]]+\]\])")


def parse_sports_table_invoke(wikitext: str, country: str, league_name: str, tier: int) -> list[LeagueClub]:
    """Parsea el formato {{#invoke:Sports table|main|...}} usado por
    Premier League (y probablemente otras ligas europeas que compartan
    el mismo módulo de Wikipedia). Cada club aparece como un parámetro
    'name_XXX=[[Club F.C.|Club]]', no como fila de tabla wiki -- por
    eso NO se puede reusar parse_league_table (que busca filas '|-')."""
    clubs: list[LeagueClub] = []
    seen: set[str] = set()
    for match in NAME_PARAM_RE.finditer(wikitext):
        link_wikitext = match.group(1)
        links = mwparserfromhell.parse(link_wikitext).filter_wikilinks()
        if not links:
            continue
        link = links[0]
        wiki_title = str(link.title).strip()
        if wiki_title in seen:
            continue
        seen.add(wiki_title)
        display_name = str(link.text).strip() if link.text else wiki_title
        clubs.append(
            LeagueClub(
                wiki_title=wiki_title,
                display_name=display_name,
                country=country,
                league_name=league_name,
                tier=tier,
            )
        )
    return clubs


def fetch_league_clubs(
    league_article: str, country: str, league_name: str, tier: int
) -> list[LeagueClub]:
    # Estrategia 1: sección de tabla de posiciones (formato {{#invoke:Sports table}})
    idx = find_section_index(league_article, "League table")
    if idx is not None:
        wikitext = get_section_wikitext(league_article, idx)
        clubs = parse_sports_table_invoke(wikitext, country, league_name, tier)
        if clubs:
            return clubs

    # Estrategia 2: sección de "Personnel and X" (formato tabla wiki con
    # club como wikilink en 1ª celda) -- fallback para ligas como
    # Argentina, que no tienen "League table" con este módulo.
    for section_name in ("Personnel and sponsoring", "Personnel and kits"):
        idx = find_section_index(league_article, section_name)
        if idx is not None:
            wikitext = get_section_wikitext(league_article, idx)
            clubs = parse_league_table(wikitext, country, league_name, tier)
            if clubs:
                return clubs

    raise ValueError(
        f"No pude extraer clubes de '{league_article}' con ninguna estrategia conocida. "
        "Revisar estructura del artículo a mano."
    )


if __name__ == "__main__":
    from .wiki_common import get_sections

    ARTICLE = "2026 AFA Liga Profesional de Fútbol"
    print(f"--- Secciones de '{ARTICLE}' ---")
    for s in get_sections(ARTICLE):
        print(repr(s["index"]), repr(s["line"]))

    print(f"\n--- Clubes extraídos ---")
    clubs = fetch_league_clubs(
        ARTICLE, country="Argentina", league_name="AFA Liga Profesional de Fútbol", tier=1
    )
    print(f"Total: {len(clubs)}")
    for c in clubs:
        print(c)