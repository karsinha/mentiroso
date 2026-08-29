"""Motor de juego de MENTIROSO.

Reglas confirmadas con el usuario (no las asumidas por defecto en el
documento original):

- Turno estrictamente secuencial y rotativo (A -> B -> C -> A...).
- En tu turno SOLO hay dos acciones posibles: `declare` (subir, en +1 o
  más) o `call_mentiroso` (desafiar la declaración inmediatamente
  anterior). No existe "pasar".
- MENTIROSO solo puede decirlo el jugador que tiene el turno, y siempre
  apunta al jugador que hizo la última declaración (el anteúltimo en
  hablar, nunca uno de más atrás).
- Puntos fijos: quien demuestra bien +1 / quien lo desafió mal -1.
  Quien no demuestra -1 / quien lo desafió bien +1. (Sin escalado por
  cantidad declarada — decisión explícita del usuario.)
- La demostración no da feedback en vivo: el jugador carga sus N
  respuestas (puede borrar y reescribir), y recién al terminar
  (botón "Terminar" o timeout) se revela qué estuvo bien y qué mal.
- No se permiten respuestas duplicadas (comparación normalizada) dentro
  de una misma demostración.
- Sin "pasar" implica que hace falta un default de AFK/timeout: ver
  `handle_timeout`.

El motor NUNCA valida si una respuesta de fútbol es correcta -- eso es
responsabilidad de la capa de filtros/DB (app/filters + app/db), que se
inyecta como callback. Esto mantiene al engine testeable sin DB real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .errors import (
    AnswerSlotsFullError,
    DuplicateAnswerError,
    InvalidAnswerIndexError,
    InvalidCategoryError,
    InvalidDeclarationError,
    InvalidPhaseError,
    NotEnoughPlayersError,
    NotYourTurnError,
)
from .models import AnswerEntry, CategorySpec, Declaration, GameConfig, Player, RoundRecord, normalize_text
from .states import GamePhase


class MentirosoGame:
    def __init__(self, players: list[Player], config: Optional[GameConfig] = None):
        if len(players) < 2:
            raise NotEnoughPlayersError("Se necesitan al menos 2 jugadores.")
        self.config = config or GameConfig()
        if not (self.config.min_players <= len(players) <= self.config.max_players):
            raise NotEnoughPlayersError(
                f"La partida requiere entre {self.config.min_players} y "
                f"{self.config.max_players} jugadores."
            )

        self.players: list[Player] = list(players)
        self.scores: dict[str, int] = {p.id: 0 for p in players}
        self.phase: GamePhase = GamePhase.WAITING_FOR_PLAYERS
        self.round_number: int = 0
        self.starter_index: int = 0  # rota una posición cada ronda nueva
        self.history: list[RoundRecord] = []

        # Estado de la ronda en curso
        self.current_category: Optional[CategorySpec] = None
        self.turn_index: Optional[int] = None
        self.declarations: list[Declaration] = []
        self.answers: list[AnswerEntry] = []
        self.challenger_id: Optional[str] = None
        self.declarant_id: Optional[str] = None
        self.last_result: Optional[RoundRecord] = None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _player_ids(self) -> list[str]:
        return [p.id for p in self.players]

    @property
    def current_turn_player_id(self) -> Optional[str]:
        if self.turn_index is None:
            return None
        return self._player_ids()[self.turn_index]

    def _advance_turn(self) -> None:
        n = len(self.players)
        self.turn_index = (self.turn_index + 1) % n

    def _require_phase(self, *phases: GamePhase) -> None:
        if self.phase not in phases:
            raise InvalidPhaseError(
                f"Acción no permitida en fase {self.phase}. Se esperaba {phases}."
            )

    def _require_turn(self, player_id: str) -> None:
        if player_id != self.current_turn_player_id:
            raise NotYourTurnError(f"No es el turno de {player_id}.")

    # ------------------------------------------------------------------ #
    # Ciclo de vida de la ronda
    # ------------------------------------------------------------------ #

    def start_round(self, category: CategorySpec, valid_answer_count: int) -> None:
        """`valid_answer_count` se recibe SOLO para validar que la
        categoría sea jugable (Punto 5). Nunca se guarda en un atributo
        visible al cliente ni se expone por WS/REST."""
        self._require_phase(GamePhase.WAITING_FOR_PLAYERS, GamePhase.RESULT, GamePhase.CATEGORY_SELECTION)
        min_required = 1  # el mínimo configurable real vive en la capa de filtros;
        # acá solo garantizamos que no sea 0 (categoría imposible).
        if valid_answer_count < min_required:
            raise InvalidCategoryError("La categoría no tiene respuestas posibles.")

        self.round_number += 1
        self.current_category = category
        self.declarations = []
        self.answers = []
        self.challenger_id = None
        self.declarant_id = None
        self.last_result = None
        self.turn_index = self.starter_index
        self.phase = GamePhase.BETTING

    def declare(self, player_id: str, amount: int) -> None:
        self._require_phase(GamePhase.BETTING)
        self._require_turn(player_id)

        if not self.declarations:
            if amount < self.config.min_declare:
                raise InvalidDeclarationError(
                    f"La primera declaración debe ser al menos {self.config.min_declare}."
                )
        else:
            last = self.declarations[-1]
            if amount <= last.amount:
                raise InvalidDeclarationError(
                    f"Debés declarar más de {last.amount} (o decir MENTIROSO)."
                )

        self.declarations.append(Declaration(player_id=player_id, amount=amount))
        self._advance_turn()

    def call_mentiroso(self, player_id: str) -> None:
        self._require_phase(GamePhase.BETTING)
        self._require_turn(player_id)
        if not self.declarations:
            raise InvalidDeclarationError(
                "No podés decir MENTIROSO como primera acción de la ronda: "
                "todavía no hay ninguna declaración que desafiar."
            )

        last = self.declarations[-1]
        self.challenger_id = player_id
        self.declarant_id = last.player_id
        self.answers = []
        self.phase = GamePhase.ANSWERING

    # ------------------------------------------------------------------ #
    # Demostración
    # ------------------------------------------------------------------ #

    @property
    def declared_amount(self) -> int:
        if not self.declarations:
            return 0
        return self.declarations[-1].amount

    def submit_answer(self, player_id: str, text: str) -> int:
        """Devuelve el índice de la respuesta agregada."""
        self._require_phase(GamePhase.ANSWERING)
        if player_id != self.declarant_id:
            raise NotYourTurnError("Solo el jugador desafiado puede cargar respuestas.")
        if len(self.answers) >= self.declared_amount:
            raise AnswerSlotsFullError("Ya completaste todos los casilleros.")

        normalized = normalize_text(text)
        if not normalized:
            raise InvalidDeclarationError("Respuesta vacía.")
        if any(a.normalized == normalized for a in self.answers):
            raise DuplicateAnswerError(f"'{text}' ya fue ingresado.")

        self.answers.append(AnswerEntry(raw_text=text, normalized=normalized))
        return len(self.answers) - 1

    def remove_answer(self, player_id: str, index: int) -> None:
        self._require_phase(GamePhase.ANSWERING)
        if player_id != self.declarant_id:
            raise NotYourTurnError("Solo el jugador desafiado puede borrar respuestas.")
        if not (0 <= index < len(self.answers)):
            raise InvalidAnswerIndexError(index)
        self.answers.pop(index)

    def finish_answering(self) -> list[str]:
        """Cierra la carga de respuestas (por botón "Terminar" o por
        timeout) y devuelve la lista cruda para que la capa externa
        (filters/DB) la valide contra la categoría. No decide nada de
        fútbol acá."""
        self._require_phase(GamePhase.ANSWERING)
        return [a.raw_text for a in self.answers]

    def resolve_round(self, valid_flags: list[bool], ended_by_timeout: bool = False) -> RoundRecord:
        """`valid_flags` viene alineado 1:1 con las respuestas cargadas
        (en el orden en que se ingresaron). Todo o nada: para ganar hay
        que llegar a la cantidad declarada Y que todas sean válidas."""
        self._require_phase(GamePhase.ANSWERING)
        if len(valid_flags) != len(self.answers):
            raise InvalidDeclarationError("valid_flags no coincide con la cantidad de respuestas cargadas.")

        success = len(self.answers) == self.declared_amount and all(valid_flags)

        score_changes: dict[str, int] = {}
        if success:
            score_changes[self.declarant_id] = self.config.points_win
            score_changes[self.challenger_id] = -self.config.points_loss
        else:
            score_changes[self.declarant_id] = -self.config.points_loss
            score_changes[self.challenger_id] = self.config.points_win

        for pid, delta in score_changes.items():
            self.scores[pid] = self.scores.get(pid, 0) + delta

        record = RoundRecord(
            round_number=self.round_number,
            category_description=self.current_category.description,
            declarations=list(self.declarations),
            declarant_id=self.declarant_id,
            challenger_id=self.challenger_id,
            declared_amount=self.declared_amount,
            answers=[a.raw_text for a in self.answers],
            valid_flags=list(valid_flags),
            success=success,
            score_changes=score_changes,
            ended_by_timeout=ended_by_timeout,
        )
        self.history.append(record)
        self.last_result = record
        self.phase = GamePhase.RESULT
        return record

    # ------------------------------------------------------------------ #
    # Avance de ronda / fin de partida
    # ------------------------------------------------------------------ #

    def start_next_round(self) -> None:
        self._require_phase(GamePhase.RESULT)
        self.starter_index = (self.starter_index + 1) % len(self.players)
        self.phase = GamePhase.CATEGORY_SELECTION

    def finish_game(self) -> None:
        self.phase = GamePhase.FINISHED

    # ------------------------------------------------------------------ #
    # AFK / timeouts — no existe "pasar", así que necesitamos un default
    # explícito para no trabar la partida.
    # ------------------------------------------------------------------ #

    def handle_betting_timeout(self) -> str:
        """Se llama cuando el timer de BETTING expira sin acción del
        jugador en turno.

        Default elegido:
        - Si todavía no hay ninguna declaración en la ronda (le tocaba
          abrir), se le fuerza la declaración mínima configurada. Así
          la partida sigue sin trabarse y el jugador no gana nada por
          desconectarse.
        - Si ya había una declaración previa, se le fuerza un MENTIROSO
          automático contra el último declarante (no requiere que
          "invente" un número, y es la opción de menor riesgo para
          forzar sin arbitrariedad).

        Devuelve qué acción se forzó, para que la capa de WS pueda
        anunciarlo en el chat/log de la partida.
        """
        self._require_phase(GamePhase.BETTING)
        player_id = self.current_turn_player_id
        if not self.declarations:
            self.declare(player_id, self.config.min_declare)
            return "forced_declare"
        else:
            self.call_mentiroso(player_id)
            return "forced_mentiroso"

    def handle_answering_timeout(self) -> list[str]:
        """Se llama cuando expira el timer de ANSWERING. Cierra la
        demostración con lo que se haya cargado hasta ese momento (que,
        salvo que haya llegado justo a completar los N casilleros,
        automáticamente será un fallo por la regla de "todo o nada")."""
        return self.finish_answering()

    # ------------------------------------------------------------------ #
    # Serialización para el cliente — nunca exponer valid_answer_count
    # ------------------------------------------------------------------ #

    def public_state(self, for_player_id: Optional[str] = None) -> dict:
        """Estado a mandar por WS. Deliberadamente NO incluye la
        cantidad real de respuestas válidas de la categoría (Punto 6)."""
        return {
            "phase": self.phase.value,
            "round_number": self.round_number,
            "scores": dict(self.scores),
            "players": [p.id for p in self.players],
            "current_turn_player_id": self.current_turn_player_id,
            "category": self.current_category.description if self.current_category else None,
            "declarations": [
                {"player_id": d.player_id, "amount": d.amount} for d in self.declarations
            ],
            "declared_amount": self.declared_amount if self.declarations else None,
            "declarant_id": self.declarant_id,
            "challenger_id": self.challenger_id,
            # Mientras se está demostrando, todos ven CUÁNTAS respuestas
            # hay cargadas, pero no el contenido (salvo el propio
            # declarant_id, que ve lo que escribió).
            "answers_loaded": len(self.answers),
            "answers": (
                [a.raw_text for a in self.answers]
                if for_player_id == self.declarant_id
                else None
            ),
            "last_result": (
                {
                    "success": self.last_result.success,
                    "declarant_id": self.last_result.declarant_id,
                    "challenger_id": self.last_result.challenger_id,
                    "declared_amount": self.last_result.declared_amount,
                    "answers": self.last_result.answers,
                    "valid_flags": self.last_result.valid_flags,
                    "score_changes": self.last_result.score_changes,
                }
                if self.last_result
                else None
            ),
        }
