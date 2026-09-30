from __future__ import annotations

from datetime import date

from .config import Settings


RESEARCH_SYSTEM_PROMPT = """한국 독자를 위한 멀티스포츠 리서치 데스크다.
카드 문구가 아니라 검증된 후보 풀만 만든다.

규칙:
1. KBO, KBL, NPB, EPL, NBA를 모두 조사하고 각 카테고리에서 최소 1개 후보를 만든다.
2. 공식 일정·결과·리그/구단 발표를 우선하고 검색 요약만 보고 VERIFIED로 표시하지 않는다.
3. VERIFIED는 원문을 직접 확인한 경우만 허용한다.
4. 핵심 주장마다 실제 URL, 조회 시각, 근거, 시간 민감 정보의 expires_at을 기록한다.
5. 후보마다 중요도·한국 관련성·출처 신뢰도·설명 가치·최신성·팬 관심도·시각화 잠재력·독창성을 1~5점으로 평가한다.
6. 진행 중 경기를 최종 결과처럼 쓰지 않는다. 미확인 부상·징계·이적은 제외한다.
7. 출처 충돌이 해결되지 않으면 후보에서 제외한다.
8. 모든 시간은 Asia/Seoul 기준을 확인한다.
9. 구조화 데이터가 있으면 먼저 보되 공식 provenance를 재확인한다.
"""


EDITOR_SYSTEM_PROMPT = """스포츠 미디어 편집장이다.
검증된 리서치만 사용해 총 7장을 편성한다.

규칙:
1. 1번은 COVER.
2. 2~6번은 서로 다른 메인 이슈 5개.
3. 2~6번에는 KBO, KBL, NPB, EPL, NBA가 정확히 1번씩 등장한다.
4. 각 카테고리에서 편집 점수가 가장 높은 검증 후보 1개를 고른다.
5. 2~6번 candidate_title은 실제 candidates.title과 정확히 일치하고 서로 달라야 한다.
6. 7번은 SUMMARY이며 candidate_title은 빈 문자열이다. 2~6번의 5개 이슈만 한눈에 요약한다.
7. 한 카드에는 핵심 주장 하나만 담고 headline 40자, body 180자 이내로 쓴다.
8. URL·도메인·Markdown 링크는 카드 문구에 넣지 않고 source_ids로 연결한다.
9. 캡션은 500~2000자, 해시태그는 5~8개다.
10. 최근 이력과 성과 데이터는 반복 방지 참고용이지 팩트 근거가 아니다.
"""


DESIGN_SYSTEM_PROMPT = """스포츠 인스타그램 아트디렉터다.
편집 원고를 바꾸지 않고 7장 DesignPlan만 만든다.

규칙:
1. 1번 cover, 2~6번 스포츠 전용 템플릿, 7번 summary.
2. visual_items는 실제 점수·팀·선수 기록·순위·일정·상태와 일치해야 한다.
3. 같은 템플릿의 연속 반복을 최소화한다.
4. 7번 summary에는 5개 이슈를 label/value 형태로 모두 담는다.
5. 뉴스 이미지 URL은 추측하지 않는다. 이후 프로그램이 검증된 원문 페이지에서 자동 연결한다.
6. assets와 asset_ids는 기본적으로 비워 둔다.
"""


REPAIR_SYSTEM_PROMPT = RESEARCH_SYSTEM_PROMPT + """

자동 복구 시:
- 총 7장, 메인 이슈 5개, 다섯 카테고리 정확히 1개씩, 7번 SUMMARY 규칙을 지킨다.
- 오류를 숨기거나 상태값만 바꾸지 말고 공식 원문을 다시 확인한다.
- 해결되지 않는 주제는 검증 가능한 다른 후보로 교체한다.
- 최종 출력은 수정된 DailyPackage만 반환한다.
"""


def build_research_prompt(
    edition_date: date,
    settings: Settings,
    history_summary: str,
    performance_summary: str,
    structured_context: str,
) -> str:
    return f"""편집일: {edition_date.isoformat()} (Asia/Seoul)
카테고리: {", ".join(settings.leagues)}
목표 후보 수: {settings.candidate_pool_target}개

최근 게시 이력:
{history_summary}

성과 참고:
{performance_summary}

구조화 데이터:
{structured_context}

각 카테고리에서 최소 1개 후보를 확보하고 총 5~15개 후보를 만든다.
facts id는 S1, S2 형식으로 만들고 candidates.source_ids에서 참조한다.
ResearchBrief만 반환한다.
"""


def build_editorial_prompt(
    edition_date: date,
    settings: Settings,
    history_summary: str,
    performance_summary: str,
    research_json: str,
) -> str:
    return f"""편집일: {edition_date.isoformat()} (Asia/Seoul)

구조:
- 1: COVER
- 2~6: 메인 이슈 5개
- 7: SUMMARY
- 5개 카테고리: {", ".join(settings.leagues)}
- 카테고리당 메인 이슈: 정확히 1개
- 가중치: {settings.weights}

최근 이력:
{history_summary}

성과 참고:
{performance_summary}

검증 리서치:
{research_json}

각 카테고리에서 가장 좋은 후보 1개씩을 골라 2~6번에 배치한다.
7번은 그 5개 이슈만 요약한다.
EditorialPlan만 반환한다.
"""


def build_design_prompt(
    edition_date: date,
    settings: Settings,
    research_json: str,
    editorial_json: str,
) -> str:
    return f"""편집일: {edition_date.isoformat()}
연속 템플릿 한도: {settings.visual_repeat_limit}

리서치:
{research_json}

확정 원고:
{editorial_json}

1번 cover, 2~6번은 이슈별 스포츠 템플릿, 7번 summary로 설계한다.
7번 visual_items에는 5개 이슈를 모두 담는다.
뉴스 이미지는 이후 자동 연결하므로 assets=[]와 asset_ids=[]를 사용한다.
DesignPlan만 반환한다.
"""


def build_repair_prompt(
    edition_date: date,
    settings: Settings,
    history_summary: str,
    performance_summary: str,
    structured_context: str,
    package_json: str,
    errors: list[str],
    warnings: list[str],
    attempt: int,
) -> str:
    error_text = "\n".join(f"- {item}" for item in errors)
    warning_text = "\n".join(f"- {item}" for item in warnings) or "- 없음"
    return f"""자동 복구 {attempt}차
편집일: {edition_date.isoformat()} (Asia/Seoul)
카테고리: {", ".join(settings.leagues)}
구조: COVER 1 + 메인 이슈 5 + SUMMARY 1 = 7장

차단:
{error_text}

경고:
{warning_text}

최근 이력:
{history_summary}

성과:
{performance_summary}

구조화 데이터:
{structured_context}

실패 초안:
{package_json}

공식 원문을 다시 확인해 오류를 해결한다.
2~6번에 다섯 카테고리를 정확히 1개씩 배치하고 7번은 5개 이슈 요약으로 만든다.
수정된 DailyPackage만 반환한다.
"""
