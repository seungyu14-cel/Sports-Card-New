from __future__ import annotations

import json
import zipfile
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from sports_card_news.config import load_settings
from sports_card_news.history import recent_publication_summary
from sports_card_news.models import (
    AssetType,
    CardLeague,
    FactStatus,
    RightsStatus,
    VerificationMethod,
    VisualAsset,
    VisualTemplate,
)
from sports_card_news.pipeline import load_package, run_daily
from sports_card_news.validation import validate_package


ROOT = Path(__file__).parents[1]


def test_demo_package_passes_validation() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    report = validate_package(package, settings)

    assert report.ok, report.errors
    assert len(package.cards) == 5
    assert package.cards[0].league.value == "COVER"
    assert package.cards[-1].league.value == "SUMMARY"

    issue_cards = package.cards[1:4]
    assert len(issue_cards) == 3
    assert len({card.candidate_title for card in issue_cards}) == 3
    counts = Counter(card.league.value for card in issue_cards)
    assert counts == {"KBO": 1, "MLB": 1, "NPB": 1}
    assert len(package.candidates) == 3
    assert 500 <= len(package.caption) <= 2000


def test_daily_fixture_renders_png_and_review_files(tmp_path: Path) -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    destination, report = run_daily(
        edition_date=date(2026, 9, 30),
        output_root=tmp_path,
        settings=settings,
        fixture=ROOT / "fixtures/demo_package.json",
    )

    assert report.ok
    assert len(list(destination.glob("card-*.png"))) == 5
    assert (destination / "editorial-review.md").exists()
    assert (destination / "validation.md").exists()
    assert (destination / "visual-qa.md").exists()

    manifest = json.loads((destination / "publish-manifest.json").read_text(encoding="utf-8"))
    assert manifest["cards"] == [f"card-{index:02d}.png" for index in range(1, 6)]

    with zipfile.ZipFile(destination / "instagram-carousel.zip") as archive:
        assert set(archive.namelist()) == {
            *(f"card-{index:02d}.png" for index in range(1, 6)),
            "caption-instagram.md",
            "alt-text.json",
            "sources.md",
            "visual-qa.md",
            "publish-manifest.json",
        }


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
    changed = package.model_copy(
        update={"cards": [package.cards[0], linked_card, *package.cards[2:]]}
    )

    report = validate_package(changed, settings)

    assert not report.ok
    assert any("URL·도메인·Markdown 링크" in error for error in report.errors)


def test_legacy_package_without_card_layout_fields_is_migrated(tmp_path: Path) -> None:
    payload = json.loads((ROOT / "fixtures/demo_package.json").read_text(encoding="utf-8"))
    for card in payload["cards"]:
        for key in (
            "visual_template",
            "league",
            "visual_title",
            "visual_items",
            "content_type",
            "kicker",
            "asset_ids",
            "candidate_title",
        ):
            card.pop(key, None)
    for fact in payload["facts"]:
        fact.pop("expires_at")
        fact.pop("verification_method")
        fact.pop("evidence")

    legacy_path = tmp_path / "legacy-package.json"
    legacy_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    package = load_package(legacy_path)

    assert package.cards[0].visual_template == VisualTemplate.COVER
    assert all(card.visual_template == VisualTemplate.AUTO for card in package.cards[1:])
    assert all(card.candidate_title for card in package.cards[1:4])
    assert package.cards[-1].league.value == "SUMMARY"
    assert package.cards[-1].candidate_title == ""
    assert all(
        fact.verification_method == VerificationMethod.SECONDARY_ONLY
        for fact in package.facts
    )


def test_card_candidate_league_mismatch_is_blocked() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    wrong_card = package.cards[1].model_copy(update={"league": CardLeague.MLB})
    wrong = package.model_copy(update={"cards": [package.cards[0], wrong_card, *package.cards[2:]]})

    report = validate_package(wrong, settings)

    assert not report.ok
    assert any("카테고리와 후보 카테고리가 다릅니다" in error for error in report.errors)


def test_flexible_issue_order_is_allowed() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    reordered = [
        package.cards[0],
        package.cards[2],
        package.cards[3],
        package.cards[1],
        package.cards[4],
    ]
    cards = [card.model_copy(update={"slide": index}) for index, card in enumerate(reordered, start=1)]
    changed = package.model_copy(update={"cards": cards})

    report = validate_package(changed, settings)

    assert report.ok, report.errors


def test_duplicate_category_in_three_issues_is_blocked() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    duplicate = package.cards[2].model_copy(
        update={
            "candidate_title": package.cards[1].candidate_title,
            "league": package.cards[1].league,
            "source_ids": package.cards[1].source_ids,
        }
    )
    changed = package.model_copy(
        update={"cards": [package.cards[0], package.cards[1], duplicate, *package.cards[3:]]}
    )

    report = validate_package(changed, settings)

    assert not report.ok
    assert any("정확히 1개씩" in error or "서로 다른 3개의 이슈" in error for error in report.errors)


def test_news_image_from_verified_source_is_allowed() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    asset = VisualAsset(
        id="A1",
        asset_type=AssetType.NEWS_IMAGE,
        title="KBO 기사 대표 이미지",
        source_url="https://example-cdn.invalid/kbo.jpg",
        source_fact_id="S1",
        rights_status=RightsStatus.NEWS_APPROVED,
        rights_note="프로젝트 운영 정책에 따라 뉴스 원문 이미지 사용 허용",
        credit="koreabaseball.com",
        usage_scope=["instagram_post"],
        license_evidence="사용자 운영 정책 승인",
        approved_for_publish=True,
    )
    card = package.cards[1].model_copy(update={"asset_ids": ["A1"]})
    changed = package.model_copy(
        update={
            "assets": [asset],
            "rights_status": RightsStatus.NEWS_APPROVED,
            "cards": [package.cards[0], card, *package.cards[2:]],
        }
    )

    report = validate_package(changed, settings)

    assert report.ok, report.errors


def test_unapproved_news_image_is_blocked() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    asset = VisualAsset(
        id="A1",
        asset_type=AssetType.NEWS_IMAGE,
        title="승인 안 된 이미지",
        source_url="https://example-cdn.invalid/kbo.jpg",
        source_fact_id="S1",
        rights_status=RightsStatus.NEEDS_REVIEW,
        rights_note="확인 전",
        credit="example",
        usage_scope=[],
        license_evidence="",
        approved_for_publish=False,
    )
    card = package.cards[1].model_copy(update={"asset_ids": ["A1"]})
    changed = package.model_copy(
        update={"assets": [asset], "cards": [package.cards[0], card, *package.cards[2:]]}
    )

    report = validate_package(changed, settings)

    assert not report.ok
    assert any("게시 승인되지 않은 시각 자산" in error for error in report.errors)


def test_search_snippet_cannot_be_marked_verified() -> None:
    settings = load_settings(ROOT / "config/settings.toml")
    package = load_package(ROOT / "fixtures/demo_package.json")
    snippet = package.facts[0].model_copy(
        update={"verification_method": VerificationMethod.SEARCH_SNIPPET}
    )
    changed = package.model_copy(update={"facts": [snippet, *package.facts[1:]]})

    report = validate_package(changed, settings)

    assert not report.ok
    assert any("원문을 직접 확인하지 않은 출처" in error for error in report.errors)


def test_live_generation_repairs_conflicts_and_writes_recovery_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = replace(load_settings(ROOT / "config/settings.toml"), allow_news_images=False)
    valid = load_package(ROOT / "fixtures/demo_package.json")
    conflicted = valid.facts[0].model_copy(update={"status": FactStatus.CONFLICT})
    invalid = valid.model_copy(update={"facts": [conflicted, *valid.facts[1:]]})
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
    assert len(list(destination.glob("card-*.png"))) == 5
    assert (destination / "recovery-log.md").exists()


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

