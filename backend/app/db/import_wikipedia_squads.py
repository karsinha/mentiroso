# TODO: ~10% de los jugadores quedan con qid=None cuando el wiki_title
# tiene desambiguación larga (ej. "Aderbar Santos", "Victor Hugo
# (footballer, born 11 May 2004)"). No bloquea el import porque el
# schema de Player no persiste qid todavía -- investigar aparte si en
# algún momento se necesita QID para deduplicar entre torneos.

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

import re
from dataclasses import dataclass

import mwparserfromhell

from app.engine.models import normalize_text

from .wiki_common import (
    find_section_index,
    get_section_wikitext,
    get_sections,
    resolve_qids,
)




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
    'fb player23', etc. -- todas comparten esta convención).

    Se usa para artículos de plantel completo de selecciones (Mundial,
    Copa América, Eurocopa). NO sirve para artículos de finales de
    clubes (Champions/Libertadores) -- ver `parse_final_lineup`."""
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


def parse_final_lineup(wikitext: str) -> tuple[list[dict], list[dict], str, str]:
    """Parsea la sección 'Details' de un artículo de final de Champions/
    Libertadores.

    Formato real (confirmado a mano en el artículo de la final 2024,
    ver conversación del proyecto) -- DISTINTO al de las tablas de
    plantel de selecciones que usa `parse_squad_table`:

    - No hay templates con parámetro `name=`. Cada jugador es una fila
      de tabla wiki: `|POS ||'''NUM'''||{{flagicon|PAI}} [[Jugador]]`.
    - Hay DOS bloques de columna (`|valign="top" width="N%"|`), uno
      por equipo, uno al lado del otro en la misma tabla. Los anchos
      pueden ser asimétricos (ej. 40%/50%), así que se matchea con
      regex, no con un string de ancho fijo.
    - Entre esas dos columnas puede haber una celda intermedia
      (`|valign="top"|[[File:...]]`, el mapita de posiciones) que NO
      tiene `width=` -- por eso el regex exige `width="\\d+%"` explícito,
      para no confundir esa celda con una columna de equipo.
    - Dentro de cada bloque, titulares y suplentes se separan por una
      fila `|colspan=3|'''Substitutes:'''`.
    - Después de los suplentes viene una fila `Manager:` con el DT --
      se excluye del resultado (no es jugador).
    - Los nombres de equipo salen del template {{Football box}} al
      principio de la sección (team1/team2), que es la fuente de
      verdad de quién es cada columna -- se devuelven junto con las
      listas para que el caller pueda saber cuál lista corresponde a
      qué club sin asumir un orden fijo.

    Devuelve (team1_players, team2_players, team1_name, team2_name).
    Cada jugador: {"wiki_title": ..., "display_name": ..., "role": "starter"|"substitute"}.

    Nota: esto está probado contra UN artículo (final 2024, 23 jugadores
    por equipo, conteo correcto). Antes de generalizar a Libertadores u
    otros años, conviene correrlo contra 2-3 casos más y confirmar que
    el patrón de tabla se mantiene (ver nota en fetch_club_final_lineup) --
    artículos más viejos podrían usar un template distinto a
    {{Football box}}."""
    code = mwparserfromhell.parse(wikitext)

    box = next(
        (t for t in code.filter_templates() if t.name.strip().lower() == "football box"),
        None,
    )
    if box is None:
        raise ValueError("No encontré el template {{Football box}} en esta sección.")

    def _team_name(param_name: str) -> str:
        value = box.get(param_name).value
        links = value.filter_wikilinks()
        if links:
            link = links[0]
            return str(link.text).strip() if link.text else str(link.title).strip()
        return str(value).strip()

    team1_name = _team_name("team1")
    team2_name = _team_name("team2")

    # No asumimos un ancho fijo de columna (width="40%") -- Wikipedia
    # suele usar columnas asimétricas (ej. 40%/50%), así que matcheamos
    # el patrón `valign="top" width="N%"|` con regex en vez de un string
    # literal exacto. Se exige el width= para no matchear la celda
    # intermedia de la imagen (`valign="top"|[[File:...]]`), que no lo tiene.
    COLUMN_MARKER_RE = re.compile(r'\|valign="top" width="\d+%"\|')
    raw = str(code)
    parts = COLUMN_MARKER_RE.split(raw)
    if len(parts) < 3:
        raise ValueError(
            "No encontré las dos columnas de alineación esperadas "
            "(patrón 'valign=\"top\" width=\"N%\"|'). Revisar estructura a mano "
            "-- puede que este artículo use un formato distinto."
        )
    team1_block, team2_block = parts[1], parts[2]

    def _parse_block(block: str) -> list[dict]:
        players: list[dict] = []
        role = "starter"
        for line in block.splitlines():
            if "Substitutes:" in line:
                role = "substitute"
                continue
            if "Manager:" in line:
                break  # DT y todo lo que venga después no son jugadores
            link_match = mwparserfromhell.parse(line).filter_wikilinks()
            if not link_match:
                continue
            link = link_match[0]  # primer wikilink de la fila = el jugador
            wiki_title = str(link.title).strip()
            display_name = str(link.text).strip() if link.text else wiki_title
            players.append({"wiki_title": wiki_title, "display_name": display_name, "role": role})
        return players

    team1_players = _parse_block(team1_block)
    team2_players = _parse_block(team2_block)

    return team1_players, team2_players, team1_name, team2_name





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
    '2024 UEFA Champions League final' (OJO: el patrón de título es
    "AÑO + final", no "TEMPORADA + Final" -- distinto al de los
    artículos de plantel de selecciones).

    Confirmado a mano (ver conversación del proyecto): estos artículos
    NO separan la alineación en una sección por club -- traen UNA sola
    sección llamada "Details" con dos columnas lado a lado
    (home/away), parseada por `parse_final_lineup`. Por eso acá NO se
    busca la sección por nombre de club, sino por el nombre fijo
    "Details", y después se elige cuál de las dos columnas corresponde
    a `champion_club` comparando nombres normalizados."""
    idx = find_section_index(final_article, "Details")
    if idx is None:
        raise ValueError(
            f"'{final_article}' no tiene una sección 'Details'. "
            "Revisar la estructura del artículo a mano (puede tener otro nombre)."
        )
    wikitext = get_section_wikitext(final_article, idx)
    team1_players, team2_players, team1_name, team2_name = parse_final_lineup(wikitext)

    target = normalize_text(champion_club)
    if normalize_text(team1_name) == target:
        players = team1_players
    elif normalize_text(team2_name) == target:
        players = team2_players
    else:
        raise ValueError(
            f"'{champion_club}' no coincide con ninguno de los dos equipos "
            f"de la final ('{team1_name}' / '{team2_name}'). Revisar el nombre exacto."
        )

    titles = [p["wiki_title"] for p in players]
    qids = resolve_qids(titles)
    for p in players:
        p["qid"] = qids.get(p["wiki_title"])
    return SquadFetchResult(achievement_code=achievement_code, year=year, players=players)


if __name__ == "__main__":
    # Prueba puntual 1: plantel campeón del Mundial 2022 (ya sabemos que funciona).
    result = fetch_national_team_squad(
        achievement_code="mundial",
        year=2022,
        squads_article="2022 FIFA World Cup squads",
        champion_country="Argentina",
    )
    for p in result.players:
        print(p)

    # Prueba puntual 2: final de Champions 2024, vía fetch_club_final_lineup
    # ya cableado con parse_final_lineup (23 jugadores esperados para
    # Real Madrid, ganador).
    print("\n--- Final de Champions 2024 (Real Madrid) ---")
    final_result = fetch_club_final_lineup(
        achievement_code="champions",
        year=2024,
        final_article="2024 UEFA Champions League final",
        champion_club="Real Madrid",
    )
    print(f"Total jugadores: {len(final_result.players)}")
    for p in final_result.players:
        print(p)