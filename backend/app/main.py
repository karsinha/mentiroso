from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .db.database import get_session, init_db
from .engine.errors import GameError
from .engine.game import MentirosoGame
from .engine.models import CategorySpec, GameConfig, Player as EnginePlayer
from .engine.states import GamePhase
from .filters.dsl import CategoryFilter
from .filters.query_builder import (
    resolve_answer_player_id,
    resolve_category,
    search_players,
    validate_category,
)
from .rooms.manager import Room, RoomSettings, room_manager
from .schemas import (
    INCOMING_MESSAGE_TYPES,
    CreateRoomRequest,
    CreateRoomResponse,
    JoinRoomRequest,
    JoinRoomResponse,
)

logger = logging.getLogger("mentiroso")

# Fix: mensajes que solo tienen sentido si la partida ya arrancó. Antes
# esto se detectaba de rebote atajando AttributeError (porque
# `room.game` era None), lo cual también se comía errores internos
# reales y los reportaba como "la partida no arrancó".
GAME_REQUIRED_MESSAGE_TYPES = {
    "declare",
    "mentiroso",
    "submit_answer",
    "remove_answer",
    "finish_answering",
    "next_round",
    "end_game",
}

# Fix: cuánto tiempo se mantiene una sala en memoria sin NINGÚN cliente
# conectado antes de borrarla. Sin esto, `RoomManager.remove_room` nunca
# se llamaba y las salas se acumulaban para siempre.
ROOM_CLEANUP_GRACE_SECONDS = 600  # 10 minutos

app = FastAPI(title="Mentiroso")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


# ------------------------------------------------------------------ #
# REST: crear / unirse a salas, autocompletado
# ------------------------------------------------------------------ #


@app.post("/api/rooms", response_model=CreateRoomResponse)
def create_room(req: CreateRoomRequest) -> CreateRoomResponse:
    settings = RoomSettings(
        min_players=req.min_players,
        max_players=max(req.max_players, req.min_players),
        min_declare=req.min_declare,
        min_category_answers=req.min_category_answers,
        betting_timeout_seconds=req.betting_timeout_seconds,
        answering_timeout_seconds=req.answering_timeout_seconds,
        hardcore_mode=req.hardcore_mode,
    )
    room, player_id = room_manager.create_room(req.host_name, settings)
    return CreateRoomResponse(room_code=room.code, player_id=player_id)


@app.post("/api/rooms/{room_code}/join", response_model=JoinRoomResponse)
def join_room(room_code: str, req: JoinRoomRequest) -> JoinRoomResponse:
    room, player_id, error_reason = room_manager.join_room(room_code, req.player_name)
    if room is None:
        raise HTTPException(status_code=404, detail="La sala no existe.")
    if error_reason == "started":
        raise HTTPException(status_code=409, detail="La partida ya empezó, no se puede unir ahora.")
    if error_reason == "full":
        raise HTTPException(status_code=409, detail="La sala está llena.")
    return JoinRoomResponse(room_code=room.code, player_id=player_id)


@app.get("/api/players/search")
def api_search_players(q: str) -> list[dict]:
    session = get_session()
    try:
        return search_players(session, q)
    finally:
        session.close()


# ------------------------------------------------------------------ #
# Estado enviado por WS — combina info de sala (lobby) + estado del
# engine (si ya arrancó la partida). Personalizado por jugador porque
# las respuestas propias solo las ve el declarante (Punto 6).
# ------------------------------------------------------------------ #


def room_snapshot(room: Room, for_player_id: str) -> dict:
    base = {
        "room_code": room.code,
        "host_player_id": room.host_player_id,
        "settings": {
            "min_players": room.settings.min_players,
            "max_players": room.settings.max_players,
            "min_declare": room.settings.min_declare,
            "hardcore_mode": room.settings.hardcore_mode,
        },
        "players": [{"id": p.id, "name": p.name} for p in room.players.values()],
    }
    if room.game is None:
        base["phase"] = GamePhase.WAITING_FOR_PLAYERS.value
        base["game"] = None
    else:
        base["game"] = room.game.public_state(for_player_id=for_player_id)
        base["phase"] = room.game.phase.value
    return base


async def broadcast(room: Room, extra: Optional[dict] = None) -> None:
    stale = []
    for pid, ws in room.connections.items():
        payload = {"type": "state", "state": room_snapshot(room, pid)}
        if extra:
            payload.update(extra)
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            stale.append(pid)
    for pid in stale:
        room.connections.pop(pid, None)


async def send_error(ws: WebSocket, message: str) -> None:
    try:
        await ws.send_text(json.dumps({"type": "error", "message": message}))
    except Exception:
        pass


# ------------------------------------------------------------------ #
# Timers — sin "pasar", el turno tiene que resolverse solo con
# declare/mentiroso, así que un AFK necesita un default automático
# (ver engine.game.handle_betting_timeout / handle_answering_timeout).
# ------------------------------------------------------------------ #


def cancel_timers(room: Room) -> None:
    for attr in ("betting_timer", "answering_timer"):
        task = getattr(room, attr)
        if task is not None and not task.done():
            task.cancel()
        setattr(room, attr, None)


async def _betting_timeout_watcher(room: Room) -> None:
    seconds = room.settings.betting_timeout_seconds
    if not seconds:
        return
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        return
    game = room.game
    if game is None or game.phase != GamePhase.BETTING:
        return
    action = game.handle_betting_timeout()
    await broadcast(room, extra={"type": "info", "message": f"Tiempo agotado: acción forzada ({action})."})
    await refresh_timers(room)


async def _answering_timeout_watcher(room: Room) -> None:
    seconds = room.settings.answering_timeout_seconds
    if not seconds:
        return
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        return
    game = room.game
    if game is None or game.phase != GamePhase.ANSWERING:
        return
    await _resolve_answering(room, ended_by_timeout=True)
    await refresh_timers(room)


async def refresh_timers(room: Room) -> None:
    cancel_timers(room)
    game = room.game
    if game is None:
        return
    if game.phase == GamePhase.BETTING and room.settings.betting_timeout_seconds:
        room.betting_timer = asyncio.create_task(_betting_timeout_watcher(room))
    elif game.phase == GamePhase.ANSWERING and room.settings.answering_timeout_seconds:
        room.answering_timer = asyncio.create_task(_answering_timeout_watcher(room))


async def _resolve_answering(room: Room, ended_by_timeout: bool) -> None:
    game = room.game
    assert game is not None

    # Fix: se capturan las entradas (con su resolved_player_id, si
    # vino de autocompletado) ANTES de cerrar la demostración, y se
    # resuelve la categoría UNA sola vez para validar todas las
    # respuestas — antes se recalculaba `resolve_category` (o sea, la
    # categoría entera) una vez POR CADA respuesta cargada.
    entries = list(game.answers)
    game.finish_answering()  # solo valida la fase; tira GameError si no corresponde

    session = get_session()
    try:
        valid_ids = resolve_category(session, room.pending_category)
        flags = [
            resolve_answer_player_id(session, entry.raw_text, entry.resolved_player_id) in valid_ids
            for entry in entries
        ]
    finally:
        session.close()

    game.resolve_round(flags, ended_by_timeout=ended_by_timeout)
    await broadcast(room)


# ------------------------------------------------------------------ #
# Limpieza de salas huérfanas (fix: `remove_room` nunca se llamaba)
# ------------------------------------------------------------------ #


def _cancel_room_cleanup(room: Room) -> None:
    if room.cleanup_timer is not None and not room.cleanup_timer.done():
        room.cleanup_timer.cancel()
    room.cleanup_timer = None


async def _room_cleanup_watcher(room: Room) -> None:
    try:
        await asyncio.sleep(ROOM_CLEANUP_GRACE_SECONDS)
    except asyncio.CancelledError:
        return
    if room.connections:
        return  # alguien volvió a conectarse antes de que expire
    cancel_timers(room)
    room_manager.remove_room(room.code)
    logger.info("Sala %s eliminada por inactividad (sin conexiones).", room.code)


def _schedule_room_cleanup_if_empty(room: Room) -> None:
    if not room.connections:
        _cancel_room_cleanup(room)
        room.cleanup_timer = asyncio.create_task(_room_cleanup_watcher(room))


# ------------------------------------------------------------------ #
# WebSocket principal
# ------------------------------------------------------------------ #


@app.websocket("/ws/{room_code}")
async def ws_endpoint(websocket: WebSocket, room_code: str, player_id: str) -> None:
    room = room_manager.get_room(room_code)
    if room is None or player_id not in room.players:
        await websocket.close(code=4404, reason="Sala o jugador inválido.")
        return

    await websocket.accept()
    _cancel_room_cleanup(room)
    room.connections[player_id] = websocket

    # Fix: reconexión. Antes, un jugador que se caía quedaba marcado
    # `connected=False` para siempre; nunca se revertía al volver.
    if room.game is not None:
        for p in room.game.players:
            if p.id == player_id:
                p.connected = True

    await broadcast(room)

    try:
        while True:
            raw = await websocket.receive_text()
            await handle_message(room, player_id, websocket, raw)
    except WebSocketDisconnect:
        room.connections.pop(player_id, None)
        if room.game is not None:
            for p in room.game.players:
                if p.id == player_id:
                    p.connected = False
        await broadcast(room)
        _schedule_room_cleanup_if_empty(room)


async def handle_message(room: Room, player_id: str, websocket: WebSocket, raw: str) -> None:
    try:
        payload = json.loads(raw)
        msg_type = payload.get("type")
        model_cls = INCOMING_MESSAGE_TYPES.get(msg_type)
        if model_cls is None:
            await send_error(websocket, f"Tipo de mensaje desconocido: {msg_type}")
            return
        message = model_cls(**payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        await send_error(websocket, f"Mensaje inválido: {exc}")
        return

    if message.type in GAME_REQUIRED_MESSAGE_TYPES and room.game is None:
        await send_error(websocket, "La partida todavía no arrancó.")
        return

    try:
        if message.type == "propose_category":
            await on_propose_category(room, player_id, message.category, websocket)
        elif message.type == "start_game":
            await on_start_game(room, player_id, websocket)
        elif message.type == "declare":
            room.game.declare(player_id, message.amount)
            await broadcast(room)
            await refresh_timers(room)
        elif message.type == "mentiroso":
            room.game.call_mentiroso(player_id)
            await broadcast(room)
            await refresh_timers(room)
        elif message.type == "submit_answer":
            # Fix: antes se descartaba message.player_id (el id del
            # futbolista resuelto por el autocompletado) y se lo
            # pisaba con el player_id de la conexión WS. Ahora se
            # threadea correctamente hasta la validación final.
            room.game.submit_answer(player_id, message.text, message.player_id)
            await broadcast(room)
        elif message.type == "remove_answer":
            room.game.remove_answer(player_id, message.index)
            await broadcast(room)
        elif message.type == "finish_answering":
            # Fix: antes cualquier jugador conectado podía cortarle la
            # demostración a otro.
            if player_id != room.game.declarant_id:
                await send_error(websocket, "Solo el jugador desafiado puede terminar la demostración.")
            else:
                cancel_timers(room)
                await _resolve_answering(room, ended_by_timeout=False)
        elif message.type == "next_round":
            # Fix: antes cualquier jugador podía forzar el avance de
            # ronda; el frontend solo ocultaba el botón, no protegía
            # el mensaje real por WS.
            if player_id != room.host_player_id:
                await send_error(websocket, "Solo el anfitrión puede pasar a la siguiente ronda.")
            else:
                room.game.start_next_round()
                room.pending_category = None
                await broadcast(room)
        elif message.type == "end_game":
            if player_id != room.host_player_id:
                await send_error(websocket, "Solo el anfitrión puede terminar la partida.")
            else:
                cancel_timers(room)
                room.game.finish_game()
                await broadcast(room)
    except GameError as exc:
        await send_error(websocket, str(exc))
    except Exception:
        # Fix: antes un `except AttributeError` genérico se comía
        # también errores internos reales y los reportaba siempre como
        # "la partida no arrancó". Ahora ese caso se chequea explícito
        # arriba, y cualquier otra excepción se loguea de verdad.
        logger.exception(
            "Error inesperado procesando mensaje '%s' en sala %s (jugador %s)",
            message.type,
            room.code,
            player_id,
        )
        await send_error(websocket, "Ocurrió un error inesperado procesando tu acción.")


async def on_start_game(room: Room, player_id: str, websocket: WebSocket) -> None:
    if player_id != room.host_player_id:
        await send_error(websocket, "Solo el anfitrión puede iniciar la partida.")
        return
    if room.game is not None:
        await send_error(websocket, "La partida ya arrancó.")
        return
    if not room.can_start():
        await send_error(websocket, f"Se necesitan al menos {room.settings.min_players} jugadores.")
        return

    config = GameConfig(
        min_players=room.settings.min_players,
        max_players=room.settings.max_players,
        min_declare=room.settings.min_declare,
        betting_timeout_seconds=room.settings.betting_timeout_seconds,
        answering_timeout_seconds=room.settings.answering_timeout_seconds,
    )
    engine_players = [EnginePlayer(id=p.id, name=p.name) for p in room.players.values()]
    room.game = MentirosoGame(engine_players, config)
    await broadcast(room)


async def on_propose_category(room: Room, player_id: str, category: CategoryFilter, websocket: WebSocket) -> None:
    if room.game is None:
        await send_error(websocket, "Iniciá la partida antes de elegir una categoría.")
        return
    if room.game.phase not in (GamePhase.WAITING_FOR_PLAYERS, GamePhase.CATEGORY_SELECTION):
        await send_error(websocket, "No se puede cambiar de categoría en este momento.")
        return

    # La primera categoría de la partida la arma el anfitrión (todavía
    # no hay "turno" definido). De ahí en más, la arma quien tenga el
    # turno en ese momento (Punto 3 del documento).
    expected_player = (
        room.host_player_id if room.game.phase == GamePhase.WAITING_FOR_PLAYERS else room.game.current_turn_player_id
    )
    if player_id != expected_player:
        await send_error(websocket, "No te toca proponer la categoría.")
        return

    session = get_session()
    try:
        result = validate_category(session, category, room.settings.min_category_answers)
    finally:
        session.close()

    if not result.valid:
        # Deliberadamente NO se manda la cantidad real (Punto 6): ni
        # siquiera a quien la está creando, para no darle ventaja
        # cuando le toque declarar.
        await send_error(websocket, "Esa combinación de filtros no tiene suficientes respuestas posibles. Probá otra.")
        return

    room.pending_category = category
    spec = CategorySpec(id=f"round-{room.game.round_number + 1}", description=category.build_description())
    room.game.start_round(spec, valid_answer_count=result.answer_count)
    await broadcast(room)
    await refresh_timers(room)


# Sirve el frontend estático (Fase 8) directamente desde FastAPI para
# simplificar el MVP: no hace falta un segundo servidor.
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")