from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .config import Settings
from .models import DailyPackage


@dataclass
class VisualQAReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_markdown(self) -> str:
        status = "[PASS] Visual QA 통과" if self.ok else "[FAIL] Visual QA 실패"
        parts = [f"# Visual QA\n\n{status}"]
        if self.errors:
            parts.append("## 차단 항목\n\n" + "\n".join(f"- {item}" for item in self.errors))
        if self.warnings:
            parts.append("## 디자인 검토 권고\n\n" + "\n".join(f"- {item}" for item in self.warnings))
        if not self.errors and not self.warnings:
            parts.append("모바일 가독성·정보 밀도·레이아웃 반복 자동 검사에서 경고가 없습니다.")
        return "\n\n".join(parts) + "\n"


def run_visual_qa(
    package: DailyPackage,
    paths: list[Path],
    settings: Settings,
) -> VisualQAReport:
    report = VisualQAReport()
    expected_size = (settings.output_width, settings.output_height)

    if len(paths) != 7:
        report.errors.append(f"카드 이미지는 정확히 7장이어야 합니다: {len(paths)}장")

    for card, path in zip(package.cards, paths, strict=False):
        if len(card.headline) > 36:
            report.warnings.append(f"{card.slide}번 제목이 모바일에서 길 수 있습니다: {len(card.headline)}자")
        if len(card.body) > 150:
            report.warnings.append(f"{card.slide}번 본문 정보 밀도가 높습니다: {len(card.body)}자")
        if 2 <= card.slide <= 6 and len(card.visual_items) < 2:
            report.warnings.append(f"{card.slide}번 이슈 카드의 데이터 포인트가 1개뿐입니다.")
        if not path.exists() or path.stat().st_size == 0:
            report.errors.append(f"렌더링 파일이 비어 있습니다: {path.name}")
            continue
        with Image.open(path) as image:
            if image.format != "PNG":
                report.errors.append(f"PNG가 아닌 카드입니다: {path.name}")
            if image.size != expected_size:
                report.errors.append(f"카드 크기가 다릅니다: {path.name}={image.size}")
            if image.mode != "RGB":
                report.errors.append(f"RGB가 아닌 카드입니다: {path.name}={image.mode}")

    issue_cards = package.cards[1:6]
    templates = [card.visual_template.value for card in issue_cards]
    counts = Counter(templates)
    if counts and counts.most_common(1)[0][1] >= 4:
        name, count = counts.most_common(1)[0]
        report.warnings.append(f"5개 이슈 중 {count}개가 같은 템플릿({name})입니다.")

    headlines = [card.headline.strip() for card in issue_cards]
    if len(set(headlines)) != 5:
        report.errors.append("2~6번 메인 이슈 headline은 5개 모두 서로 달라야 합니다.")

    if package.cards and package.cards[-1].visual_template.value != "summary":
        report.errors.append("7번 마무리 카드는 summary 템플릿이어야 합니다.")

    if package.cards and len(package.cards[-1].visual_items) < 5:
        report.warnings.append("7번 요약 카드에 5개 이슈가 모두 시각 항목으로 들어갔는지 확인하세요.")

    return report
