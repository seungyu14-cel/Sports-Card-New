# 스포츠 카드뉴스 자동화 스튜디오

KBO·KBL·NPB·EPL·NBA의 최신 공식 이슈를 조사해 6장의 인스타그램 카드뉴스를 만드는 자동화 프로젝트입니다. 현재 버전은 단순한 “리그별 한 장” 생성기가 아니라 **Research → Editorial → Design → Validation → Visual QA → Draft PR** 흐름으로 동작합니다.

자동 게시기는 아닙니다. 결과는 GitHub Draft PR로 제출되고, 종목 담당 → 팩트체크·권리 담당 → 편집장 승인 후에만 게시하는 구조입니다.

## 핵심 개선 사항

- **3단계 AI 파이프라인**: 웹 조사와 원고 작성, 디자인 결정을 한 번에 하지 않습니다.
- **뉴스 가치 기반 편성**: KBO→KBL→NPB→EPL→NBA 고정 순서를 제거하고, 최소 리그 다양성과 리그당 최대 카드 수를 지키면서 오늘 중요한 5개 이슈를 고릅니다.
- **확장된 편집 점수**: 중요도·한국 독자 관련성·출처 신뢰도 외에 최신성·팬 관심도·시각화 잠재력·독창성을 반영합니다.
- **스포츠 전용 템플릿**: 경기 결과, 경기 프리뷰, 선수, 기록, 순위, 속보, 일정형 레이아웃을 지원합니다.
- **권리 승인형 자산 모델**: 선수 사진·로고 등을 쓰려면 `VisualAsset`에 권리 상태와 게시 승인이 명시되어야 합니다. 승인되지 않은 자산은 자동 차단됩니다.
- **구조화 데이터 우선 입력**: `data/structured/YYYY-MM-DD.json` 또는 `latest.json`을 공식 API/수집기 입력으로 사용할 수 있습니다. 다만 공식 원문 검증은 다시 수행합니다.
- **성과 피드백**: 과거 결과 폴더의 `performance.json`을 다음 편집의 참고값으로 사용합니다.
- **Visual QA**: 이미지 규격뿐 아니라 제목/본문 밀도, 데이터 포인트 부족, headline 중복, 템플릿 반복도 검사합니다.

## 결과 파일

`output/YYYY-MM-DD/`에 다음 파일이 생성됩니다.

- `card-01.png` ~ `card-06.png`: 1080×1350 Instagram 카드
- `package.json`: 후보·팩트·편집·디자인·권리 자산 구조화 데이터
- `caption.md`: 내부 검토용 캡션
- `caption-instagram.md`: URL 제거 게시용 캡션
- `editorial-review.md`: 후보 점수, 선정 이유, 편성·템플릿 구성, 승인 체크리스트
- `validation.md`: 팩트·편성·권리 자동 검증
- `visual-qa.md`: 렌더링·가독성·반복성 QA
- `sources.md`: 공식 원문과 시각 자산 권리 감사 정보
- `alt-text.json`: 카드별 대체 텍스트
- `publish-manifest.json`: 승인 대기 상태와 게시 파일 목록
- `instagram-carousel.zip`: 게시 전달 패키지
- `recovery-log.md`: 자동 복구가 실행된 경우의 기록

## 편집 구조

리서치 단계는 모든 대상 리그를 조사해 최대 20개의 후보를 만들 수 있습니다. 이후 편집 단계에서 표지를 제외한 5개 스토리를 고릅니다.

기본 설정은 다음과 같습니다.

- 최소 서로 다른 리그: 3개
- 한 리그 최대 카드: 2장
- 같은 시각 템플릿 연속 반복: 최대 2장
- 최근 게시 이력: 7일
- 성과 참고 기간: 30일

이 값은 `config/settings.toml`에서 변경할 수 있습니다.

## 구조화 스포츠 데이터 연결

공식 API 또는 자체 수집기가 있다면 다음 위치에 JSON을 저장할 수 있습니다.

```
data/structured/2026-09-30.json
```

또는

```
data/structured/latest.json
```

가능하면 데이터에 `provenance`를 포함하세요. 이 파일은 검색보다 먼저 참고되지만, 자동화는 해당 값이 추적 가능한 공식 원문과 일치하는지 다시 확인합니다.

## Instagram 성과 피드백

게시 후 해당 날짜 결과 폴더에 `performance.json`을 저장하면 다음 생성에서 반복 방지와 편집 참고에 사용합니다.

예:

```json
{
  "topic": "KBO 포스트시즌",
  "reach": 18200,
  "likes": 820,
  "comments": 64,
  "saves": 410,
  "shares": 255
}
```

성과 데이터는 “무엇을 더 관심 있게 봤는지”를 참고하기 위한 것이며 사실 검증에는 사용하지 않습니다.

## 실행

Windows에서는 `start.bat`을 실행하거나 PowerShell에서 다음을 사용할 수 있습니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
$env:OPENAI_API_KEY="sk-proj-..."
sports-card-news daily --date 2026-09-30
```

API 비용 없이 전체 흐름을 확인하려면:

```powershell
sports-card-news daily --date 2026-09-30 --fixture fixtures/demo_package.json
```

검증과 테스트:

```powershell
sports-card-news validate fixtures/demo_package.json
sports-card-news render fixtures/demo_package.json --output preview
pytest -q
```

## GitHub Actions

`.github/workflows/daily-card-news.yml`은 매일 오전 8시(Asia/Seoul)에 실행됩니다.

1. 전체 단위 테스트
2. Research → Editorial → Design 생성
3. 팩트·편성·권리 검증
4. PNG 렌더링
5. Visual QA
6. 게시 패키지 ZIP 검사
7. 날짜별 자동화 브랜치 생성/갱신
8. Draft PR 생성/갱신
9. Artifact 14일 보존

저장소의 `Settings → Secrets and variables → Actions`에 `OPENAI_API_KEY`가 필요합니다.

## 디자인 시스템

기본 브랜드는 따뜻한 아이보리 지면, 검정 타이포그래피, 스코어 옐로, 검토 레드를 유지합니다. 콘텐츠별로 다음과 같은 스포츠 문법을 사용합니다.

- Match Result: 팀/선수와 스코어 중심
- Match Preview: 대진·시각·관전 포인트
- Player: 선수 중심 핵심 기록
- Stat / Ranking: 숫자와 순위 중심
- Breaking: 속보 헤더와 한 가지 확정 사실
- Schedule: 일정·시각·상태 중심
- Explainer: 핵심 사실·비교·단계형 데이터 그래픽

외부 사진·로고를 자동으로 가져오지 않습니다. 승인된 자산이 없으면 텍스트와 자체 제작 데이터 그래픽으로 완성합니다.

## 안전장치

생성물은 다음 상황에서 차단됩니다.

- 공식 원문을 직접 확인하지 않은 자료를 “검증 완료”로 표시
- 후보/카드가 존재하지 않거나 미검증 출처를 참조
- 예정·진행 중 정보의 유효기한 누락 또는 만료
- 카드가 선택 후보와 다른 리그·출처를 사용
- 스토리 리그 다양성 부족 또는 한 리그 과다 편성
- 같은 시각 템플릿의 과도한 연속 반복
- URL·도메인·Markdown 링크가 카드 문구에 노출
- 권리 미승인 외부 asset 사용
- 카드 수, 이미지 크기, PNG/RGB 규격 오류
- headline 중복 등 Visual QA 차단 항목

자세한 구조는 `docs/architecture.md`를 참고하세요.
