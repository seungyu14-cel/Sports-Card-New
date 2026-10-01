# 스포츠 카드뉴스 자동화 스튜디오

KBO·MLB·NPB 3개 야구 리그의 최신 공식 이슈를 조사해 **표지 1장 + 리그별 메인 이슈 3장 + 마무리 요약 1장 = 총 5장**의 인스타그램 카드뉴스를 만드는 자동화 프로젝트입니다.

토큰 비용과 시간 초과를 줄이기 위해 5장/3이슈로 축소하고 단계별 출력 토큰 상한과 하루 전체 예산을 적용했습니다. Research → Editorial → Design → Validation → Render → Visual QA 흐름과 뉴스 이미지 자동 연결 기능은 유지합니다.

## 최종 카드 구조

| 페이지 | 역할 |
|---|---|
| 1 | 표지 |
| 2 | 오늘의 메인 이슈 1 |
| 3 | 오늘의 메인 이슈 2 |
| 4 | 오늘의 메인 이슈 3 |
| 5 | 마무리 / 한눈 요약 |

2~4번에는 **KBO·MLB·NPB에서 각각 1개씩** 메인 이슈를 선택합니다. 같은 리그가 두 번 들어가거나 하나가 빠지면 자동 검증에서 차단됩니다.

5번 SUMMARY는 앞의 3개 이슈만 다시 정리합니다.

## 토큰 절감 설정

- 후보 풀 목표: **6개**
- 메인 이슈: **3개**
- 생성 카드: **5장**
- 단계별 최대 출력: 리서치 **8,000** / 편집 **6,000** / 디자인 **4,000** / 복구 **9,000**
- 정상 제작 최대 예약량: **18,000**, 자동 복구 포함 하루 상한: **27,000**
- 추론 강도: `low`, API 시간 제한: 300초
- 시간 초과는 자동 재시도하지 않고 연결 오류·429만 1회 재시도

KBO·MLB·NPB 공식 원문 검증은 그대로 유지합니다.

## 뉴스 이미지

라이브 생성에서는 검증된 뉴스·공식 원문 페이지의 대표 이미지를 사용할 수 있습니다.

1. 카드의 검증 완료 `facts.url`을 확인합니다.
2. 원문 HTML의 `og:image` 또는 `twitter:image`를 읽습니다.
3. 발견한 이미지를 `VisualAsset(asset_type=news_image)`으로 등록합니다.
4. 원문 Fact와 이미지의 연결 관계를 저장합니다.
5. 렌더링에 성공하면 뉴스 이미지를 사용하고 실패하면 데이터 그래픽으로 대체합니다.

AI가 임의의 이미지 URL을 만들어 내는 방식은 사용하지 않습니다.

## 기본 편집 규칙

`config/settings.toml`:

- 전체 카드: 5장
- 메인 이슈: 3개
- 리그: KBO / MLB / NPB
- 각 리그 메인 이슈: 정확히 1개
- 후보 풀 목표: 6개
- 같은 시각 템플릿 연속 반복: 최대 2장
- 최근 게시 이력: 7일
- 성과 참고: 30일

## 결과 파일

`output/YYYY-MM-DD/`:

- `card-01.png` ~ `card-05.png`
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
- 필요 시 `recovery-log.md`

## 실행

```powershell
git pull origin main
python -m pip install -e ".[dev]"
pytest -q
sports-card-news daily --date 2026-10-01
```

API 없이 데모 확인:

```powershell
sports-card-news daily --date 2026-10-01 --fixture fixtures/demo_package.json
```

GitHub Actions는 테스트 → 생성 → 검증 → Visual QA → Draft PR 순서로 동작하며 게시 여부는 사람이 최종 결정합니다.

