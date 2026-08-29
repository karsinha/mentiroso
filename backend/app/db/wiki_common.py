"""backend/app/db/wiki_common.py

Cliente HTTP compartido para la API de MediaWiki, usado por los
distintos importadores de Wikipedia (squads, clubs, titles). Separado
para que cada importador no reimplemente su propio _api_get.
"""

from __future__ import annotations

import time

import requests

WIKI_API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "Mentiroso-DataImport/1.0 (proyecto educativo, uso interno)"}


def _api_get(params: dict) -> dict:
    params = {**params, "format": "json", "formatversion": 2}
    resp = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    time.sleep(0.5)  # buen ciudadano: no golpear la API sin pausas
    data = resp.json()
    if "error" in data:
        raise ValueError(f"Wikipedia API error para params={params}: {data['error']}")
    return data


def get_sections(article_title: str) -> list[dict]:
    """Devuelve [{"index": "3", "line": "Argentina"}, ...] — línea de
    sección tal cual aparece en el artículo."""
    data = _api_get({"action": "parse", "page": article_title, "prop": "sections"})
    return data["parse"]["sections"]


def find_section_index(article_title: str, section_name: str) -> str | None:
    for s in get_sections(article_title):
        if s["line"].strip().lower() == section_name.strip().lower():
            return s["index"]
    return None


def get_section_wikitext(article_title: str, section_index: str) -> str:
    data = _api_get(
        {"action": "parse", "page": article_title, "prop": "wikitext", "section": section_index}
    )
    return data["parse"]["wikitext"]


def resolve_qids(wiki_titles: list[str]) -> dict[str, str]:
    """Movido de import_wikipedia_squads.py -- lo van a necesitar
    también clubs.py y titles.py, no tiene sentido duplicarlo."""
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

    missing = [t for t in wiki_titles if t not in result]
    for title in missing:
        data = _api_get({"action": "query", "prop": "pageprops", "titles": title, "redirects": 1})
        for page in data["query"]["pages"]:
            qid = page.get("pageprops", {}).get("wikibase_item")
            if qid:
                result[page["title"]] = qid
    return result