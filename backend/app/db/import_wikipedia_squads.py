"""backend/app/db/import_wikipedia_squads.py

Importa planteles campeones de torneos de selección/clubes desde
Wikipedia (API oficial, no scraping: https://www.mediawiki.org/wiki/API).
Wikidata resultó no confiable para "quién ganó qué" (ver discusión en el
proyecto: P54/P1344 devuelven ruido, incluso categorizan mal a DTs como
jugadores). Wikipedia SÍ mantiene tablas de plantel curadas a mano por
torneo/edición, que es justo el dato que necesitamos.

Requiere: pip install requests mwparserfromhell --break-system-packages
"""

from __future__ import annotations
import mwparserfromhell  # agregar junto a los otros imports, arriba del archivo
import re
import time
from dataclasses import dataclass

import requests

WIKI_API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "Mentiroso-DataImport/1.0 (proyecto educativo, uso interno)"}


def _api_get(params: dict) -> dict:
    params = {**params, "format": "json", "formatversion": 2}
    resp = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    time.sleep(0.5)  # buen ciudadano: no golpear la API sin pausas
    return resp.json()


def get_sections(article_title: str) -> list[dict]:
    """Devuelve [{"index": "3", "line": "Argentina"}, ...] — línea de
    sección tal cual aparece en el artículo (para matchear por país)."""
    data = _api_get({"action": "parse", "page": article_title, "prop": "sections"})
    return data["parse"]["sections"]


def find_section_index(article_title: str, country_name: str) -> str | None:
    for s in get_sections(article_title):
        if s["line"].strip().lower() == country_name.strip().lower():
            return s["index"]
    return None


def get_section_wikitext(article_title: str, section_index: str) -> str:
    data = _api_get(
        {"action": "parse", "page": article_title, "prop": "wikitext", "section": section_index}
    )
    return data["parse"]["wikitext"]


WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def parse_squad_table(wikitext: str) -> list[dict]:
    """Las tablas de plantel en Wikipedia no usan sintaxis de tabla
    (|celda||celda), sino plantillas: {{nat fs g player|no=1|pos=GK|
    name=[[Franco Armani]]|...}} — y encima con plantillas anidadas
    adentro (la edad viene como {{birth date and age|...}}). Por eso
    hace falta un parser real de wikitext (mwparserfromhell) en vez de
    una regex por líneas: una regex no distingue de qué plantilla es
    cada '}}' de cierre cuando hay anidamiento.

    Estrategia: recorrer TODAS las plantillas de la sección y quedarnos
    con las que tengan un parámetro 'name' (independientemente del
    nombre exacto de la plantilla -- Wikipedia usa varias familias
    según la época/competición: 'nat fs g player', 'fs player',
    'fb player23', etc. -- todas comparten esta convención)."""
    code = mwparserfromhell.parse(wikitext)
    players = []
    for template in code.filter_templates():
        if not template.has("name"):
            continue
        name_param = template.get("name").value
        links = name_param.filter_wikilinks()
        if not links:
            continue
        link = links[0]
        wiki_title = str(link.title).strip()
        display_name = str(link.text).strip() if link.text else wiki_title
        players.append({"wiki_title": wiki_title, "display_name": display_name})
    return players


def resolve_qids(wiki_titles: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for i in range(0, len(wiki_titles), 50):
        batch = wiki_titles[i : i + 50]
        data = _api_get(
            {"action": "query", "prop": "pageprops", "titles": "|".join(batch), "redirects": 1}
        )
        for page in data["query"]["pages"]:
            qid = page.get("pageprops", {}).get("wikibase_item")
            if qid:
                result[page["title"]] = qid

    # Fallback: reintentar en solitario los que quedaron sin resolver
    # en el batch (títulos con desambiguación a veces fallan agrupados).
    missing = [t for t in wiki_titles if t not in result]
    for title in missing:
        data = _api_get({"action": "query", "prop": "pageprops", "titles": title, "redirects": 1})
        for page in data["query"]["pages"]:
            qid = page.get("pageprops", {}).get("wikibase_item")
            if qid:
                result[page["title"]] = qid
    return result


@dataclass
class SquadFetchResult:
    achievement_code: str
    year: int
    players: list[dict]  # [{"wiki_title": ..., "display_name": ..., "qid": ...}]


def fetch_national_team_squad(
    achievement_code: str, year: int, squads_article: str, champion_country: str
) -> SquadFetchResult:
    """Para Mundial / Copa América / Eurocopa: un artículo tipo
    '2022 FIFA World Cup squads' con una sección por país."""
    idx = find_section_index(squads_article, champion_country)
    if idx is None:
        raise ValueError(
            f"No encontré la sección '{champion_country}' en '{squads_article}'. "
            "Revisar el nombre exacto de sección en Wikipedia (puede diferir "
            "levemente, ej. 'Argentina' vs 'Argentina national football team')."
        )
    wikitext = get_section_wikitext(squads_article, idx)
    players = parse_squad_table(wikitext)
    titles = [p["wiki_title"] for p in players]
    qids = resolve_qids(titles)
    for p in players:
        p["qid"] = qids.get(p["wiki_title"])
    return SquadFetchResult(achievement_code=achievement_code, year=year, players=players)


def fetch_club_final_lineup(
    achievement_code: str, year: int, final_article: str, champion_club: str
) -> SquadFetchResult:
    """Para Champions / Libertadores: un artículo tipo
    '2023–24 UEFA Champions League Final' con secciones 'Details' o
    listas de titulares/suplentes por equipo. La estructura varía más
    que la de selecciones -- conviene probar 1-2 casos a mano antes de
    automatizar en lote (ver nota abajo)."""
    idx = find_section_index(final_article, champion_club)
    if idx is None:
        # Muchos artículos de finales no separan por sección de equipo,
        # sino que tienen UNA tabla con dos columnas (local/visitante).
        # En ese caso hay que traer el artículo completo y parsear las
        # dos columnas por separado -- dejar para revisión manual caso
        # por caso, no generalizar a ciegas.
        raise ValueError(
            f"'{final_article}' no tiene una sección propia para '{champion_club}'. "
            "Revisar la estructura del artículo a mano."
        )
    wikitext = get_section_wikitext(final_article, idx)
    players = parse_squad_table(wikitext)
    titles = [p["wiki_title"] for p in players]
    qids = resolve_qids(titles)
    for p in players:
        p["qid"] = qids.get(p["wiki_title"])
    return SquadFetchResult(achievement_code=achievement_code, year=year, players=players)


if __name__ == "__main__":
    # Prueba puntual: plantel campeón del Mundial 2022.
    result = fetch_national_team_squad(
        achievement_code="mundial",
        year=2022,
        squads_article="2022 FIFA World Cup squads",
        champion_country="Argentina",
    )
    for p in result.players:
        print(p)