from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx

from .config import Settings
from .models import (
    AssetType,
    DailyPackage,
    FactStatus,
    RightsStatus,
    VerificationMethod,
    VisualAsset,
)


META_PATTERNS = (
    re.compile(
        r'<meta[^>]+property=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::url)?["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
        re.IGNORECASE,
    ),
)


def attach_verified_news_images(
    package: DailyPackage,
    settings: Settings,
) -> DailyPackage:
    """Attach article/official-page hero images to issue cards when project policy allows it.

    Only facts already marked as direct + verified are eligible. Image URLs are discovered
    from the source page metadata instead of being invented by the model.
    """
    if not settings.allow_news_images or not settings.auto_approve_verified_news_images:
        return package

    facts_by_id = {fact.id: fact for fact in package.facts}
    assets = list(package.assets)
    assets_by_source = {
        asset.source_fact_id: asset
        for asset in assets
        if asset.asset_type == AssetType.NEWS_IMAGE and asset.source_fact_id
    }
    next_id = _next_asset_id(assets)
    updated_cards = list(package.cards)

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SportsCardNews/1.2; +https://github.com/)"
    }
    try:
        client = httpx.Client(
            timeout=settings.news_image_timeout_seconds,
            follow_redirects=True,
            headers=headers,
        )
    except Exception:
        return package

    with client:
        for index, card in enumerate(updated_cards):
            if not 2 <= card.slide <= 6 or card.asset_ids:
                continue

            chosen_asset: VisualAsset | None = None
            for source_id in card.source_ids:
                fact = facts_by_id.get(source_id)
                if (
                    fact is None
                    or fact.status != FactStatus.VERIFIED
                    or fact.verification_method != VerificationMethod.DIRECT
                ):
                    continue

                existing = assets_by_source.get(source_id)
                if existing is not None:
                    chosen_asset = existing
                    break

                image_url = _discover_hero_image(client, fact.url)
                if not image_url:
                    continue

                domain = (urlparse(fact.url).hostname or "").removeprefix("www.")
                chosen_asset = VisualAsset(
                    id=f"A{next_id}",
                    asset_type=AssetType.NEWS_IMAGE,
                    title=f"{fact.title} 대표 이미지",
                    source_url=image_url,
                    source_fact_id=fact.id,
                    rights_status=RightsStatus.NEWS_APPROVED,
                    rights_note="프로젝트 운영 정책에 따라 검증된 뉴스·공식 원문 페이지에 포함된 대표 이미지 사용 허용",
                    credit=domain or fact.title,
                    usage_scope=["instagram_post"],
                    license_evidence=(
                        "사용자가 뉴스 원문에 포함된 이미지를 카드뉴스에 사용할 수 있다고 "
                        "승인한 운영 정책에 따라 자동 승인"
                    ),
                    approved_for_publish=True,
                )
                next_id += 1
                assets.append(chosen_asset)
                assets_by_source[source_id] = chosen_asset
                break

            if chosen_asset is not None:
                updated_cards[index] = card.model_copy(
                    update={"asset_ids": [chosen_asset.id]}
                )

    if not assets:
        return package

    return package.model_copy(
        update={
            "assets": assets,
            "cards": updated_cards,
            "rights_status": RightsStatus.NEWS_APPROVED,
        }
    )


def _discover_hero_image(client: httpx.Client, page_url: str) -> str:
    try:
        response = client.get(page_url)
        response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return ""

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower():
        return ""

    text = response.text[:1_500_000]
    for pattern in META_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        candidate = urljoin(str(response.url), match.group(1).strip())
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return candidate
    return ""


def _next_asset_id(assets: list[VisualAsset]) -> int:
    highest = 0
    for asset in assets:
        try:
            highest = max(highest, int(asset.id.removeprefix("A")))
        except ValueError:
            continue
    return highest + 1
