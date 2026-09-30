# 운영안과 구현 대응 관계

## 하루 한 편 흐름

1. `generator.py`가 OpenAI Responses API의 웹 검색 도구로 공식 출처 우선 조사를 수행하고 서로 다른 종목의 후보를 최소 3건 작성합니다.
2. 후보마다 중요도·한국 독자 관련성·출처 신뢰도·설명 가치를 1~5점으로 기록합니다.
3. 최근 7일 동안 병합된 `output/*/package.json`을 읽어 종목·리그·주제 편중을 프롬프트에 제공합니다.
4. KBO·KBL·NPB·EPL·NBA에서 검증 가능한 이슈를 하나씩 고르고 `표지 → KBO → KBL → NPB → EPL → NBA`의 6장으로 구성합니다. 실제 URL은 `facts.url`로 분리하고 카드 문구는 출처 ID만 참조합니다.
5. `validation.py`가 고정 리그 순서, 리그별 후보·출처 연결, 공식 원문 직접 확인 여부, 편집일 당일 조회 시각과 유효 기한, 카드 문구의 URL·도메인·Markdown 링크, 본문 길이, 경기 상태, 권리 상태, 카드 수, 승인 게이트를 검사합니다. 검색 결과 요약은 검증 완료로 인정하지 않습니다.
6. 차단 항목이 있으면 `pipeline.py`가 오류와 기존 초안을 복구 프롬프트에 넣어 공식 출처 재조사와 전체 원고 재작성을 최대 설정 횟수만큼 수행합니다. 충돌을 해결할 수 없으면 관련 주제를 폐기하며, 검증 규칙 자체는 완화하지 않습니다.
7. 복구된 패키지를 처음부터 다시 검증하고, 통과한 경우에만 `renderer.py`가 외부 소재 없이 1080×1350 PNG를 만듭니다. 렌더러는 `visual_template`과 `visual_items`의 실제 대진·시각·점수·상태를 사용하며, 방어 단계에서 남은 링크도 제거합니다. 복구 과정은 `recovery-log.md`에 기록합니다.
8. 렌더링 뒤에는 이미지 수·형식·크기·색상 모드를 검사하고, 게시용 캡션·대체 텍스트·출처 감사 문서·승인 대기 manifest와 `instagram-carousel.zip`을 만듭니다.
9. GitHub Actions는 API 호출 전 단위 테스트와 생성 후 검증을 모두 수행하고 결과 폴더를 Artifact로 보존합니다.
10. 날짜별 고정 자동화 브랜치에서 Draft PR을 생성하거나 갱신합니다. PR 병합은 사람 승인을 뜻하며 자동으로 수행하지 않습니다.

## 역할별 산출물

| 운영 역할 | 코드·파일 |
|---|---|
| 후보 수집·종목 데스크 | `generator.py`, `package.json`의 `candidates`·`facts` |
| 편성 에이전트 | 가중 점수와 `selected_candidate_title`·`selection_reason` |
| 원고 에이전트 | `cards`, `caption`, `hashtags`, `design_brief` |
| 팩트체크·권리 | `validation.py`, `validation.md`, `recovery-log.md`, `sources.md`, `rights_status` |
| 편집장 | `editorial-review.md` 체크리스트와 Draft PR 승인 |
| 채널·성장 | `instagram-carousel.zip`, `caption-instagram.md`, `alt-text.json`을 사용해 승인된 결과를 수동 게시하고 성과를 별도 기록 |

## 의도적으로 자동화하지 않은 것

- 인스타그램 게시·예약
- Draft PR 자동 병합
- 외부 사진·영상·로고 수집
- 광고·협찬 표기 판단
- 출처 충돌이나 미확인 부상·이적 정보를 근거 없이 자동 확정

이 경계는 운영안의 “AI는 조사·정리·초안을 돕고 사람 편집자가 게시를 승인한다”는 원칙을 코드로 강제하기 위한 것입니다.
