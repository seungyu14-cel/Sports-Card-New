# ChatGPT Work 스포츠 편집국 운영

기존 MD + Ollama + 직원별 Feedback Memory에 Work 전달·검수·성과 기록을 추가했습니다.
기본은 10페이지이며 링크의 7페이지(표지/메인 이슈 1~5/요약)는 선택할 수 있습니다.

## 시작

```powershell
git switch feat/local-llm-feedback-newsroom
git pull --ff-only
python -m pip install -e ".[dev]"
sports-card-news-web --open-browser
```

- Work 운영 허브: http://127.0.0.1:8787/work
- 기존 Ollama 제작소: http://127.0.0.1:8787/local
- Work 원고 가져오기는 OpenAI API 키와 Ollama가 모두 없어도 동작합니다.
- Ollama로 만들 때만 `ollama serve`와 모델 설치가 필요합니다.

## 방법 A: Work에서 편집하고 프로그램으로 가져오기

1. `/work`에서 **직원 프롬프트 + JSON 규격 복사**를 누릅니다.
2. ChatGPT Work에 프롬프트와 검증할 MD를 함께 제공합니다. `page_count`는 10 또는 7입니다.
3. Work가 반환한 JSON을 붙여넣거나 파일로 가져옵니다.
4. 페이지별 `evidence`는 MD에서 그대로 인용한 문자열이어야 합니다. 프로그램은 존재 여부만 검사하며, 그 인용이 실제로 모든 문장을 뒷받침하는지는 사람이 확인합니다.
5. 가져오기 성공 시 미리보기와 Work 전달 ZIP이 생성됩니다. AI 직원의 개별 실행이나 팩트체크 점수를 만들어 기록하지 않습니다.

핵심 직원 6명은 김도윤(선정), 서유진(흐름), 박지훈(사실), 강지우(카피), 정하린(디자인), 임현우(배포·성과)입니다.
기존 23명 교육과 Ollama 합동 편집 프롬프트는 유지됩니다. 이름별 규칙 주입은 별도의 독립 에이전트 실행이나 모델 가중치 학습과 다릅니다.

## 방법 B: 기존 Ollama 제작 후 Work로 넘기기

1. `/local`에서 MD·리그·페이지 수를 선택하고 제작합니다.
2. `/work`에서 해당 세션을 선택합니다.
3. **Canva CSV · Work 전달서 ZIP 다운로드**를 누릅니다.
4. ZIP에는 원본 MD, 카드 JSON, 캡션, Canva CSV, Work 작업 지침과 전달 명세가 있습니다.
5. 직원 사후 검수 프롬프트에 이제 MD 원문과 추출 사실을 함께 전달합니다.

## Canva → 검수 → Metricool SOP

| 단계 | 담당 | 입력 | 수행 시점 및 출력 |
|---|---|---|---|
| 뉴스 선정·편집 | 김도윤·서유진·강지우 | 검증한 MD | 원고 생성 전. 핵심 사건·페이지 순서 확정 |
| 숫자·출처 검수 | 박지훈 | MD·원고·페이지 근거 | 디자인 전. 스코어·선수명·경기상태 대조 |
| 템플릿 제작 | 정하린 / Work Canva | 실제 MASTER_TEMPLATE ID·전달 ZIP | 원고 확정 후. 기존 템플릿 읽기→복제→필드 매핑→내용 교체 |
| 시각 검수 | 사용자·디자인 담당 | 최종 Canva 디자인 | 내보내기 전. 사진 권한·잘림·오탈자·순서 확인 |
| 예약 | 임현우 / Work Metricool | 최종 이미지·캡션·brand ID·게시 시각 | 실제 게시 지시 후. 기존 예약 확인→예약→반환된 post ID 기록 |
| 성과 | 임현우 | Metricool 실측값 | 게시 후 24/48/168시간. 도달·노출·좋아요·댓글·저장·공유 기록 |
| 다음 편집 | Work / Ollama | 같은 리그·관측 기간 집계 | 다음 생성 전. 성과 기준선을 참고하되 사실 검증 규칙은 유지 |

**외부 앱 호출 경계:** 로컬 프로그램은 ChatGPT의 플러그인 세션을 사용할 수 없습니다.
따라서 Canva 디자인 생성·Metricool 예약은 연결된 Work 플러그인에서 실행합니다.
프로그램은 전달 ZIP을 만들고 사용자가 입력한 검수·외부 처리 결과·성과를 보관합니다.
`external_actions_executed: false`는 이 프로그램이 외부 동작을 수행하지 않았다는 뜻입니다.
예약 결과 기록 버튼을 눌러도 Instagram에는 게시되지 않습니다.
실제 연결·호출 성공 여부를 프로그램에서 자동 확인하지 않으며, 현재 작업에서 실계정 예약은 수행하지 않았습니다.

Canva CSV는 `p01_headline`, `p01_body`, `p01_kicker`, `p01_key_stat`부터 시작하는 **다중 페이지 한 디자인에 대한 한 행**입니다.
실제 Canva 템플릿 필드를 읽고 명시적으로 매핑해야 합니다. 템플릿마다 자동 대입이 보장되는 범용 Canva API payload가 아닙니다.
MASTER_TEMPLATE ID가 없으면 임의 생성·덮어쓰기하지 않고 Work에서 사용할 템플릿을 지정합니다.
사진·로고는 이번 프로그램이 자동 수집하지 않습니다. 최종 Canva 디자인에서 승인된 자산을 사용합니다.

## 시간과 성과 규칙

- 시간대는 Asia/Seoul입니다.
- KBO·NPB 23:50, MLB 14:00, EPL 08:00, NBA 15:00은 자료 수집 마감입니다. 예약 게시 시각이 아닙니다.
- KBL·V-LEAGUE는 마감 미설정으로 표시합니다. 임의 시간을 넣지 않습니다.
- 성과는 `post_id`가 기록된 예약 결과와 같아야 합니다.
- 선택한 관측 기간이 지나야 입력할 수 있습니다. 비교 시 가능한 한 같은 시점에 수집하세요.
- 저장률 = 저장/도달, 공유율 = 공유/도달, 참여율 = (좋아요+댓글+저장+공유)/도달입니다.
- 도달 0은 비율 계산 불가(null)로 표시합니다.
- 리그·관측 기간별 도달 가중 집계입니다. 3건 미만은 표본 부족이며, 3건 이상이어도 인과 효과를 입증하지 않습니다.
- 현재는 세션별 최신 성과 스냅샷 1개를 보관합니다. 여러 기간을 입력하면 마지막 입력이 이전 스냅샷을 대체합니다.
- 실제 성과 집계를 다음 Ollama 편집 프롬프트와 Work 프롬프트에 제공합니다. 과거 경기 사실이나 특정 선수 기록을 다음 뉴스에 재사용하지 않습니다.
- 원고/MD가 바뀌면 기존 검수는 무효입니다. 이미 예약 결과가 있는 원고의 수정본은 새 세션으로 가져옵니다.

## 저장 및 연결

- 제작물: `output/studio/<session_id>/`
- 검수·예약·성과: `data/work_operations.sqlite3`
- 기존 직원별 학습 규칙: `data/feedback_memory.sqlite3`
- Google Drive와 Notion 기록은 `work-brief.md`의 지침에 따라 Work에서 수행합니다. 로컬 프로그램이 자동 업로드하지 않습니다.
- 사용자 로컬 실행을 전제로 합니다. 로그인 없는 로컬 운영 API를 공용 인터넷에 노출하지 마세요.

## API

- `GET /api/work/import-schema`: Work 작성 프롬프트·JSON Schema·6명 역할·성과 기준선
- `POST /api/work/import`: MD+JSON 원고 가져오기 및 미리보기 생성
- `GET /api/work/sessions`: 영구 저장된 제작물·운영 상태
- `GET /api/work/sessions/{id}`: 원고·검사 경고·검수·예약·성과
- `GET /api/work/sessions/{id}/bundle`: Canva/Work 전달 ZIP
- `POST /api/work/sessions/{id}/review`: 최종 검수 확인 기록
- `POST /api/work/sessions/{id}/schedule-receipt`: 외부 예약 결과 기록(실행 안 함)
- `POST /api/work/sessions/{id}/metrics`: 실측 성과 입력
- `GET /api/work/performance`: 리그·관측 기간별 성과 집계

## 검증 범위

자동 검사는 페이지 수·순서·인용 존재·숫자 후보·제목 중복을 확인합니다.
같은 숫자가 다른 의미로 쓰였는지, 선수가 맞는지, URL 출처가 사실을 뒷받침하는지까지 자동 보장하지 않습니다.
Work 가져오기/Canva 전달 파일/검수·예약·성과 API는 테스트하며, 실제 Canva 템플릿과 Metricool 실계정 예약은 별도 연결 실행 단계입니다.
