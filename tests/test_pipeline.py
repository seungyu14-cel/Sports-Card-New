from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from sports_card_news.config import load_settings
from sports_card_news.history import recent_publication_summary
from sports_card_news.models import CardLeague, FactStatus, RightsStatus, VisualTemplate
from sports_card_news.pipeline import load_package, run_daily
from sports_card_news.validation import validate_package


ROOT = Path(__file__).parents[1]


def test_demo_package_passes_validation() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    report = validate_package(package, settings)
    assert report.ok, report.errors
    assert len(package.cards) == 6
    assert [card.league.value for card in package.cards] == [
        "COVER",
        "KBO",
        "KBL",
        "NPB",
        "EPL",
        "NBA",
    ]
    assert len({candidate.sport for candidate in package.candidates}) == 3
    assert 500 <= len(package.caption) <= 2000


def test_daily_fixture_renders_png_and_review_files(tmp_path: Path) -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    destination, report = run_daily(
        edition_date=date(2026, 9, 29),
        output_root=tmp_path,
        settings=settings,
        fixture=ROOT / "fixtures/demo_package.json",
    )
    assert report.ok
    assert len(list(destination.glob("card-*.png"))) == 6
    assert (destination / "editorial-review.md").exists()
    assert (destination / "validation.md").exists()


def test_unknown_source_reference_is_blocked() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    broken_candidate = package.candidates[0].model_copy(update={"source_ids": ["S999"]})
    broken = package.model_copy(update={"candidates": [broken_candidate, *package.candidates[1:]]})
    report = validate_package(broken, settings)
    assert not report.ok
    assert any("S999" in error for error in report.errors)


def test_card_copy_with_markdown_or_url_is_blocked() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    linked_card = package.cards[1].model_copy(
        update={"body": "공식 발표를 확인했습니다. ([example.com](https://example.com/news))"}
    )
    linked = package.model_copy(update={"cards": [package.cards[0], linked_card, *package.cards[2:]]})

    report = validate_package(linked, settings)

    assert not report.ok
    assert any("URL·도메인·Markdown 링크" in error for error in report.errors)


def test_legacy_package_without_card_layout_fields_is_migrated(tmp_path: Path) -> None:
    payload = json.loads((ROOT / "fixtures/demo_package.json").read_text(encoding="utf-8"))
    for card in payload["cards"]:
        card.pop("visual_template")
        card.pop("league")
    legacy_path = tmp_path / "legacy-package.json"
    legacy_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    package = load_package(legacy_path)

    assert package.cards[0].visual_template == VisualTemplate.COVER
    assert all(card.visual_template == VisualTemplate.AUTO for card in package.cards[1:])
    assert [card.league.value for card in package.cards] == [
        "COVER",
        "KBO",
        "KBL",
        "NPB",
        "EPL",
        "NBA",
    ]


def test_wrong_league_page_order_is_blocked() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    wrong_card = package.cards[1].model_copy(update={"league": CardLeague.NBA})
    wrong = package.model_copy(update={"cards": [package.cards[0], wrong_card, *package.cards[2:]]})

    report = validate_package(wrong, settings)

    assert not report.ok
    assert any("카드 리그 순서" in error for error in report.errors)


def test_rights_needs_review_is_warning_not_blocking() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    needs_review = package.model_copy(update={"rights_status": RightsStatus.NEEDS_REVIEW})

    report = validate_package(needs_review, settings)

    assert report.ok, report.errors
    assert any("시각 소재 권리가 '확인 필요'" in warning for warning in report.warnings)


def test_live_generation_repairs_conflicts_and_writes_recovery_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    valid = load_package(ROOT / "fixtures/demo_package.json")
    conflicted_fact = valid.facts[0].model_copy(update={"status": FactStatus.CONFLICT})
    invalid = valid.model_copy(update={"facts": [conflicted_fact, *valid.facts[1:]]})
    repair_calls: list[list[str]] = []

    monkeypatch.setattr(
        "sports_card_news.pipeline.generate_daily_package",
        lambda *_args, **_kwargs: invalid,
    )

    def fake_repair(*_args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        repair_calls.append(list(kwargs["errors"]))  # type: ignore[arg-type]
        return valid

    monkeypatch.setattr("sports_card_news.pipeline.repair_daily_package", fake_repair)

    destination, report = run_daily(
        edition_date=date(2026, 9, 29),
        output_root=tmp_path,
        settings=settings,
    )

    assert report.ok
    assert len(repair_calls) == 1
    assert any("출처 충돌: S1" in error for error in repair_calls[0])
    assert any("자동 복구 1회" in warning for warning in report.warnings)
    recovery_log = (destination / "recovery-log.md").read_text(encoding="utf-8")
    assert "1차 재조사 사유" in recovery_log
    assert "모든 차단 항목이 해결" in recovery_log
    assert len(list(destination.glob("card-*.png"))) == 6

    # A clean rerun for the same edition must not leave a stale recovery record.
    run_daily(
        edition_date=date(2026, 9, 29),
        output_root=tmp_path,
        settings=settings,
        fixture=ROOT / "fixtures/demo_package.json",
    )
    assert not (destination / "recovery-log.md").exists()


def test_live_generation_stops_after_bounded_repair_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = replace(
        load_settings(ROOT / "config/settings.toml"),
        auto_repair_attempts=2,
    )
    valid = load_package(ROOT / "fixtures/demo_package.json")
    conflicted_fact = valid.facts[0].model_copy(update={"status": FactStatus.CONFLICT})
    invalid = valid.model_copy(update={"facts": [conflicted_fact, *valid.facts[1:]]})
    attempts: list[int] = []

    monkeypatch.setattr(
        "sports_card_news.pipeline.generate_daily_package",
        lambda *_args, **_kwargs: invalid,
    )

    def failed_repair(*_args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        attempts.append(int(kwargs["attempt"]))
        return invalid

    monkeypatch.setattr("sports_card_news.pipeline.repair_daily_package", failed_repair)

    with pytest.raises(ValueError, match="자동 복구 횟수 안에"):
        run_daily(
            edition_date=date(2026, 9, 29),
            output_root=tmp_path,
            settings=settings,
        )

    assert attempts == [1, 2]
    assert not (tmp_path / "2026-09-29").exists()


def test_recent_history_uses_only_prior_seven_days(tmp_path: Path) -> None:
    package = json.loads((ROOT / "fixtures/demo_package.json").read_text(encoding="utf-8"))
    for day in ("2026-09-20", "2026-09-27", "2026-09-29"):
        folder = tmp_path / day
        folder.mkdir()
        package["edition_date"] = day
        (folder / "package.json").write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
    summary = recent_publication_summary(tmp_path, date(2026, 9, 29), days=7)
    assert "2026-09-27" in summary
    assert "2026-09-20" not in summary
    assert "2026-09-29" not in summary
