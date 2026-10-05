from __future__ import annotations

from datetime import date
from pathlib import Path

from sports_card_news.employee_training import EMPLOYEE_TRAINING, training_profile
from sports_card_news.local_studio import LocalStudioRequest, local_category_info, run_local_studio


class FakeOllama:
    def __init__(self) -> None:
        self.calls = 0

    def json_chat(self, system: str, payload: dict) -> dict:
        self.calls += 1
        if self.calls == 1:
            cards = []
            headlines = [
                'KIA, LG에 6-4 역전승', '4점 차를 따라잡은 KIA',
                '김도영 9회 역전 3점포', '시즌 42호 홈런',
                'LG 초반 4득점에도 역전패', 'KIA 불펜 추가 실점 차단',
                '승부 갈린 9회', '정해영 세이브',
                '숫자로 보는 KIA-LG', '오늘은 이것만 기억하세요',
            ]
            for i, headline in enumerate(headlines, start=1):
                cards.append({
                    'slide': i, 'role': f'PAGE {i}', 'kicker': f'ISSUE {i}',
                    'headline': headline,
                    'body': '업로드한 MD에 있는 KIA 6-4 LG 경기 내용만 사용한 카드뉴스 본문입니다.',
                    'key_stat': 'KIA 6-4 LG' if i != 4 else '42호 홈런',
                    'visual_direction': '검증된 경기 사실 중심의 에디토리얼 카드',
                })
            return {
                'master_headline': '김도영 9회 3점포, KIA 6-4 역전승',
                'editorial_angle': '4점 차 추격과 9회 역전 홈런을 중심으로 경기 흐름을 설명한다.',
                'facts': [
                    {'key':'score','claim':'KIA가 LG에 6-4로 승리했다.','confidence':0.99},
                    {'key':'hr','claim':'김도영이 9회 역전 3점 홈런을 기록했다.','confidence':0.99},
                    {'key':'42','claim':'김도영의 홈런은 시즌 42호였다.','confidence':0.98},
                ],
                'warnings': [], 'cards': cards,
                'social': {
                    'post_title':'김도영 9회 역전포, KIA 6-4 승리',
                    'caption':'KIA가 LG를 상대로 4점 차를 따라잡은 뒤 9회 김도영의 역전 3점 홈런으로 승부를 뒤집었습니다. 업로드한 MD 근거만 사용해 오늘 경기의 핵심 장면과 기록을 10장으로 정리했습니다.',
                    'hashtags':['#KBO','#KIA','#LG','#김도영','#카드뉴스'],
                },
                'shortform_hook':'9회 한 방으로 뒤집힌 KIA-LG, 핵심만 30초에 봅니다.',
            }
        agents = payload['active_agents']
        return {
            'feedback': [
                {
                    'agent_id': a['id'], 'agent_name': a['name'], 'score': 90,
                    'what_worked':'MD 근거를 벗어나지 않았다.',
                    'improve_next':'다음에는 핵심 사건의 우선순위를 더 빠르게 정한다.',
                    'learning_rule':'MD에 직접 근거가 있는 결정적 사건을 표지와 TOP1에 우선 배치한다.',
                } for a in agents
            ],
            'overall_score': 92,
            'final_editor_note':'MD 근거 기반 제작이 완료됐으며 다음 실행에는 저장된 편집 규칙을 재사용한다.',
        }


def test_local_studio_uses_markdown_and_generates_ten_cards(tmp_path: Path) -> None:
    request = LocalStudioRequest(
        edition_date=date(2026,10,6), category='KBO',
        topic='KIA-LG 경기 브리핑',
        markdown_text='# KIA 6-4 LG\nKIA가 6-4로 승리했다. 김도영이 9회 시즌 42호 역전 3점 홈런을 기록했다. 정해영이 세이브를 기록했다.',
        source_name='kbo.md', editorial_instruction='결정적 장면부터 정리',
    )
    destination, package = run_local_studio(
        request, output_root=tmp_path/'output', memory_path=tmp_path/'memory.sqlite3', client=FakeOllama()
    )
    assert len(package.cards) == 10
    assert '김도영' in package.master_headline
    assert (destination/'card-10.png').exists()
    assert (destination/'source.md').exists()
    assert len(package.feedback) >= 8
    assert (tmp_path/'memory.sqlite3').exists()

def test_employee_training_has_all_23_profiles() -> None:
    assert len(EMPLOYEE_TRAINING) == 23
    assert training_profile("kim-doyoon")["core_rule"].startswith("가장 결정적인 사건")
    assert "MD 원문" in training_profile("park-jihoon")["core_rule"]
    assert "MD에 없는" in training_profile("han-yerin")["core_rule"]


def test_category_info_exposes_training_and_only_relevant_specialists() -> None:
    info = local_category_info("KBO")
    agents = {item["id"]: item for item in info["agents"]}
    assert agents["kim-doyoon"]["working"] is True
    assert agents["kim-taehoon"]["working"] is True
    assert agents["jung-minwoo"]["working"] is False
    assert agents["kim-doyoon"]["training"]["focus"] == "뉴스 가치"
    assert agents["park-jihoon"]["training"]["focus"] == "숫자 검증"


def test_local_seven_pages_passes_md_to_feedback_and_creates_work_bundle(tmp_path: Path) -> None:
    class SevenOllama(FakeOllama):
        def json_chat(self, system: str, payload: dict) -> dict:
            if self.calls == 0:
                assert payload['page_count'] == 7
                assert len(payload['required_pages']) == 7
                assert 'measured_performance' in payload
                result = super().json_chat(system, payload)
                result['cards'] = result['cards'][:7]
                return result
            assert '김도영' in payload['markdown_source']
            assert payload['extracted_facts']
            return super().json_chat(system, payload)

    request = LocalStudioRequest(edition_date=date(2026,10,6), category='KBO',
        topic='7페이지 검증', page_count=7,
        markdown_text='KIA가 LG에 6-4로 승리했다. 김도영이 9회 시즌 42호 역전 3점 홈런을 기록했다.')
    destination, package = run_local_studio(request, output_root=tmp_path/'output', memory_path=tmp_path/'memory.sqlite3', client=SevenOllama())
    assert len(package.cards) == 7
    assert (destination/'card-07.png').exists()
    assert not (destination/'card-08.png').exists()
    assert (destination/'work-bundle.zip').exists()


def test_local_rejects_wrong_requested_count(tmp_path: Path) -> None:
    import pytest
    request = LocalStudioRequest(edition_date=date(2026,10,6), category='KBO', topic='페이지 수 불일치', page_count=7,
        markdown_text='KIA가 LG에 6-4로 승리했다. 김도영이 역전 홈런을 기록했다.')
    with pytest.raises(ValueError, match='요청한 7페이지'):
        run_local_studio(request, output_root=tmp_path/'output', memory_path=tmp_path/'memory.sqlite3', client=FakeOllama())
