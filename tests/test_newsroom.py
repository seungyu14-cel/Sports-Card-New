from __future__ import annotations

from sports_card_news.newsroom import _missing_critical_fields, _select_template


def test_complete_verified_game_does_not_require_delta_search() -> None:
    game = {
        "status": "종료",
        "home_score": 5,
        "away_score": 2,
        "verified": True,
    }
    stats = [
        {"verified": True, "player_id": "p1"},
        {"verified": True, "player_id": "p2"},
    ]
    sources = [
        {"verified": True, "source_priority": 5, "url": "https://example.com"}
    ]

    assert _missing_critical_fields(game, stats, sources) == []


def test_incomplete_game_requests_only_missing_facts() -> None:
    game = {
        "status": "종료",
        "home_score": 5,
        "away_score": 2,
        "verified": False,
    }
    missing = _missing_critical_fields(game, [], [])

    assert missing == [
        "verified_game_result",
        "key_player_stats",
        "official_postgame_context",
    ]


def test_news_event_selects_fixed_template() -> None:
    assert _select_template("PLAYER_PERFORMANCE") == "player-performance-v1"
    assert _select_template("record") == "record-v1"
    assert _select_template("unknown") == "game-result-v1"
