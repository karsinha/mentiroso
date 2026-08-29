import pytest

from app.engine.errors import (
    AnswerSlotsFullError,
    DuplicateAnswerError,
    InvalidDeclarationError,
    InvalidPhaseError,
    NotYourTurnError,
)
from app.engine.game import MentirosoGame
from app.engine.models import CategorySpec, GameConfig, Player
from app.engine.states import GamePhase


def make_game(n=3, **config_kwargs):
    players = [Player(id=f"p{i}", name=f"Jugador{i}") for i in range(n)]
    config = GameConfig(**config_kwargs) if config_kwargs else None
    return MentirosoGame(players, config)


def start(game, min_answers=10):
    cat = CategorySpec(id="c1", description="Ganadores de Champions")
    game.start_round(cat, valid_answer_count=min_answers)
    return cat


def test_turn_order_is_sequential_and_rotates():
    game = make_game(3)  # p0, p1, p2
    start(game)
    assert game.current_turn_player_id == "p0"
    game.declare("p0", 5)
    assert game.current_turn_player_id == "p1"
    game.declare("p1", 6)
    assert game.current_turn_player_id == "p2"


def test_cannot_act_out_of_turn():
    game = make_game(3)
    start(game)
    with pytest.raises(NotYourTurnError):
        game.declare("p1", 5)


def test_first_declaration_must_respect_minimum():
    game = make_game(3, min_declare=3)
    start(game)
    with pytest.raises(InvalidDeclarationError):
        game.declare("p0", 2)
    game.declare("p0", 3)  # ok


def test_declaration_must_exceed_previous():
    game = make_game(3)
    start(game)
    game.declare("p0", 5)
    with pytest.raises(InvalidDeclarationError):
        game.declare("p1", 5)
    with pytest.raises(InvalidDeclarationError):
        game.declare("p1", 4)
    game.declare("p1", 6)  # ok


def test_cannot_call_mentiroso_as_first_action():
    game = make_game(3)
    start(game)
    with pytest.raises(InvalidDeclarationError):
        game.call_mentiroso("p0")


def test_mentiroso_targets_the_immediately_previous_declarant():
    # A B C ; B dice 10 ; C dice MENTIROSO -> el desafiado es B
    game = make_game(3)
    start(game)
    game.declare("p0", 5)
    game.declare("p1", 10)
    game.call_mentiroso("p2")
    assert game.phase == GamePhase.ANSWERING
    assert game.declarant_id == "p1"
    assert game.challenger_id == "p2"
    assert game.declared_amount == 10


def test_only_declarant_can_submit_answers():
    game = make_game(3)
    start(game)
    game.declare("p0", 2)
    game.call_mentiroso("p1")
    with pytest.raises(NotYourTurnError):
        game.submit_answer("p2", "Lionel Messi")
    game.submit_answer("p0", "Lionel Messi")


def test_duplicate_answers_are_rejected_normalized():
    game = make_game(3)
    start(game)
    game.declare("p0", 2)
    game.call_mentiroso("p1")
    game.submit_answer("p0", "Lionel Messi")
    with pytest.raises(DuplicateAnswerError):
        game.submit_answer("p0", "  LIONEL   messi ")  # normaliza igual


def test_answer_slots_are_capped_at_declared_amount():
    game = make_game(3)
    start(game)
    game.declare("p0", 1)
    game.call_mentiroso("p1")
    game.submit_answer("p0", "Lionel Messi")
    with pytest.raises(AnswerSlotsFullError):
        game.submit_answer("p0", "Cristiano Ronaldo")


def test_remove_answer_allows_editing():
    game = make_game(3)
    start(game)
    game.declare("p0", 2)
    game.call_mentiroso("p1")
    game.submit_answer("p0", "Lionel Messi")
    game.submit_answer("p0", "Xavi")
    game.remove_answer("p0", 1)
    game.submit_answer("p0", "Iniesta")
    texts = [a.raw_text for a in game.answers]
    assert texts == ["Lionel Messi", "Iniesta"]


def test_resolve_round_success_all_or_nothing():
    game = make_game(3)
    start(game)
    game.declare("p0", 2)
    game.call_mentiroso("p1")
    game.submit_answer("p0", "Lionel Messi")
    game.submit_answer("p0", "Xavi")
    record = game.resolve_round([True, True])
    assert record.success is True
    assert game.scores["p0"] == 1  # demostró bien
    assert game.scores["p1"] == -1  # desafió mal
    assert game.phase == GamePhase.RESULT


def test_resolve_round_failure_if_incomplete_even_with_all_valid_flags_true():
    # Declaró 2, solo cargó 1 -> aunque sea válida, no llega al total: falla
    game = make_game(3)
    start(game)
    game.declare("p0", 2)
    game.call_mentiroso("p1")
    game.submit_answer("p0", "Lionel Messi")
    record = game.resolve_round([True])
    assert record.success is False
    assert game.scores["p0"] == -1
    assert game.scores["p1"] == 1


def test_resolve_round_failure_if_any_answer_invalid():
    game = make_game(3)
    start(game)
    game.declare("p0", 2)
    game.call_mentiroso("p1")
    game.submit_answer("p0", "Lionel Messi")
    game.submit_answer("p0", "Nombre Inventado")
    record = game.resolve_round([True, False])
    assert record.success is False
    assert game.scores["p0"] == -1
    assert game.scores["p1"] == 1


def test_fixed_points_regardless_of_declared_amount():
    game = make_game(3)
    start(game, min_answers=50)
    game.declare("p0", 40)
    game.call_mentiroso("p1")
    for i in range(40):
        game.submit_answer("p0", f"Jugador {i}")
    record = game.resolve_round([True] * 40)
    assert record.success is True
    assert game.scores["p0"] == 1  # no escala con la cantidad declarada


def test_next_round_rotates_starter():
    game = make_game(3)
    start(game)  # starter_index 0 -> p0 arranca
    assert game.current_turn_player_id == "p0"
    game.declare("p0", 2)
    game.call_mentiroso("p1")
    game.submit_answer("p0", "a")
    game.submit_answer("p0", "b")
    game.resolve_round([True, True])
    game.start_next_round()
    assert game.phase == GamePhase.CATEGORY_SELECTION
    cat = CategorySpec(id="c2", description="Ganadores de Libertadores")
    game.start_round(cat, valid_answer_count=10)
    assert game.current_turn_player_id == "p1"  # rota, no depende de quién ganó


def test_betting_timeout_forces_minimum_declare_when_no_declarations_yet():
    game = make_game(3, min_declare=2)
    start(game)
    action = game.handle_betting_timeout()
    assert action == "forced_declare"
    assert game.declarations[-1].amount == 2
    assert game.current_turn_player_id == "p1"


def test_betting_timeout_forces_mentiroso_when_declaration_exists():
    game = make_game(3)
    start(game)
    game.declare("p0", 5)
    action = game.handle_betting_timeout()
    assert action == "forced_mentiroso"
    assert game.phase == GamePhase.ANSWERING
    assert game.challenger_id == "p1"
    assert game.declarant_id == "p0"


def test_answering_timeout_resolves_with_partial_answers_as_failure():
    game = make_game(3)
    start(game)
    game.declare("p0", 3)
    game.call_mentiroso("p1")
    game.submit_answer("p0", "Lionel Messi")
    answers = game.handle_answering_timeout()
    assert answers == ["Lionel Messi"]
    record = game.resolve_round([True])
    assert record.success is False
    assert record.ended_by_timeout is False  # el caller debe marcarlo


def test_public_state_never_leaks_answer_count_or_hidden_answers():
    game = make_game(3)
    start(game)
    game.declare("p0", 2)
    game.call_mentiroso("p1")
    game.submit_answer("p0", "Lionel Messi")

    state_for_challenger = game.public_state(for_player_id="p1")
    assert state_for_challenger["answers"] is None
    assert state_for_challenger["answers_loaded"] == 1
    assert "valid_answer_count" not in state_for_challenger

    state_for_declarant = game.public_state(for_player_id="p0")
    assert state_for_declarant["answers"] == ["Lionel Messi"]


def test_cannot_declare_outside_betting_phase():
    game = make_game(3)
    start(game)
    game.declare("p0", 2)
    game.call_mentiroso("p1")
    with pytest.raises(InvalidPhaseError):
        game.declare("p2", 3)
