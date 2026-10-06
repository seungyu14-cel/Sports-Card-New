from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from openai import OpenAI
from pydantic import Field, field_validator

from .config import Settings
from .models import StrictModel
from .studio_renderer import render_studio_package
from .supabase_store import SupabaseStore


ProgressCallback = Callable[[str, int, str], None]


class AgentProfile(StrictModel):
    id: str
    name: str
    title: str
    team: str
    responsibility: str
    stage: str
    sports: list[str] = Field(default_factory=list)


class ThemeProfile(StrictModel):
    id: str
    sport: str
    name: str
    primary: str
    secondary: str
    accent: str
    paper: str
    description: str


class StudioRequest(StrictModel):
    edition_date: date
    sport: Literal["야구", "농구", "축구", "배구", "기타"]
    league: str = Field(min_length=1, max_length=40)
    topic: str = Field(min_length=2, max_length=200)
    source_notes: str = Field(default="", max_length=12000)
    theme_id: str
    archive_to_db: bool = True


class AgentContribution(StrictModel):
    agent_id: str
    agent_name: str
    title: str
    team: str
    task: str
    result: str = Field(min_length=5, max_length=1200)
    confidence: float = Field(ge=0, le=1)


class VerifiedFact(StrictModel):
    key: str
    claim: str = Field(min_length=4, max_length=500)
    source_url: str = Field(default="", max_length=2048)
    confidence: float = Field(ge=0, le=1)


class ResearchStage(StrictModel):
    contributions: list[AgentContribution] = Field(min_length=4, max_length=8)
    facts: list[VerifiedFact] = Field(min_length=3, max_length=20)
    recommended_angle: str = Field(min_length=10, max_length=500)
    risks: list[str] = Field(default_factory=list, max_length=10)


class CardCopy(StrictModel):
    slide: int = Field(ge=1, le=10)
    role: str = Field(min_length=2, max_length=40)
    kicker: str = Field(default="", max_length=32)
    headline: str = Field(min_length=2, max_length=48)
    body: str = Field(min_length=10, max_length=260)
    key_stat: str = Field(default="", max_length=80)
    visual_direction: str = Field(default="", max_length=240)


class EditorialStage(StrictModel):
    contributions: list[AgentContribution] = Field(min_length=3, max_length=6)
    master_headline: str = Field(min_length=4, max_length=70)
    editorial_angle: str = Field(min_length=10, max_length=500)
    cards: list[CardCopy] = Field(min_length=7, max_length=7)

    @field_validator("cards")
    @classmethod
    def validate_slides(cls, items: list[CardCopy]) -> list[CardCopy]:
        if sorted(item.slide for item in items) != list(range(1, 8)):
            raise ValueError("카드는 1~7번이 각각 한 장씩 필요합니다.")
        return sorted(items, key=lambda item: item.slide)


class SocialDraft(StrictModel):
    post_title: str = Field(min_length=4, max_length=80)
    caption: str = Field(min_length=80, max_length=1200)
    hashtags: list[str] = Field(min_length=5, max_length=12)

    @field_validator("hashtags")
    @classmethod
    def validate_tags(cls, items: list[str]) -> list[str]:
        return [item if item.startswith("#") else "#" + item.replace(" ", "") for item in items]


class CreativeStage(StrictModel):
    contributions: list[AgentContribution] = Field(min_length=6, max_length=10)
    card_visual_directions: list[str] = Field(min_length=7, max_length=7)
    social: SocialDraft
    shortform_hook: str = Field(min_length=5, max_length=160)


class AgentFeedback(StrictModel):
    agent_id: str
    agent_name: str
    score: int = Field(ge=1, le=100)
    what_worked: str = Field(min_length=5, max_length=500)
    improve_next: str = Field(min_length=5, max_length=500)
    learning_rule: str = Field(min_length=5, max_length=500)


class FeedbackStage(StrictModel):
    feedback: list[AgentFeedback] = Field(min_length=8, max_length=24)
    overall_score: int = Field(ge=1, le=100)
    final_editor_note: str = Field(min_length=10, max_length=800)


class StudioPackage(StrictModel):
    session_id: str
    edition_date: str
    sport: str
    league: str
    topic: str
    theme: ThemeProfile
    master_headline: str
    editorial_angle: str
    agent_outputs: list[AgentContribution]
    facts: list[VerifiedFact]
    risks: list[str]
    cards: list[CardCopy]
    social: SocialDraft
    shortform_hook: str
    feedback: list[AgentFeedback]
    overall_score: int
    final_editor_note: str
    needs_human_approval: bool = True
    generated_at: datetime


AGENTS: tuple[AgentProfile, ...] = (
    AgentProfile(id="kim-doyoon", name="김도윤", title="편집국장", team="편집국", responsibility="최종 뉴스 가치·정확성·발행 품질 승인", stage="editorial"),
    AgentProfile(id="seo-yujin", name="서유진", title="부편집국장", team="편집국", responsibility="편집회의 조율·톤앤매너·중복 제거", stage="editorial"),
    AgentProfile(id="park-jihoon", name="박지훈", title="데이터저널리즘 팀장", team="데이터팀", responsibility="경기·선수·팀 숫자 데이터 검증", stage="research"),
    AgentProfile(id="lee-seojun", name="이서준", title="경기운영 데이터 매니저", team="데이터팀", responsibility="일정·경기상태·스코어·시간 기준 확인", stage="research"),
    AgentProfile(id="han-yerin", name="한예린", title="팩트체크 팀장", team="검증팀", responsibility="출처 교차검증·오보 위험 차단", stage="research"),
    AgentProfile(id="jung-yujin", name="정유진", title="야구 데스크", team="취재팀", responsibility="KBO·MLB·NPB 뉴스 가치 판단", stage="research", sports=["야구"]),
    AgentProfile(id="kim-taehoon", name="김태훈", title="KBO 담당 기자", team="취재팀", responsibility="KBO 경기·선수·현장 이슈 정리", stage="research", sports=["야구"]),
    AgentProfile(id="jung-minwoo", name="정민우", title="MLB 담당 기자", team="취재팀", responsibility="MLB 경기·기록·선수 이슈 정리", stage="research", sports=["야구"]),
    AgentProfile(id="lee-hyunseok", name="이현석", title="NPB 담당 기자", team="취재팀", responsibility="NPB 경기·선수 뉴스 정리", stage="research", sports=["야구"]),
    AgentProfile(id="park-junyoung", name="박준영", title="축구 데스크", team="취재팀", responsibility="EPL·유럽축구 경기 흐름·전술·순위 영향 판단", stage="research", sports=["축구"]),
    AgentProfile(id="kim-minseong", name="김민성", title="EPL 담당 기자", team="취재팀", responsibility="EPL 경기·선수·감독 뉴스 정리", stage="research", sports=["축구"]),
    AgentProfile(id="jang-minjun", name="장민준", title="농구 데스크", team="취재팀", responsibility="NBA·KBL 경기 흐름·기록 가치 판단", stage="research", sports=["농구"]),
    AgentProfile(id="kim-jaehyun", name="김재현", title="NBA 담당 기자", team="취재팀", responsibility="NBA 경기·선수·트레이드 이슈 정리", stage="research", sports=["농구"]),
    AgentProfile(id="oh-sehoon", name="오세훈", title="KBL 담당 기자", team="취재팀", responsibility="KBL 경기·국내 농구 이슈 정리", stage="research", sports=["농구"]),
    AgentProfile(id="choi-seoyoon", name="최서윤", title="배구 데스크", team="취재팀", responsibility="V-리그 경기·선수·순위 이슈 판단", stage="research", sports=["배구"]),
    AgentProfile(id="kang-jiwoo", name="강지우", title="스포츠 콘텐츠 에디터", team="콘텐츠팀", responsibility="기사·데이터를 카드뉴스 문장으로 재구성", stage="editorial"),
    AgentProfile(id="yoon-seoa", name="윤서아", title="카드뉴스 콘텐츠 디렉터", team="콘텐츠팀", responsibility="페이지 흐름·정보 위계·비주얼 방향 설계", stage="creative"),
    AgentProfile(id="jung-harin", name="정하린", title="스포츠 그래픽 디자이너", team="콘텐츠팀", responsibility="스코어·선수·경기 그래픽 방향 설계", stage="creative"),
    AgentProfile(id="kim-seohyun", name="김서현", title="데이터 비주얼 디자이너", team="콘텐츠팀", responsibility="기록·순위·비교 정보 시각화", stage="creative"),
    AgentProfile(id="lim-hyunwoo", name="임현우", title="소셜미디어 팀장", team="배포팀", responsibility="SNS 채널별 발행 전략·제목 방향 결정", stage="creative"),
    AgentProfile(id="choi-jimin", name="최지민", title="Instagram 에디터", team="배포팀", responsibility="인스타 캡션·해시태그·CTA 최적화", stage="creative"),
    AgentProfile(id="park-soyeon", name="박소연", title="숏폼 콘텐츠 PD", team="배포팀", responsibility="Reels·Shorts 전환용 훅 기획", stage="creative"),
    AgentProfile(id="kim-donghyuk", name="김동혁", title="영상 편집자", team="배포팀", responsibility="영상 전환 시 장면 순서와 강조 포인트 설계", stage="creative"),
)


THEMES: tuple[ThemeProfile, ...] = (
    ThemeProfile(id="baseball-green", sport="야구", name="Diamond Green", primary="#123F2F", secondary="#1F6B4E", accent="#B6F36B", paper="#F4F1E8", description="잔디와 스코어보드에서 가져온 묵직한 그린"),
    ThemeProfile(id="basketball-orange", sport="농구", name="Court Orange", primary="#8F3B12", secondary="#E56A1F", accent="#FFD166", paper="#FFF3E8", description="코트와 농구공을 연상시키는 강한 오렌지"),
    ThemeProfile(id="soccer-red", sport="축구", name="Pitch Red", primary="#6F1717", secondary="#C92A2A", accent="#FFB3A7", paper="#FFF0ED", description="속도감과 긴장감을 살린 레드"),
    ThemeProfile(id="volleyball-blue", sport="배구", name="Volley Blue", primary="#133E7C", secondary="#2767B5", accent="#92D5FF", paper="#EEF6FF", description="코트 라인과 청량감을 살린 블루"),
    ThemeProfile(id="editorial-purple", sport="기타", name="Editorial Purple", primary="#3F246D", secondary="#7147A8", accent="#D8B4FE", paper="#F7F1FF", description="기타 종목에 사용하는 에디토리얼 퍼플"),
)


def public_agents() -> list[dict[str, Any]]:
    return [agent.model_dump(mode="json") for agent in AGENTS]


def public_themes() -> list[dict[str, Any]]:
    return [theme.model_dump(mode="json") for theme in THEMES]


def theme_for(theme_id: str, sport: str) -> ThemeProfile:
    for theme in THEMES:
        if theme.id == theme_id:
            return theme
    for theme in THEMES:
        if theme.sport == sport:
            return theme
    return THEMES[-1]


def active_agents(sport: str, league: str) -> list[AgentProfile]:
    core = [agent for agent in AGENTS if not agent.sports]
    specialists = [agent for agent in AGENTS if sport in agent.sports]
    if sport == "야구":
        league_upper = league.upper()
        specialist_ids = {"jung-yujin"}
        if "KBO" in league_upper:
            specialist_ids.add("kim-taehoon")
        elif "MLB" in league_upper:
            specialist_ids.add("jung-minwoo")
        elif "NPB" in league_upper:
            specialist_ids.add("lee-hyunseok")
        else:
            specialist_ids.update({"kim-taehoon", "jung-minwoo", "lee-hyunseok"})
        specialists = [agent for agent in specialists if agent.id in specialist_ids]
    elif sport == "농구":
        league_upper = league.upper()
        specialist_ids = {"jang-minjun"}
        specialist_ids.add("kim-jaehyun" if "NBA" in league_upper else "oh-sehoon")
        specialists = [agent for agent in specialists if agent.id in specialist_ids]
    elif sport == "축구":
        specialists = [agent for agent in specialists if agent.id in {"park-junyoung", "kim-minseong"}]
    return core + specialists


def run_studio(
    request: StudioRequest,
    *,
    output_root: str | Path,
    settings: Settings,
    demo: bool = False,
    progress: ProgressCallback | None = None,
) -> tuple[Path, StudioPackage]:
    notify = progress or (lambda _stage, _percent, _message: None)
    theme = theme_for(request.theme_id, request.sport)
    session_id = f"{request.edition_date:%Y%m%d}-{uuid.uuid4().hex[:8]}"
    store = SupabaseStore.from_env() if SupabaseStore.is_configured() else None
    context, learning_memory = _load_context(store, request)

    if demo:
        notify("research", 22, "박지훈·이서준·한예린이 데모 자료를 정리했습니다.")
        package = _demo_package(request, theme, session_id)
    else:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("라이브 편집국 제작에는 OPENAI_API_KEY가 필요합니다.")
        client = OpenAI(timeout=settings.api_timeout_seconds, max_retries=0)
        package = _generate_live(
            client,
            request,
            theme,
            session_id,
            context,
            learning_memory,
            settings,
            notify,
        )

    notify("render", 90, "윤서아·정하린·김서현의 테마 규칙으로 카드를 렌더링합니다.")
    destination = Path(output_root) / "studio" / session_id
    destination.mkdir(parents=True, exist_ok=True)
    render_studio_package(package, destination)
    (destination / "studio-package.json").write_text(
        package.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (destination / "caption-instagram.md").write_text(
        f"{package.social.post_title}\n\n{package.social.caption}\n\n"
        + " ".join(package.social.hashtags)
        + "\n",
        encoding="utf-8",
    )
    if request.archive_to_db and store is not None:
        notify("archive", 96, "오세진 아카이브 역할로 결과와 피드백을 DB에 기록합니다.")
        _archive(store, request, package)
    notify("complete", 100, "편집국 제작·디자인·SNS·사후 피드백이 완료되었습니다.")
    return destination, package


def load_studio_package(path: str | Path) -> StudioPackage:
    return StudioPackage.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _load_context(
    store: SupabaseStore | None,
    request: StudioRequest,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if store is None:
        return [], []
    try:
        reports = store.reports_for_date(request.edition_date)
        league = request.league.upper()
        selected = [
            row for row in reports
            if league in str((row.get("payload") or {}).get("league", "")).upper()
            or league in str(row.get("game_id", "")).upper()
        ]
        feedback = store.select(
            "agent_feedback",
            params={
                "sport": f"eq.{request.sport}",
                "order": "created_at.desc",
                "limit": "30",
            },
        )
        return selected[:12], feedback
    except Exception:
        return [], []


def _generate_live(
    client: OpenAI,
    request: StudioRequest,
    theme: ThemeProfile,
    session_id: str,
    context: list[dict[str, Any]],
    learning_memory: list[dict[str, Any]],
    settings: Settings,
    notify: ProgressCallback,
) -> StudioPackage:
    agents = active_agents(request.sport, request.league)
    research_agents = [agent for agent in agents if agent.stage == "research"]
    editorial_agents = [agent for agent in agents if agent.stage == "editorial"]
    creative_agents = [agent for agent in agents if agent.stage == "creative"]

    notify("research", 15, "데이터팀·취재팀이 저장된 사실과 최신 결핍 정보를 점검합니다.")
    research_prompt = {
        "request": request.model_dump(mode="json"),
        "agents": [agent.model_dump(mode="json") for agent in research_agents],
        "supabase_game_reports": context,
        "manual_source_notes": request.source_notes,
        "past_learning_rules": [
            {
                "agent_name": row.get("agent_name"),
                "learning_rule": row.get("learning_rule"),
                "improve_next": row.get("improve_next"),
            }
            for row in learning_memory[:20]
        ],
    }
    research_kwargs: dict[str, Any] = {
        "model": os.getenv("OPENAI_STUDIO_MODEL", "gpt-6.1-sol"),
        "reasoning": {"effort": settings.reasoning_effort},
        "instructions": _research_instructions(),
        "input": json.dumps(research_prompt, ensure_ascii=False),
        "text_format": ResearchStage,
        "max_output_tokens": 5000,
        "store": False,
    }
    if not context and not request.source_notes.strip():
        research_kwargs.update(
            {
                "tools": [
                    {
                        "type": "web_search",
                        "filters": {"allowed_domains": list(settings.trusted_domains)},
                        "external_web_access": True,
                    }
                ],
                "tool_choice": "required",
                "include": ["web_search_call.action.sources"],
            }
        )
    research_response = client.responses.parse(**research_kwargs)
    research = _require_parsed(research_response, "리서치")

    notify("editorial", 42, "서유진·강지우·김도윤이 7장 원고와 편집 각도를 확정합니다.")
    editorial_response = client.responses.parse(
        model=os.getenv("OPENAI_STUDIO_MODEL", "gpt-6.1-sol"),
        reasoning={"effort": settings.reasoning_effort},
        instructions=_editorial_instructions(),
        input=json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "agents": [agent.model_dump(mode="json") for agent in editorial_agents],
                "research": research.model_dump(mode="json"),
            },
            ensure_ascii=False,
        ),
        text_format=EditorialStage,
        max_output_tokens=4500,
        store=False,
    )
    editorial = _require_parsed(editorial_response, "편집")

    notify("creative", 66, "콘텐츠팀·배포팀이 디자인 방향과 SNS 문구를 제작합니다.")
    creative_response = client.responses.parse(
        model=os.getenv("OPENAI_STUDIO_MODEL", "gpt-6.1-sol"),
        reasoning={"effort": "low"},
        instructions=_creative_instructions(),
        input=json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "theme": theme.model_dump(mode="json"),
                "agents": [agent.model_dump(mode="json") for agent in creative_agents],
                "facts": [fact.model_dump(mode="json") for fact in research.facts],
                "cards": [card.model_dump(mode="json") for card in editorial.cards],
            },
            ensure_ascii=False,
        ),
        text_format=CreativeStage,
        max_output_tokens=4000,
        store=False,
    )
    creative = _require_parsed(creative_response, "디자인·배포")
    cards = [
        card.model_copy(update={"visual_direction": creative.card_visual_directions[index]})
        for index, card in enumerate(editorial.cards)
    ]

    notify("feedback", 82, "각 담당자가 자신의 작업을 평가하고 다음 제작 규칙을 작성합니다.")
    feedback_response = client.responses.parse(
        model=os.getenv("OPENAI_STUDIO_MODEL", "gpt-6.1-sol"),
        reasoning={"effort": "low"},
        instructions=_feedback_instructions(),
        input=json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "active_agents": [agent.model_dump(mode="json") for agent in agents],
                "research": research.model_dump(mode="json"),
                "editorial": editorial.model_dump(mode="json"),
                "creative": creative.model_dump(mode="json"),
                "previous_learning": learning_memory[:20],
            },
            ensure_ascii=False,
        ),
        text_format=FeedbackStage,
        max_output_tokens=4500,
        store=False,
    )
    feedback = _require_parsed(feedback_response, "사후평가")

    return StudioPackage(
        session_id=session_id,
        edition_date=request.edition_date.isoformat(),
        sport=request.sport,
        league=request.league,
        topic=request.topic,
        theme=theme,
        master_headline=editorial.master_headline,
        editorial_angle=editorial.editorial_angle,
        agent_outputs=[
            *research.contributions,
            *editorial.contributions,
            *creative.contributions,
        ],
        facts=research.facts,
        risks=research.risks,
        cards=cards,
        social=creative.social,
        shortform_hook=creative.shortform_hook,
        feedback=feedback.feedback,
        overall_score=feedback.overall_score,
        final_editor_note=feedback.final_editor_note,
        needs_human_approval=True,
        generated_at=datetime.now(timezone.utc),
    )


def _require_parsed(response: Any, stage: str) -> Any:
    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
        raise RuntimeError(f"{stage} 단계에서 구조화된 결과를 받지 못했습니다.")
    return parsed


def _research_instructions() -> str:
    return """스포츠 데일리 카드 뉴스 제작소의 데이터·취재 데스크다.
각 agent의 책임에 맞춰 contribution을 하나씩 작성한다.
Supabase game report와 사용자가 제공한 source_notes를 사실의 최우선 근거로 사용한다.
웹검색이 활성화된 경우에도 주제에 필요한 최신 정보만 보강한다.
숫자·스코어·선수 소속·인터뷰를 추측하지 않는다.
facts에는 카드뉴스에서 직접 사용할 수 있는 검증 사실만 넣는다.
이전 learning_rule은 표현 방식 개선에만 사용하며 과거 사실을 현재 사실로 재사용하지 않는다."""


def _editorial_instructions() -> str:
    return """스포츠 데일리 카드 뉴스 제작소 편집국이다.
리서치 facts 범위 안에서만 최종 원고를 작성한다.
김도윤은 뉴스 가치와 최종 품질, 서유진은 흐름과 중복, 강지우는 문장 가독성을 담당한다.
총 7장 구조는 1 표지 / 2 경기·이슈 핵심 / 3 TOP1 / 4 TOP2 / 5 TOP3 / 6 데이터·의미 / 7 한눈 요약·CTA다.
한 카드 한 메시지 원칙을 지키고 모바일에서 3초 안에 이해되는 문장을 사용한다.
사실에 없는 숫자나 인용을 새로 만들지 않는다."""


def _creative_instructions() -> str:
    return """스포츠 카드뉴스 디자인·배포 데스크다.
원고의 사실과 핵심 문장을 바꾸지 않는다.
선택된 종목 테마를 바탕으로 각 카드의 visual direction 7개를 작성한다.
SNS 제목과 캡션, 해시태그는 제공된 사실과 카드 원고에서만 도출한다.
과도한 낚시·확인되지 않은 표현은 금지한다.
임현우·최지민은 SNS, 윤서아·정하린·김서현은 카드 디자인, 박소연·김동혁은 숏폼 전환 관점의 contribution을 작성한다."""


def _feedback_instructions() -> str:
    return """스포츠 미디어 사후 편집회의다.
active_agents 각각이 이번 결과에서 잘한 점과 다음에 개선할 점을 평가한다.
feedback에는 가능한 한 모든 active_agents를 포함한다.
learning_rule은 다음 제작 시 실제 프롬프트에 재사용할 수 있는 구체적 규칙으로 쓴다.
예: '헤드라인에서 승패 결과를 반복하지 말고 결정적 장면을 첫 15자 안에 배치한다.'
사실 자체를 학습 규칙으로 저장하지 않는다.
100점은 사실상 사용하지 말고, 개선할 부분이 있으면 점수에 반영한다."""


def _archive(store: SupabaseStore, request: StudioRequest, package: StudioPackage) -> None:
    store.upsert(
        "production_sessions",
        {
            "session_id": package.session_id,
            "edition_date": package.edition_date,
            "sport": package.sport,
            "league": package.league,
            "topic": package.topic,
            "theme_id": package.theme.id,
            "input_payload": request.model_dump(mode="json"),
            "final_payload": package.model_dump(mode="json"),
            "status": "pending_human_review",
        },
        on_conflict="session_id",
    )
    rows = [
        {
            "feedback_key": f"{package.session_id}:{item.agent_id}",
            "session_id": package.session_id,
            "agent_id": item.agent_id,
            "agent_name": item.agent_name,
            "sport": package.sport,
            "score": item.score,
            "what_worked": item.what_worked,
            "improve_next": item.improve_next,
            "learning_rule": item.learning_rule,
        }
        for item in package.feedback
    ]
    if rows:
        store.upsert("agent_feedback", rows, on_conflict="feedback_key")


def _demo_package(
    request: StudioRequest,
    theme: ThemeProfile,
    session_id: str,
) -> StudioPackage:
    specialists = active_agents(request.sport, request.league)
    agent_outputs = [
        AgentContribution(
            agent_id=agent.id,
            agent_name=agent.name,
            title=agent.title,
            team=agent.team,
            task=agent.responsibility,
            result=f"{request.topic}을(를) 기준으로 {agent.responsibility} 관점의 검토를 완료했습니다.",
            confidence=0.88,
        )
        for agent in specialists
    ]
    cards = [
        CardCopy(slide=1, role="표지", kicker=f"{request.sport} · {request.league}", headline=request.topic[:48], body="오늘의 핵심 이슈를 데이터와 뉴스 가치 기준으로 정리했습니다.", key_stat="SPORTS DAILY"),
        CardCopy(slide=2, role="핵심", kicker="WHAT HAPPENED", headline="먼저 결과와 맥락부터", body="경기 결과·핵심 기록·공식 발표를 우선해 사건의 중심을 한 문장으로 정리합니다.", key_stat="FACT FIRST"),
        CardCopy(slide=3, role="TOP 1", kicker="MAIN ISSUE 01", headline="승부를 바꾼 가장 큰 장면", body="가장 높은 뉴스 가치를 가진 장면을 첫 번째 이슈로 배치합니다.", key_stat="TOP 1"),
        CardCopy(slide=4, role="TOP 2", kicker="MAIN ISSUE 02", headline="개인 기록과 경기 영향", body="선수 퍼포먼스가 실제 승부와 시즌에 어떤 영향을 줬는지 설명합니다.", key_stat="TOP 2"),
        CardCopy(slide=5, role="TOP 3", kicker="MAIN ISSUE 03", headline="다음 경기를 바꾸는 변수", body="순위·부상·일정·최근 흐름 가운데 팬이 알아야 할 세 번째 이슈를 고릅니다.", key_stat="TOP 3"),
        CardCopy(slide=6, role="데이터", kicker="DATA BOARD", headline="숫자로 다시 보는 오늘", body="스코어와 핵심 지표는 Supabase의 검증된 구조화 데이터에서 가져옵니다.", key_stat="DB VERIFIED"),
        CardCopy(slide=7, role="요약", kicker="ONE LOOK", headline="오늘은 이것만 기억하세요", body="TOP3를 다시 압축하고 다음 경기에서 확인할 관전 포인트로 마무리합니다.", key_stat="SAVE & SHARE"),
    ]
    directions = [
        "큰 헤드라인과 종목 컬러를 사용한 편집형 표지",
        "스코어보드처럼 핵심 사실을 좌우 정렬",
        "TOP1 숫자와 한 문장 헤드라인을 가장 크게 배치",
        "선수 기록을 카드형 모듈로 표현",
        "세 번째 이슈와 다음 경기 연결선을 강조",
        "숫자 3개 중심의 데이터 보드",
        "TOP3 요약과 저장·공유 CTA",
    ]
    cards = [card.model_copy(update={"visual_direction": directions[i]}) for i, card in enumerate(cards)]
    social = SocialDraft(
        post_title=f"{request.league} 오늘의 핵심 3가지",
        caption=f"{request.topic}. 경기 결과만 나열하지 않고 승부를 바꾼 장면, 주요 선수 기록, 다음 경기에 이어질 변수를 한 번에 정리했습니다.\n\n카드에서 오늘의 핵심 흐름을 확인해보세요.",
        hashtags=[f"#{request.sport}", f"#{request.league.replace(' ', '')}", "#스포츠뉴스", "#카드뉴스", "#스포츠데일리"],
    )
    feedback = [
        AgentFeedback(
            agent_id=agent.id,
            agent_name=agent.name,
            score=88,
            what_worked="담당 범위를 벗어나지 않고 핵심 정보를 분리했습니다.",
            improve_next="실제 운영에서는 검증 데이터와 성과 지표를 더 적극적으로 비교합니다.",
            learning_rule="다음 제작에서도 자신의 담당 범위에 맞는 근거를 먼저 제시하고 중복 문장을 줄인다.",
        )
        for agent in specialists
    ]
    return StudioPackage(
        session_id=session_id,
        edition_date=request.edition_date.isoformat(),
        sport=request.sport,
        league=request.league,
        topic=request.topic,
        theme=theme,
        master_headline=request.topic,
        editorial_angle="팩트 → 승부 영향 → 선수 기록 → 다음 관전 포인트 순으로 전달",
        agent_outputs=agent_outputs,
        facts=[
            VerifiedFact(key="DEMO-1", claim="데모에서는 실제 경기 사실 대신 제작 구조만 확인합니다.", confidence=1.0),
            VerifiedFact(key="DEMO-2", claim="라이브 모드는 Supabase 저장 자료를 우선 사용합니다.", confidence=1.0),
            VerifiedFact(key="DEMO-3", claim="부족한 최신 정보에 한해 OpenAI 검색을 사용합니다.", confidence=1.0),
        ],
        risks=["데모 데이터는 실제 뉴스 게시에 사용할 수 없습니다."],
        cards=cards,
        social=social,
        shortform_hook=f"15초 안에 보는 {request.league} 오늘의 핵심 3가지",
        feedback=feedback,
        overall_score=88,
        final_editor_note="데모 제작 구조 검증 완료. 라이브 제작 전 데이터 출처와 Supabase 연결 상태를 확인하세요.",
        needs_human_approval=True,
        generated_at=datetime.now(timezone.utc),
    )
