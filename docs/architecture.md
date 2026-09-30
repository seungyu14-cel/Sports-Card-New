# 운영안과 구현 대응 관계

## 하루 한 편 흐름

1. `generator.py`가 **Research → Editorial → Design** 3단계로 분리되어 동작합니다. 리서치 단계만 웹 검색을 사용하고, 편집·디자인 단계는 검증된 리서치 결과만 사용합니다.
2. Research 단계는 KBO·KBL·NPB·EPL·NBA를 모두 조사하고 후보 풀을 만듭니다. 후보마다 중요도·한국 독자 관련성·출처 신뢰도·설명 가치·최신성·팬 관심도·시각화 잠재력·독창성을 1~5점으로 기록합니다.
3. `data/structured/YYYY-MM-DD.json` 또는 `data/structured/latest.json`이 있으면 공식 API/수집기에서 만든 구조화 데이터를 사전 컨텍스트로 사용합니다. provenance가 있어도 공식 원문을 재확인합니다.
4. 최근 게시 이력과 `output/*/performance.json` 성과 데이터는 반복 방지와 편집 참고에만 사용합니다. 팩트 판정 근거로 사용하지 않습니다.
5. Editorial 단계는 표지 1장 + 스토리 5장을 고릅니다. 과거의 `KBO → KBL → NPB → EPL → NBA` 고정 순서를 사용하지 않고, 뉴스 가치·최소 리그 다양성·리그당 최대 카드 수 규칙으로 편성합니다.
6. Design 단계는 원고를 바꾸지 않고 `match_result`, `match_preview`, `player`, `stat`, `ranking`, `breaking`, `schedule` 등 스포츠 전용 템플릿과 실제 `visual_items`를 설계합니다.
7. `validation.py`는 공식 원문 직접 확인, 조회일·유효기한, 후보-카드 연결, 리그 다양성, 템플릿 반복, 권리 승인된 asset만 사용했는지 검사합니다.
8. 검증 실패 시 `pipeline.py`가 공식 원문을 다시 조사해 전체 패키지를 복구합니다. 검증 규칙은 완화하지 않습니다.
9. `renderer.py`는 1080×1350 PNG를 만들고, 경기 결과·프리뷰·선수·기록·순위·속보·일정에 맞는 서로 다른 스포츠 모듈을 사용합니다. 외부 사진이 없어도 데이터 그래픽으로 완성되도록 설계했습니다.
10. `visual_qa.py`가 렌더 후 이미지 규격, 제목·본문 밀도, headline 중복, 데이터 포인트 부족, 템플릿 과반 반복을 검사하고 `visual-qa.md`를 남깁니다.
11. 게시 패키지는 캡션, 대체 텍스트, 출처 감사 문서, 권리 자산 정보, Visual QA, 승인 대기 manifest와 ZIP으로 묶입니다.
12. GitHub Actions는 API 호출 전 테스트, 생성 후 검증, ZIP 무결성 검사를 수행하고 날짜별 Draft PR을 만들거나 갱신합니다. 병합은 사람이 합니다.

## 역할별 산출물

| 운영 역할 | 코드·파일 |
|---|---|
| 리서치 데스크 | `ResearchBrief`, `candidates`, `facts`, 구조화 데이터 컨텍스트 |
| 편집장·카피 | `EditorialPlan`, `selected_candidate_title`, `cards`, `caption`, `hashtags` |
| 아트디렉션 | `DesignPlan`, 스포츠 전용 `visual_template`, `visual_items`, `assets` |
| 팩트체크·권리 | `validation.py`, `sources.md`, `rights_status`, asset 승인 게이트 |
| Visual QA | `visual_qa.py`, `visual-qa.md` |
| 성장 피드백 | `performance.json`을 다음 편집의 참고 데이터로 사용 |
| 최종 승인 | `editorial-review.md`와 Draft PR 사람 승인 |

## 시각 자산 원칙

`VisualAsset`은 선수 사진·팀/리그 로고·경기장·일러스트·데이터 그래픽의 출처와 권리 상태를 저장합니다. 카드가 외부 자산을 참조하려면 다음 조건을 모두 만족해야 합니다.

- `approved_for_publish=true`
- `rights_status`가 `자체 제작` 또는 `사용 허가`
- 카드의 `asset_ids`가 실제 등록 자산을 참조

자동화는 인터넷에서 사진이나 로고를 임의로 다운로드하지 않습니다. 승인 자산이 없으면 자체 제작 데이터 그래픽으로 렌더링합니다.

## 의도적으로 자동화하지 않은 것

- 인스타그램 게시·예약
- Draft PR 자동 병합
- 권리가 확인되지 않은 외부 사진·영상·로고 수집
- 광고·협찬 표기 판단
- 출처 충돌이나 미확인 부상·이적 정보를 근거 없이 자동 확정

AI는 조사·정리·초안·시각 설계를 돕고, 게시 여부는 사람이 결정합니다.
