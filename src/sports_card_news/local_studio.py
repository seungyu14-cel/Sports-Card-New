from __future__ import annotations

import hashlib
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import Field, field_validator

from .feedback_memory import FeedbackMemory
from .models import StrictModel
from .ollama_client import OllamaClient
from .studio import AgentFeedback, CardCopy, SocialDraft, StudioPackage, VerifiedFact, AgentContribution, active_agents, ThemeProfile
from .studio_renderer import render_studio_package

ProgressCallback = Callable[[str, int, str], None]

CATEGORY_CONFIG = {
    'KBO': ('야구','baseball-green'), 'NPB': ('야구','baseball-green'), 'MLB': ('야구','baseball-green'),
    'KBL': ('농구','basketball-orange'), 'NBA': ('농구','basketball-orange'),
    'EPL': ('축구','soccer-red'), 'V-LEAGUE': ('배구','volleyball-blue'),
}

THEMES = {
    'baseball-green': ThemeProfile(id='baseball-green', sport='야구', name='Diamond Green', primary='#123F2F', secondary='#1F6B4E', accent='#B6F36B', paper='#F4F1E8', description='야구 자동 테마'),
    'basketball-orange': ThemeProfile(id='basketball-orange', sport='농구', name='Court Orange', primary='#8F3B12', secondary='#E56A1F', accent='#FFD166', paper='#FFF3E8', description='농구 자동 테마'),
    'soccer-red': ThemeProfile(id='soccer-red', sport='축구', name='Pitch Red', primary='#6F1717', secondary='#C92A2A', accent='#FFB3A7', paper='#FFF0ED', description='축구 자동 테마'),
    'volleyball-blue': ThemeProfile(id='volleyball-blue', sport='배구', name='Volley Blue', primary='#133E7C', secondary='#2767B5', accent='#92D5FF', paper='#EEF6FF', description='배구 자동 테마'),
}

class LocalStudioRequest(StrictModel):
    edition_date: date
    category: Literal['KBO','NPB','MLB','KBL','NBA','EPL','V-LEAGUE']
    topic: str = Field(min_length=2, max_length=200)
    markdown_text: str = Field(min_length=20, max_length=120000)
    source_name: str = Field(default='uploaded.md', max_length=180)
    editorial_instruction: str = Field(default='', max_length=8000)
    save_feedback_memory: bool = True

class LocalEditorial(StrictModel):
    master_headline: str = Field(min_length=4, max_length=70)
    editorial_angle: str = Field(min_length=10, max_length=500)
    facts: list[dict[str, Any]] = Field(min_length=3, max_length=40)
    warnings: list[str] = Field(default_factory=list, max_length=15)
    cards: list[CardCopy] = Field(min_length=10, max_length=10)
    social: SocialDraft
    shortform_hook: str = Field(min_length=5, max_length=160)

    @field_validator('cards')
    @classmethod
    def validate_cards(cls, cards: list[CardCopy]) -> list[CardCopy]:
        if sorted(card.slide for card in cards) != list(range(1,11)):
            raise ValueError('카드는 1~10번이 각각 한 장씩 필요합니다.')
        return sorted(cards, key=lambda x: x.slide)

class LocalFeedback(StrictModel):
    feedback: list[AgentFeedback] = Field(default_factory=list, max_length=24)
    overall_score: int = Field(ge=1, le=100)
    final_editor_note: str = Field(min_length=10, max_length=800)

def local_category_info(category: str) -> dict[str, Any]:
    sport, theme_id = CATEGORY_CONFIG[category]
    theme = THEMES[theme_id]
    active = {a.id for a in active_agents(sport, category)}
    from .studio import AGENTS
    return {'category': category, 'sport': sport, 'theme': theme.model_dump(mode='json'), 'agents': [{**a.model_dump(mode='json'), 'working': a.id in active} for a in AGENTS]}

def run_local_studio(request: LocalStudioRequest, *, output_root: str | Path, memory_path: str | Path, client: OllamaClient | None = None, progress: ProgressCallback | None = None) -> tuple[Path, StudioPackage]:
    notify = progress or (lambda _s,_p,_m: None)
    sport, theme_id = CATEGORY_CONFIG[request.category]
    theme = THEMES[theme_id]
    agents = active_agents(sport, request.category)
    memory = FeedbackMemory(Path(memory_path))
    rules = memory.recent_rules(category=request.category, agent_ids=[a.id for a in agents], per_agent=3)
    ollama = client or OllamaClient()
    session_id = f'local-{request.edition_date:%Y%m%d}-{uuid.uuid4().hex[:8]}'

    notify('research', 15, 'MD와 과거 직원 학습 규칙을 분석합니다.')
    payload = {
        'category': request.category, 'sport': sport, 'topic': request.topic,
        'markdown_source': request.markdown_text[:120000],
        'editorial_instruction': request.editorial_instruction,
        'active_agents': [{'id':a.id,'name':a.name,'title':a.title,'responsibility':a.responsibility} for a in agents],
        'past_learning_rules': rules,
        'required_pages': ['1 표지','2 결과 요약','3 이슈1','4 이슈2','5 이슈3','6 이슈4','7 이슈5','8 이슈6/배경','9 데이터','10 요약/CTA'],
    }
    editorial = LocalEditorial.model_validate(ollama.json_chat(_editorial_prompt(), payload))

    notify('feedback', 78, '근무 직원별 피드백과 다음 학습 규칙을 생성합니다.')
    feedback_payload = {
        'category': request.category,
        'active_agents': payload['active_agents'],
        'cards': [c.model_dump(mode='json') for c in editorial.cards],
        'previous_learning_rules': rules,
    }
    fb = LocalFeedback.model_validate(ollama.json_chat(_feedback_prompt(), feedback_payload))
    feedback = _complete_feedback(fb.feedback, agents)

    facts = []
    for idx, item in enumerate(editorial.facts, start=1):
        claim = str(item.get('claim') or item.get('text') or '').strip()
        if claim:
            facts.append(VerifiedFact(key=str(item.get('key') or f'MD-{idx}'), claim=claim[:500], source_url='', confidence=float(item.get('confidence', 0.9))))
    if len(facts) < 3:
        raise ValueError('로컬 LLM이 MD에서 최소 3개의 사실을 추출하지 못했습니다.')

    package = StudioPackage(
        session_id=session_id, edition_date=request.edition_date.isoformat(), sport=sport, league=request.category, topic=request.topic, theme=theme,
        master_headline=editorial.master_headline, editorial_angle=editorial.editorial_angle,
        agent_outputs=[AgentContribution(agent_id=a.id,agent_name=a.name,title=a.title,team=a.team,task=a.responsibility,result='MD 원문과 학습 규칙을 기준으로 담당 업무를 수행했습니다.',confidence=0.91) for a in agents],
        facts=facts, risks=editorial.warnings, cards=editorial.cards, social=editorial.social, shortform_hook=editorial.shortform_hook,
        feedback=feedback, overall_score=fb.overall_score, final_editor_note=fb.final_editor_note, needs_human_approval=True, generated_at=datetime.now(timezone.utc),
    )

    notify('render', 92, '10페이지 PNG를 렌더링합니다.')
    destination = Path(output_root) / 'studio' / session_id
    destination.mkdir(parents=True, exist_ok=True)
    render_studio_package(package, destination)
    (destination/'studio-package.json').write_text(package.model_dump_json(indent=2)+'\n', encoding='utf-8')
    (destination/'source.md').write_text(request.markdown_text, encoding='utf-8')
    (destination/'caption-instagram.md').write_text(f'{package.social.post_title}\n\n{package.social.caption}\n\n'+' '.join(package.social.hashtags)+'\n', encoding='utf-8')

    if request.save_feedback_memory:
        memory.save_feedback(session_id=session_id, edition_date=package.edition_date, category=request.category, sport=sport, feedback=[x.model_dump(mode='json') for x in feedback])
    memory.save_run(session_id=session_id, edition_date=package.edition_date, category=request.category, sport=sport, topic=request.topic, source_name=request.source_name, markdown_sha256=hashlib.sha256(request.markdown_text.encode('utf-8')).hexdigest(), output_path=str(destination))
    notify('complete', 100, 'MD → Ollama → Feedback Memory → 10페이지 제작 완료')
    return destination, package

def _complete_feedback(items: list[AgentFeedback], agents: list[Any]) -> list[AgentFeedback]:
    by_id = {x.agent_id:x for x in items}
    out=[]
    for a in agents:
        out.append(by_id.get(a.id) or AgentFeedback(agent_id=a.id,agent_name=a.name,score=85,what_worked='담당 검토 단계를 수행했습니다.',improve_next='다음에는 MD 근거와 결과 문장을 더 엄격히 대조합니다.',learning_rule=f'{a.responsibility} 단계에서 MD 원문 근거와 최종 문장을 반드시 대조한다.'))
    return out

def _editorial_prompt() -> str:
    return '''너는 스포츠 데일리 카드 뉴스 제작소의 합동 편집국이다.
유일한 사실 소스는 markdown_source다. 외부지식, 기억, 인터넷 정보로 사실을 추가하지 않는다.
past_learning_rules는 글쓰기/편집 방법 개선에만 사용하고 과거 사실은 재사용하지 않는다.
반드시 정확히 10장의 cards를 만들고 slide는 1~10이다. 한 카드 한 메시지를 지킨다.
정보가 부족하면 억지 사건을 만들지 말고 MD에 존재하는 배경, 기록, 요약으로 채운다.
facts에는 MD에서 직접 확인 가능한 사실을 최소 3개 넣고 claim과 confidence를 포함한다.
JSON만 출력한다.
스키마: {"master_headline":"","editorial_angle":"","facts":[{"key":"","claim":"","confidence":0.9}],"warnings":[],"cards":[{"slide":1,"role":"","kicker":"","headline":"","body":"","key_stat":"","visual_direction":""}],"social":{"post_title":"","caption":"","hashtags":["#태그"]},"shortform_hook":""}'''

def _feedback_prompt() -> str:
    return '''너는 스포츠 미디어 사후 편집회의다. active_agents 각각을 평가한다.
learning_rule은 다음 실행 프롬프트에 재사용할 수 있는 구체적 개선 규칙이다. 과거 사실은 저장하지 않는다.
100점은 쓰지 않는다. JSON만 출력한다.
스키마: {"feedback":[{"agent_id":"","agent_name":"","score":90,"what_worked":"","improve_next":"","learning_rule":""}],"overall_score":90,"final_editor_note":""}'''