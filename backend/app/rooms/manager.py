"""Gestión de salas en memoria (Punto 16). Para el MVP con un solo
proceso alcanza; si en el futuro se corre con varios workers, este es
el punto donde habría que mover el estado a Redis (mencionado en el
análisis de arquitectura, pero explícitamente fuera del MVP)."""

from __future__ import annotations

import asyncio
import random
import string
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

from app.engine.game import MentirosoGame
from app.engine.models import GameConfig, Player
from app.filters.dsl import CategoryFilter


def generate_room_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


@dataclass
class RoomSettings:
    min_players: int = 2
    max_players: int = 8
    min_declare: int = 1
    min_category_answers: int = 10
    betting_timeout_seconds: Optional[int] = 30
    answering_timeout_seconds: Optional[int] = 60
    hardcore_mode: bool = False


@dataclass
class Room:
    code: str
    settings: RoomSettings
    host_player_id: str
    players: dict[str, Player] = field(default_factory=dict)
    connections: dict[str, WebSocket] = field(default_factory=dict)
    game: Optional[MentirosoGame] = None
    pending_category: Optional[CategoryFilter] = None
    betting_timer: Optional[asyncio.Task] = None
    answering_timer: Optional[asyncio.Task] = None

    def is_full(self) -> bool:
        return len(self.players) >= self.settings.max_players

    def can_start(self) -> bool:
        return len(self.players) >= self.settings.min_players


class RoomManager:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}

    def create_room(self, host_name: str, settings: Optional[RoomSettings] = None) -> tuple[Room, str]:
        code = generate_room_code()
        while code in self._rooms:
            code = generate_room_code()
        host_id = f"pl_{random.randint(100000, 999999)}"
        room = Room(code=code, settings=settings or RoomSettings(), host_player_id=host_id)
        room.players[host_id] = Player(id=host_id, name=host_name)
        self._rooms[code] = room
        return room, host_id

    def get_room(self, code: str) -> Optional[Room]:
        return self._rooms.get(code.upper())

    def join_room(self, code: str, player_name: str) -> tuple[Optional[Room], Optional[str]]:
        room = self.get_room(code)
        if room is None:
            return None, None
        if room.is_full():
            return room, None
        pid = f"pl_{random.randint(100000, 999999)}"
        room.players[pid] = Player(id=pid, name=player_name)
        return room, pid

    def remove_room(self, code: str) -> None:
        self._rooms.pop(code.upper(), None)


room_manager = RoomManager()
