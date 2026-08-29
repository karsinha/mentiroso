import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
from app.db.seed import run_seed
from app.filters.dsl import AchievementCondition, CategoryFilter, NationalityCondition, StatusCondition
from app.filters.query_builder import resolve_category, search_players, validate_answer, validate_category


@pytest.fixture()
def session(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    test_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=test_engine)

    import app.db.database as database_module

    monkeypatch.setattr(database_module, "engine", test_engine)
    monkeypatch.setattr(database_module, "SessionLocal", lambda: Session(bind=test_engine))

    run_seed()

    s = Session(bind=test_engine)
    yield s
    s.close()


def test_and_combination_champions_and_mundial(session):
    cat = CategoryFilter(
        operator="AND",
        conditions=[
            AchievementCondition(achievement_code="champions"),
            AchievementCondition(achievement_code="mundial"),
        ],
    )
    matched = resolve_category(session, cat)
    assert len(matched) >= 1  # al menos Kroos/Neuer cumplen ambas


def test_negate_excludes_players_with_the_achievement(session):
    cat = CategoryFilter(
        operator="AND",
        conditions=[
            AchievementCondition(achievement_code="champions"),
            AchievementCondition(achievement_code="mundial", negate=True),
        ],
    )
    matched = resolve_category(session, cat)
    all_with_champions = resolve_category(
        session, CategoryFilter(conditions=[AchievementCondition(achievement_code="champions")])
    )
    all_with_mundial = resolve_category(
        session, CategoryFilter(conditions=[AchievementCondition(achievement_code="mundial")])
    )
    assert matched == (all_with_champions - all_with_mundial)


def test_or_combination(session):
    cat = CategoryFilter(
        operator="OR",
        conditions=[
            AchievementCondition(achievement_code="libertadores"),
            NationalityCondition(nationality="Croacia"),
        ],
    )
    matched = resolve_category(session, cat)
    assert len(matched) >= 2


def test_status_filter(session):
    cat = CategoryFilter(conditions=[StatusCondition(status="RETIRED")])
    matched = resolve_category(session, cat)
    assert len(matched) >= 1


def test_impossible_category_is_rejected(session):
    cat = CategoryFilter(
        operator="AND",
        conditions=[
            AchievementCondition(achievement_code="champions"),
            AchievementCondition(achievement_code="mundial"),
            AchievementCondition(achievement_code="libertadores"),
            AchievementCondition(achievement_code="balon_de_oro"),
            NationalityCondition(nationality="Croacia"),
        ],
    )
    result = validate_category(session, cat, min_answers=10)
    assert result.valid is False


def test_reasonable_category_is_accepted(session):
    cat = CategoryFilter(conditions=[AchievementCondition(achievement_code="champions")])
    result = validate_category(session, cat, min_answers=3)
    assert result.valid is True
    assert result.answer_count >= 3


def test_search_players_matches_prefix_and_alias(session):
    results = search_players(session, "leo mess")
    names = [r["name"] for r in results]
    assert "Lionel Messi" in names

    results_alias = search_players(session, "kun")
    names_alias = [r["name"] for r in results_alias]
    assert "Lionel Messi" in names_alias or "Sergio Agüero" in names_alias


def test_validate_answer_checks_both_identity_and_category(session):
    cat = CategoryFilter(conditions=[AchievementCondition(achievement_code="mundial")])
    assert validate_answer(session, cat, "Lionel Messi") is True
    assert validate_answer(session, cat, "Erling Haaland") is False  # existe pero no ganó mundial
    assert validate_answer(session, cat, "Jugador Que No Existe") is False


def test_validate_answer_normalizes_accents_and_case(session):
    cat = CategoryFilter(conditions=[AchievementCondition(achievement_code="mundial")])
    assert validate_answer(session, cat, "  LIONEL messi ") is True
