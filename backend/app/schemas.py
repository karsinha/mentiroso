"""Todo mensaje que entra desde el cliente (REST o WebSocket) pasa por
acá antes de tocar el Game Engine o la sala. Nada de JS decide nada:
esto es solo *forma*, la *validez* de la jugada la sigue decidiendo el
GameEngine (Punto 13, servidor autoritativo)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .filters.dsl import CategoryFilter


class CreateRoomRequest(BaseModel):
    host_name: str = Field(min_length=1, max_length=40)
    min_players: int = Field(default=2, ge=2, le=8)
    max_players: int = Field(default=8, ge=2, le=8)
    min_declare: int = Field(default=1, ge=1)
    min_category_answers: int = Field(default=10, ge=1)
    betting_timeout_seconds: Optional[int] = Field(default=30, ge=5, le=300)
    answering_timeout_seconds: Optional[int] = Field(default=60, ge=10, le=600)
    hardcore_mode: bool = False


class CreateRoomResponse(BaseModel):
    room_code: str
    player_id: str


class JoinRoomRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=40)


class JoinRoomResponse(BaseModel):
    room_code: str
    player_id: str


# ---------------------------------------------------------------------- #
# Mensajes entrantes por WebSocket (discriminados por `type`)
# ---------------------------------------------------------------------- #


class ProposeCategoryMessage(BaseModel):
    type: Literal["propose_category"] = "propose_category"
    category: CategoryFilter


class StartGameMessage(BaseModel):
    type: Literal["start_game"] = "start_game"


class DeclareMessage(BaseModel):
    type: Literal["declare"] = "declare"
    amount: int = Field(ge=1)


class MentirosoMessage(BaseModel):
    type: Literal["mentiroso"] = "mentiroso"


class SubmitAnswerMessage(BaseModel):
    type: Literal["submit_answer"] = "submit_answer"
    text: str = Field(min_length=1, max_length=120)
    player_id: Optional[int] = None  # si vino de autocompletado, ya resuelto


class RemoveAnswerMessage(BaseModel):
    type: Literal["remove_answer"] = "remove_answer"
    index: int = Field(ge=0)


class FinishAnsweringMessage(BaseModel):
    type: Literal["finish_answering"] = "finish_answering"


class NextRoundMessage(BaseModel):
    type: Literal["next_round"] = "next_round"


class EndGameMessage(BaseModel):
    type: Literal["end_game"] = "end_game"


INCOMING_MESSAGE_TYPES = {
    "propose_category": ProposeCategoryMessage,
    "start_game": StartGameMessage,
    "declare": DeclareMessage,
    "mentiroso": MentirosoMessage,
    "submit_answer": SubmitAnswerMessage,
    "remove_answer": RemoveAnswerMessage,
    "finish_answering": FinishAnsweringMessage,
    "next_round": NextRoundMessage,
    "end_game": EndGameMessage,
}
