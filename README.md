# 스포츠 카드뉴스 자동화 스튜디오

KBO·NPB·MLB·EPL·KBL·NBA를 기본 범위로 삼아 매일 스포츠 이슈 후보를 조사하고, 5~6장의 인스타그램 카드뉴스 PNG와 검토 문서를 만드는 웹 앱과 Python 도구입니다.

이 프로젝트는 자동 게시기가 아닙니다. 운영안의 원칙에 따라 결과를 GitHub의 **Draft Pull Request**로 올리고, `종목 담당 → 팩트체크·권리 담당 → 편집장`의 사람 승인 후에만 병합하도록 설계했습니다.

## 만들어지는 결과

`output/YYYY-MM-DD/` 아래에 다음 파일이 생성됩니다.

- `card-01.png` ~ `card-06.png`: 1080×1350 카드 이미지
- `package.json`: 후보·팩트·출처·원고의 구조화 데이터
- `caption.md`: 캡션, 해시태그, 카드별 대체 텍스트
- `editorial-review.md`: 후보 점수, 선정 이유, 출처 링크, 승인 체크리스트
- `validation.md`: 자동 차단 항목과 사람 확인 경고
- `recovery-log.md`: 검증 실패가 자동 해결된 경우의 재조사 사유와 복구 결과

외부 사진·영상·로고는 자동으로 가져오지 않습니다. 기본 렌더러는 텍스트와 자체 제작 도형만 사용해 권리 위험을 줄입니다.

### SPORTS DESK 디자인 시스템

카드 이미지는 인스타그램 4:5 비율에 맞춘 `SPORTS DESK` 에디토리얼 디자인으로 생성됩니다. 따뜻한 아이보리 지면, 검정 타이포그래피, 스코어 옐로 강조, 검토 상태를 나타내는 빨강을 공통으로 사용합니다. 표지는 큰 제목과 에디션 정보에 집중하고, 본문은 카드 번호가 아니라 실제 정보 유형에 따라 핵심 팩트·3면 스크린·홈/원정 좌석·장소·단계·일정·비교·경기 상태·출처·승인 도식 중 하나를 사용합니다. 외부 사진과 리그·구단 로고가 없어도 완성된 시각 체계를 유지하도록 설계했습니다.

카드 제목과 본문에는 URL, 도메인, Markdown 링크를 넣지 않습니다. 실제 주소는 `package.json`의 `facts.url`, `caption.md`, `editorial-review.md`에 보관하고 이미지에는 짧은 출처 ID만 표시합니다. 오래된 패키지에 링크가 남아 있어도 렌더링 직전에 한 번 더 제거합니다.

## 가장 쉬운 실행 방법

Windows에서 [`start.bat`](start.bat)을 더블클릭합니다. 최초 실행은 가상환경과 필요한 패키지를 자동으로 준비한 뒤 `http://127.0.0.1:8787`을 엽니다.

웹 화면에서 다음 순서로 사용합니다.

1. [OpenAI API Keys](https://platform.openai.com/api-keys)에서 프로젝트 키를 발급합니다.
2. `OpenAI API 연결`에 `sk-proj-...` 키를 입력하고 **저장하고 연결 확인**을 누릅니다.
3. 기본 모델 `gpt-6-astra`를 그대로 사용하거나 계정에서 사용할 수 있는 OpenAI 모델 ID로 바꿉니다.
4. 날짜를 선택하고 **라이브 제작**을 누릅니다.
5. API 키 없이 확인하려면 **데모 실행**을 누릅니다.
6. 생성된 카드, 캡션, 출처를 확인하고 사람 승인 후 게시합니다.

API 키는 로컬 `.env` 파일에만 저장되고 GitHub에는 올라가지 않습니다. 웹 서버는 외부 네트워크가 아닌 `127.0.0.1`에서만 열립니다.

PowerShell에서는 다음 명령으로 실행할 수 있습니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

## CLI 실행

Python 3.11 이상이 필요합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
$env:OPENAI_API_KEY="sk-proj-..."
$env:OPENAI_MODEL="gpt-6-astra"
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

라이브 생성물이 검증에 실패하면 프로그램은 차단 원인을 자동으로 분석하고 공식 출처를 다시 조사합니다. 충돌한 주장은 검증 가능한 공식 원문으로 교체하거나, 해결할 수 없으면 관련 주제를 폐기하고 다른 검증 가능한 이슈로 전체 원고를 다시 작성합니다. 기본값은 최대 2회의 자동 복구이며 `config/settings.toml`의 `auto_repair_attempts`에서 0~3회로 조정할 수 있습니다. 복구에 성공해도 과정은 `recovery-log.md`에 남고, 설정된 횟수 안에 해결되지 않으면 잘못된 정보를 통과시키지 않고 작업을 중단합니다.

저장소 설정에서 Actions의 `Workflow permissions`가 `Read and write permissions`를 허용해야 브랜치 push와 PR 생성이 가능합니다. 조직 정책으로 제한되어 있으면 저장소 관리자가 권한을 열어야 합니다.

## 안전장치

다음 조건은 생성물을 차단하거나 검토 경고를 만듭니다.

- 후보가 세 종목보다 적음
- 선정 제목이 후보 목록과 불일치
- 카드가 5~6장이 아니거나 번호가 연속적이지 않음
- 후보·카드가 존재하지 않는 출처 ID를 참조함
- 카드 문구에 URL·도메인·Markdown 링크가 포함됨
- 카드 본문이 180자를 초과하거나 내용과 시각 템플릿이 맞지 않음
- 출처 충돌 또는 시각 소재 권리 `확인 필요`
- 후보·카드가 `검증 완료`가 아닌 출처를 직접 참조함
- 공식 출처 부족, 진행 중 경기, 변경·미검증 팩트, AI가 표시한 위험

모델과 편집 기준은 [`config/settings.toml`](config/settings.toml)에서 바꿀 수 있습니다. 새 리그를 추가할 때는 공식 도메인, 시간대, 경기 상태 정의, 권리 조건, 검토 담당자를 함께 등록하세요.

## 구현 근거

라이브 조사는 OpenAI Responses API에 `web_search` 도구와 Pydantic 구조화 출력을 적용합니다. 모델명은 환경 변수 `OPENAI_MODEL` 또는 웹 화면에서 교체할 수 있습니다.

- [OpenAI 웹 검색](https://developers.openai.com/api/docs/guides/tools-web-search)
- [OpenAI 구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI 운영 환경 보안 지침](https://developers.openai.com/api/docs/guides/production-best-practices)
- [운영안과 코드의 대응 관계](docs/architecture.md)

## 중요한 운영 원칙

AI가 만든 링크·인용·숫자는 반드시 원문에서 다시 확인해야 합니다. 이 도구는 인스타그램 계정에 게시하거나 예약하지 않으며, GitHub PR 병합도 자동화하지 않습니다.
