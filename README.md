# 스포츠 카드뉴스 자동화

KBO·NPB·MLB·EPL·KBL·NBA를 기본 범위로 삼아 매일 스포츠 이슈 후보를 조사하고, 5~6장의 인스타그램 카드뉴스 PNG와 검토 문서를 만드는 Python 도구입니다.

이 프로젝트는 자동 게시기가 아닙니다. 운영안의 원칙에 따라 결과를 GitHub의 **Draft Pull Request**로 올리고, `종목 담당 → 팩트체크·권리 담당 → 편집장`의 사람 승인 후에만 병합하도록 설계했습니다.

## 만들어지는 결과

`output/YYYY-MM-DD/` 아래에 다음 파일이 생성됩니다.

- `card-01.png` ~ `card-06.png`: 1080×1350 카드 이미지
- `package.json`: 후보·팩트·출처·원고의 구조화 데이터
- `caption.md`: 캡션, 해시태그, 카드별 대체 텍스트
- `editorial-review.md`: 후보 점수, 선정 이유, 출처 링크, 승인 체크리스트
- `validation.md`: 자동 차단 항목과 사람 확인 경고

외부 사진·영상·로고는 자동으로 가져오지 않습니다. 기본 렌더러는 텍스트와 자체 제작 도형만 사용해 권리 위험을 줄입니다.

## 로컬 실행

Python 3.11 이상이 필요합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
$env:OPENAI_API_KEY="sk-..."
sports-card-news daily --date 2026-09-29
```

API 비용 없이 전체 흐름을 확인하려면 데모 입력을 사용합니다.

```powershell
sports-card-news daily --date 2026-09-29 --fixture fixtures/demo_package.json
```

개별 명령:

```powershell
sports-card-news validate fixtures/demo_package.json
sports-card-news render fixtures/demo_package.json --output preview
pytest
```

## GitHub 자동화 설정

1. 이 프로젝트를 GitHub 저장소에 push합니다.
2. 저장소의 `Settings → Secrets and variables → Actions`에서 `OPENAI_API_KEY` secret을 추가합니다.
3. `Actions` 탭에서 **Daily sports card news** 워크플로를 한 번 수동 실행해 권한과 결과를 확인합니다.
4. 워크플로는 매일 오전 8시(Asia/Seoul, UTC 23:00)에 실행되어 새 Draft PR을 만듭니다.
5. PR의 카드 이미지·출처·체크리스트를 사람이 검토하고 승인한 뒤 병합합니다.

저장소 설정에서 Actions의 `Workflow permissions`가 `Read and write permissions`를 허용해야 브랜치 push와 PR 생성이 가능합니다. 조직 정책으로 제한되어 있으면 저장소 관리자가 권한을 열어야 합니다.

## 안전장치

다음 조건은 생성물을 차단하거나 검토 경고를 만듭니다.

- 후보가 세 종목보다 적음
- 선정 제목이 후보 목록과 불일치
- 카드가 5~6장이 아니거나 번호가 연속적이지 않음
- 후보·카드가 존재하지 않는 출처 ID를 참조함
- 출처 충돌 또는 시각 소재 권리 `확인 필요`
- 공식 출처 부족, 진행 중 경기, 변경·미검증 팩트, AI가 표시한 위험

모델과 편집 기준은 [`config/settings.toml`](config/settings.toml)에서 바꿀 수 있습니다. 새 리그를 추가할 때는 공식 도메인, 시간대, 경기 상태 정의, 권리 조건, 검토 담당자를 함께 등록하세요.

## 구현 근거

라이브 조사는 OpenAI Responses API의 `web_search` 도구를 사용하고, Pydantic 모델로 구조화된 출력을 받습니다. 모델명은 환경 변수 `OPENAI_MODEL`로 교체할 수 있습니다.

- [OpenAI Web search 가이드](https://developers.openai.com/api/docs/guides/tools-web-search)
- [OpenAI Structured Outputs 가이드](https://developers.openai.com/api/docs/guides/structured-outputs)
- [운영안과 코드의 대응 관계](docs/architecture.md)

## 중요한 운영 원칙

AI가 만든 링크·인용·숫자는 반드시 원문에서 다시 확인해야 합니다. 이 도구는 인스타그램 계정에 게시하거나 예약하지 않으며, GitHub PR 병합도 자동화하지 않습니다.

