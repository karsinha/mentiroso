"""backend/app/db/import_wikipedia_titles.py

Fase C: historial completo de campeones de un torneo, a partir de un
único artículo "List of X champions" (ej. "List of Copa Libertadores
champions") en vez de ir final por final.

ADVERTENCIA: sin validar contra wikitext real, mismo disclaimer que
import_wikipedia_clubs.py. El cruce contra la tabla Club (para decidir
si un club campeón ya existe en el snapshot 2025-26 o hay que crearlo
"huérfano") queda para el loader -- este archivo solo fetchea y
parsea, no toca la DB (mismo criterio que import_wikipedia_squads.py)."""

from __future__ import annotations

from dataclasses import dataclass

import mwparserfromhell

from .wiki_common import find_section_index, get_section_wikitext


@dataclass
class TitleWin:
    year: int
    wiki_title: str
    display_name: str


def parse_champions_table(wikitext: str) -> list[TitleWin]:
    """Extrae (año, club) de una tabla 'List of champions'.

    Supuesto sin validar: cada fila trae el año como primer campo de
    texto plano (no wikilink) y el club ganador como el PRIMER
    wikilink de la fila -- puede haber un segundo wikilink para el
    subcampeón, que se ignora a propósito (solo nos interesa quién
    ganó, no quién perdió).

    Riesgo conocido: si la tabla usa un formato de doble columna
    (temporada partida en dos años, ej. '1990–91') el año puede venir
    como string tipo '1990–91' en vez de un int limpio -- por eso
    `year` intenta parsear el primer número de 4 dígitos que encuentra
    en la celda, en vez de asumir que toda la celda es el año."""
    import re

    code = mwparserfromhell.parse(wikitext)
    raw = str(code)

    wins: list[TitleWin] = []
    current_row: list[str] = []

    def _flush_row():
        if not current_row:
            return
        row_text = "\n".join(current_row)
        year_match = re.search(r"\b(19|20)\d{2}\b", row_text)
        if not year_match:
            return
        year = int(year_match.group(0))

        links = mwparserfromhell.parse(row_text).filter_wikilinks()
        if not links:
            return
        link = links[0]
        wiki_title = str(link.title).strip()
        display_name = str(link.text).strip() if link.text else wiki_title
        wins.append(TitleWin(year=year, wiki_title=wiki_title, display_name=display_name))

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("|-"):
            _flush_row()
            current_row = []
            continue
        current_row.append(line)
    _flush_row()

    return wins


def fetch_champions_history(article_title: str, section_name: str = "Results") -> list[TitleWin]:
    idx = find_section_index(article_title, section_name)
    if idx is None:
        raise ValueError(
            f"'{article_title}' no tiene una sección '{section_name}'. "
            "Revisar el nombre exacto a mano."
        )
    wikitext = get_section_wikitext(article_title, idx)
    return parse_champions_table(wikitext)


if __name__ == "__main__":
    # Prueba exploratoria -- REVISAR A MANO antes de confiar.
    from .wiki_common import get_sections

    ARTICLE = "List of Copa Libertadores finals"  # confirmar título exacto
    print(f"--- Secciones de '{ARTICLE}' ---")
    for s in get_sections(ARTICLE):
        print(repr(s["index"]), repr(s["line"]))

    print(f"\n--- Títulos extraídos ---")
    wins = fetch_champions_history(ARTICLE, section_name="List of finals")
    for w in wins:
        print(w)