# 스포츠 데일리 카드 뉴스 제작소

기본 화면은 **MD 업로드/붙여넣기 → Ollama 편집 → 직원별 Feedback Memory → 10페이지 PNG** 제작소입니다. OpenAI API 키 없이 사용합니다. 주제 입력란은 없으며 MD 제목을 자동으로 사용합니다. 7페이지도 선택할 수 있습니다.

## Windows에서 시작

1. 실행 중인 예전 서버 창에서 `Ctrl+C`로 종료합니다.
2. 저장소 폴더에서 최신 main을 받습니다. 로컬 수정이 있다면 먼저 보관하고, pull 충돌 시 강제로 덮어쓰지 마세요.

```powershell
git switch main
git pull --ff-only origin main
```

3. Python 3.11 이상과 Ollama를 설치한 상태에서 모델을 한 번 다운로드합니다.

```powershell
ollama pull qwen3:8b
```

4. `start.bat`를 더블클릭합니다. 가상환경과 의존성을 설치하고 기본 MD 제작 화면을 엽니다.
5. 화면에서 `LOCAL AI READY`를 확인합니다. OFFLINE이면 별도 터미널에서 `ollama serve`를 실행하고 **연결 다시 확인**을 누릅니다. Ollama 앱이 이미 실행 중이면 serve를 중복 실행할 필요가 없습니다.
6. 날짜·리그·페이지 수를 선택하고 MD 파일을 업로드하거나 원문을 붙여넣습니다. **로컬 AI 편집국 제작 시작**을 누르면 PNG·캡션·피드백을 생성합니다.
7. 완성 후 ZIP 다운로드 또는 Work 운영 허브로 이동합니다.

| 주소 | 기능 |
|---|---|
| `http://127.0.0.1:8787/` 또는 `/local` | 기본 MD 제작소 · 10페이지 · 주제 자동 추출 |
| `http://127.0.0.1:8787/work` | Work 원고·Canva 전달·검수·Instagram 예약 |
| `http://127.0.0.1:8787/legacy` | 기존 OpenAI 스튜디오 |

포트 충돌 시 예전 서버를 종료하거나 `powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Port 8788`로 실행합니다. 최신 소스를 받아도 실행 중인 Python 서버는 자동 교체되지 않으므로 반드시 재시작하세요.

수동 실행은 저장소 루트에서 다음과 같습니다.

```powershell
python -m pip install -e ".[dev]"
python -m sports_card_news.webapp --open-browser
```

결과는 `output/studio/<session-id>/`, 직원 메모리는 `data/feedback_memory.sqlite3`에 저장합니다. 모델이 MD를 편집하므로 결과의 정확성은 원문과 최종 검수로 확인해야 합니다. 실제 Canva·Instagram 자동 예약은 아래 인증 설정이 추가로 필요합니다.

## OpenAI 없이 로컬 LLM 모드

MD 파일만으로 10페이지 카드뉴스를 만들 수 있습니다.

```powershell
ollama serve
ollama pull qwen3:8b
sports-card-news-web --open-browser
```

브라우저에서 `http://127.0.0.1:8787/local`로 접속하세요.

로컬 모드는 `MD → Ollama → 직원별 Agent → SQLite Feedback Memory → 10P PNG` 순서로 동작합니다. 직원별 학습 규칙과 운영 방법은 `docs/LOCAL_LLM_FEEDBACK_GUIDE.md`를 참고하세요.

## ChatGPT Work 운영 허브

`http://127.0.0.1:8787/work`에서 API 키 없이 Work JSON 원고를 가져오고,
Canva 템플릿 전달 ZIP·최종 검수·Metricool 예약 결과·실측 성과를 관리합니다.
기존 `/local`은 기본 10페이지를 유지하며 7페이지도 선택할 수 있습니다.
Canva/Metricool의 실제 외부 작업은 Work 플러그인에서 수행합니다.
자세한 실행 순서는 [Work 운영 가이드](docs/WORK_OPERATIONS_GUIDE.md)를 참고하세요.

### Canva → Instagram 직접 자동 실행

`/work`의 자동 예약 폼에서 원고와 템플릿을 확인하고 실행하면 Canva 생성·PNG 내보내기·Metricool 미디어 보관·Instagram 예약이 이어집니다.
로컬 `.env`의 Canva/Metricool API 인증 및 Instagram 계정 연결이 필요합니다.
중복 요청 방지와 외부 응답 불명확 시 확인 대기 상태를 제공합니다.
[설정 및 실패 처리](docs/WORK_OPERATIONS_GUIDE.md#직접-api-자동-실행-추가-기능)를 먼저 확인하세요.


## 기존 뉴스 수집 및 CLI 흐름

## Supabase 경기별 TOP3 뉴스룸

새 Newsroom 계층은 스포츠 API/공식 원문을 Supabase에 먼저 축적하고, 숫자 사실은 SQL에서, 기사 맥락은 hybrid RAG에서 가져옵니다. 핵심 데이터가 비어 있을 때만 OpenAI Web Search를 켜서 **모든 종료 경기별 TOP3 뉴스**를 생성합니다.

핵심 구조:

```text
Sports API / Official pages
        ↓
Supabase structured facts + raw sources
        ↓
pgvector + keyword hybrid RAG
        ↓
Missing-fact detector
        ↓
OpenAI Web Search (필요할 때만)
        ↓
Game TOP3 → news_events / game_reports
        ↓
data/structured/YYYY-MM-DD.json
        ↓
Research → Editorial → Design → Validation → Render
        ↓
Human approval
```

설치 및 DB 스키마, 데이터 적재 방법은 [docs/SUPABASE_NEWSROOM.md](docs/SUPABASE_NEWSROOM.md)를 참고하세요.

## 기존 CLI 카드 구조

| 페이지 | 역할 |
|---|---|
| 1 | 표지 |
| 2 | 오늘의 메인 이슈 1 |
| 3 | 오늘의 메인 이슈 2 |
| 4 | 오늘의 메인 이슈 3 |
| 5 | 마무리 / 한눈 요약 |

2~4번에는 **KBO·MLB·NPB에서 각각 1개씩** 메인 이슈를 선택합니다.

## 토큰 절감 설정

- 후보 풀 목표: **6개**
- 메인 이슈: **3개**
- 생성 카드: **5장**
- 단계별 최대 출력: 리서치 **8,000** / 편집 **6,000** / 디자인 **4,000** / 복구 **9,000**
- 정상 제작 최대 예약량: **18,000**, 자동 복구 포함 하루 상한: **27,000**
- 추론 강도: `low`, API 시간 제한: 300초
- 경기별 Newsroom은 기본 `gpt-6.1-sol`, 임베딩은 `text-embedding-3-small`
- Supabase 핵심 사실이 충분하면 Newsroom Web Search를 생략
- 시간 초과는 자동 재시도하지 않고 연결 오류·429만 1회 재시도

## 기존 CLI 실행

```powershell
git pull origin main
python -m pip install -e ".[dev]"
pytest -q
sports-card-news daily --date 2026-10-05
```

Supabase Newsroom:

```powershell
sports-card-news newsroom-status
sports-card-news ingest-json data/import/2026-10-05.json
sports-card-news game-news --date 2026-10-05
sports-card-news daily --date 2026-10-05
```

API 없이 데모 확인:

```powershell
sports-card-news daily --date 2026-10-05 --fixture fixtures/demo_package.json
```

GitHub Actions는 테스트 → (Supabase가 연결된 경우 경기별 TOP3 생성) → 카드 생성 → 검증 → Visual QA → Draft PR 순서로 동작하며 게시 여부는 사람이 최종 결정합니다.
