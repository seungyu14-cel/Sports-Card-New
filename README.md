# 스포츠 카드뉴스 자동화 스튜디오

KBO·MLB·NPB 공식 이슈를 조사해 **표지 1장 + 리그별 메인 이슈 3장 + 마무리 요약 1장 = 총 5장**의 인스타그램 카드뉴스를 만드는 자동화 프로젝트입니다.

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

## 최종 카드 구조

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

## 기본 실행

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
