from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sports_card_news.config import load_settings
from sports_card_news.history import recent_publication_summary
from sports_card_news.models import RightsStatus
from sports_card_news.pipeline import load_package, run_daily
from sports_card_news.validation import validate_package


ROOT = Path(__file__).parents[1]


def test_demo_package_passes_validation() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    report = validate_package(package, settings)
    assert report.ok, report.errors
    assert len(package.cards) == 6
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


def test_rights_needs_review_is_warning_not_blocking() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    needs_review = package.model_copy(update={"rights_status": RightsStatus.NEEDS_REVIEW})

    report = validate_package(needs_review, settings)

    assert report.ok, report.errors
    assert any("시각 소재 권리가 '확인 필요'" in warning for warning in report.warnings)


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
