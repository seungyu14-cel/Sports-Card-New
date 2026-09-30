# 스포츠 카드뉴스 자동화 스튜디오

KBO·KBL·NPB·EPL·NBA 5개 카테고리의 최신 공식 이슈를 조사해 **표지 1장 + 메인 이슈 8장 + 마무리 요약 1장 = 총 10장**의 인스타그램 카드뉴스를 만드는 자동화 프로젝트입니다.

현재 파이프라인은 **Research → Editorial → Design → Fact/Asset Validation → Render → Visual QA → Draft PR** 순서로 동작합니다. 자동 게시기는 아니며, 최종 게시 전 사람 승인 단계를 유지합니다.

## 카드 구성

| 페이지 | 역할 |
|---|---|
| 1 | 표지 |
| 2 | 오늘의 메인 이슈 1 |
| 3 | 오늘의 메인 이슈 2 |
| 4 | 오늘의 메인 이슈 3 |
| 5 | 오늘의 메인 이슈 4 |
| 6 | 오늘의 메인 이슈 5 |
| 7 | 오늘의 메인 이슈 6 |
| 8 | 오늘의 메인 이슈 7 |
| 9 | 오늘의 메인 이슈 8 |
| 10 | 마무리 / 한눈 요약 |

2~9번의 8개 이슈에는 **KBO·KBL·NPB·EPL·NBA가 모두 최소 1번** 들어가야 하며, 한 카테고리는 최대 2개까지만 허용합니다. 따라서 정상 편성의 카테고리 분포는 `2·2·2·1·1`입니다.

각 메인 이슈는 서로 다른 `candidate_title`을 사용합니다. 10번 요약 카드는 2~9번의 여덟 이슈를 2열 요약 그리드로 다시 보여 줍니다.

## 뉴스 이미지 사용

라이브 생성에서는 검증이 끝난 뉴스·공식 원문 페이지의 대표 이미지를 사용할 수 있습니다.

프로그램은 모델이 이미지 URL을 만들어 내도록 하지 않습니다. 대신 다음 순서로 처리합니다.

1. 이슈에 연결된 `facts.url` 중 **원문 직접 확인 + 검증 완료** 출처를 찾습니다.
2. 해당 원문 HTML의 `og:image` 또는 `twitter:image`를 읽습니다.
3. 발견한 이미지를 `VisualAsset(asset_type=news_image)`으로 등록합니다.
4. 사용자가 정한 프로젝트 운영 정책에 따라 `뉴스 이미지 사용 승인` 상태로 기록합니다.
5. 해당 이미지가 실제로 그 카드의 `source_fact_id`와 연결됐는지 검증합니다.
6. 렌더링 시 이미지를 불러올 수 있으면 사진 중심 카드로 사용하고, 실패하면 기존 데이터 그래픽으로 자동 fallback 합니다.

기본 설정:

```toml
[assets]
allow_news_images = true
auto_approve_verified_news_images = true
render_news_images = true
news_image_timeout_seconds = 8
```

AI가 임의의 이미지 URL을 추측하거나 카드와 무관한 외부 사진을 연결하는 구조는 사용하지 않습니다.

## 편집 규칙

`config/settings.toml`의 기본값은 다음과 같습니다.

- 전체 카드: 10장
- 메인 이슈: 8개
- 카테고리: KBO / KBL / NPB / EPL / NBA
- 메인 이슈에 포함할 최소 카테고리 수: 5
- 카테고리당 최대 이슈: 2
- 후보 풀 목표: 16개
- 같은 시각 템플릿 연속 반복: 최대 2장
- 최근 게시 이력 참고: 7일
- 성과 참고: 30일

후보 점수에는 중요도·한국 독자 관련성·출처 신뢰도·설명 가치뿐 아니라 최신성·팬 관심도·시각화 잠재력·독창성이 포함됩니다.

## 디자인 시스템

기본 브랜드는 따뜻한 아이보리 지면, 검정 타이포그래피, 스코어 옐로, 검토 레드를 유지합니다.

지원하는 주요 스포츠 템플릿:

- Match Result
- Match Preview
- Player
- Stat
- Ranking
- Breaking
- Schedule
- Explainer
- Summary

뉴스 대표 이미지가 연결된 이슈 카드는 이미지와 핵심 데이터 스트립을 함께 표시합니다. 이미지를 가져오지 못하더라도 카드 생성 전체를 실패시키지 않고 데이터 그래픽으로 대체합니다.

## 결과 파일

`output/YYYY-MM-DD/` 아래에 생성됩니다.

- `card-01.png` ~ `card-10.png`
- `package.json`
- `caption.md`
- `caption-instagram.md`
- `editorial-review.md`
- `validation.md`
- `visual-qa.md`
- `sources.md`
- `alt-text.json`
- `publish-manifest.json`
- `instagram-carousel.zip`
- 자동 복구가 발생한 경우 `recovery-log.md`

`sources.md`에는 이미지 자산의 원문 Fact, 이미지 URL, 크레딧, 사용 범위, 승인 근거가 함께 기록됩니다.

## 실행

Windows:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
$env:OPENAI_API_KEY="sk-proj-..."
sports-card-news daily --date 2026-09-30
```

데모:

```powershell
sports-card-news daily --date 2026-09-30 --fixture fixtures/demo_package.json
```

테스트:

```powershell
pytest -q
```

## GitHub Actions

`.github/workflows/daily-card-news.yml`은 기본적으로 매일 오전 8시(Asia/Seoul)에 실행됩니다.

- API 사용 전 단위 테스트
- Research → Editorial → Design 생성
- 10장/8이슈/5카테고리 편성 검증
- 출처 및 뉴스 이미지 연결 검증
- 렌더링
- Visual QA
- 게시 ZIP 검사
- 날짜별 Draft PR 생성/갱신

최종 게시 여부는 사람이 결정합니다.
