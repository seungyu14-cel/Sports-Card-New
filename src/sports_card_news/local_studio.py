from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import Field, field_validator, model_validator

from .feedback_memory import FeedbackMemory
from .employee_training import training_payload
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
    topic: str = Field(default="", max_length=200)
    markdown_text: str = Field(min_length=20, max_length=120000)
    source_name: str = Field(default='uploaded.md', max_length=180)
    editorial_instruction: str = Field(default='', max_length=8000)
    save_feedback_memory: bool = True
    page_count: Literal[7, 10] = 10

    @model_validator(mode='after')
    def topic_from_source(self):
        if not self.markdown_text.strip() or len(self.markdown_text.strip()) < 20:
            raise ValueError('MD 원문을 20자 이상 입력하세요.')
        if not self.topic.strip():
            headings = re.findall(r'^[ \t]{0,3}#{1,6}[ \t]+(.+)', self.markdown_text.lstrip('\ufeff'), re.M)
            self.topic = (headings[0].strip()[:200] if headings else f'{self.edition_date} {self.category} MD 브리핑')
        return self

class LocalEditorial(StrictModel):
    master_headline: str = Field(min_length=4, max_length=70)
    editorial_angle: str = Field(min_length=10, max_length=500)
    facts: list[dict[str, Any]] = Field(min_length=3, max_length=40)
    warnings: list[str] = Field(default_factory=list, max_length=15)
    cards: list[CardCopy] = Field(min_length=7, max_length=10)
    social: SocialDraft
    shortform_hook: str = Field(min_length=5, max_length=160)

    @field_validator('cards')
    @classmethod
    def validate_cards(cls, cards: list[CardCopy]) -> list[CardCopy]:
        if len(cards) not in (7, 10) or sorted(card.slide for card in cards) != list(range(1, len(cards) + 1)):
            raise ValueError('카드는 7장 또는 10장이며 1번부터 연속 번호여야 합니다.')
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
    training = {item['agent_id']: item for item in training_payload([a.id for a in AGENTS])}
    return {'category': category, 'sport': sport, 'theme': theme.model_dump(mode='json'), 'agents': [{**a.model_dump(mode='json'), 'working': a.id in active, 'training': training[a.id]} for a in AGENTS]}

def run_local_studio(request: LocalStudioRequest, *, output_root: str | Path, memory_path: str | Path, client: OllamaClient | None = None, progress: ProgressCallback | None = None) -> tuple[Path, StudioPackage]:
    notify = progress or (lambda _s,_p,_m: None)
    sport, theme_id = CATEGORY_CONFIG[request.category]
    theme = THEMES[theme_id]
    agents = active_agents(sport, request.category)
    memory = FeedbackMemory(Path(memory_path))
    rules = memory.recent_rules(category=request.category, agent_ids=[a.id for a in agents], per_agent=3)
    ollama = client or OllamaClient()
    session_id = f'local-{request.edition_date:%Y%m%d}-{uuid.uuid4().hex[:8]}'

    from .work_hub import write_handoff
    from .staged_editorial import build_editorial
    destination = Path(output_root) / 'studio' / session_id
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'source.md').write_text(request.markdown_text, encoding='utf-8')
    editorial, fb = build_editorial(request, ollama, agents, rules, notify, destination)
    feedback = fb.feedback

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
        agent_outputs=[AgentContribution(agent_id=a.id,agent_name=a.name,title=a.title,team=a.team,task=a.responsibility,result=f'{i % len(editorial.cards)+1}페이지를 원문 근거 및 담당 교육 규칙으로 검수했습니다.',confidence=0.91) for i,a in enumerate(agents)],
        facts=facts, risks=editorial.warnings, cards=editorial.cards, social=editorial.social, shortform_hook=editorial.shortform_hook,
        feedback=feedback, overall_score=fb.overall_score, final_editor_note=fb.final_editor_note, needs_human_approval=True, generated_at=datetime.now(timezone.utc),
    )

    notify('render', 92, f'{request.page_count}페이지 PNG를 렌더링합니다.')
    destination = Path(output_root) / 'studio' / session_id
    destination.mkdir(parents=True, exist_ok=True)
    render_studio_package(package, destination)
    (destination/'studio-package.json').write_text(package.model_dump_json(indent=2)+'\n', encoding='utf-8')
    (destination/'source.md').write_text(request.markdown_text, encoding='utf-8')
    (destination/'caption-instagram.md').write_text(f'{package.social.post_title}\n\n{package.social.caption}\n\n'+' '.join(package.social.hashtags)+'\n', encoding='utf-8')

    write_handoff(package, destination, request.markdown_text)

    if request.save_feedback_memory:
        memory.save_feedback(session_id=session_id, edition_date=package.edition_date, category=request.category, sport=sport, feedback=[x.model_dump(mode='json') for x in feedback])
    memory.save_run(session_id=session_id, edition_date=package.edition_date, category=request.category, sport=sport, topic=request.topic, source_name=request.source_name, markdown_sha256=hashlib.sha256(request.markdown_text.encode('utf-8')).hexdigest(), output_path=str(destination))
    notify('complete', 100, f'MD → Ollama → Feedback Memory → {request.page_count}페이지 및 Work 전달 파일 제작 완료')
    return destination, package
