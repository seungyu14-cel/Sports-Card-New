# 운영안과 구현 대응 관계

## 7장 토큰 최적화 흐름

1. **Research**가 KBO·KBL·NPB·EPL·NBA를 모두 조사하고 약 10개의 검증 후보를 만듭니다.
2. **Editorial**이 각 카테고리에서 대표 이슈 1개씩, 총 5개를 선택합니다.
3. 카드 구조는 `COVER 1 + ISSUE 5 + SUMMARY 1 = 7장`입니다.
4. 2~6번은 KBO/KBL/NPB/EPL/NBA가 정확히 한 번씩 등장합니다. 순서는 뉴스 가치에 따라 바뀔 수 있습니다.
5. 7번 SUMMARY는 2~6번의 다섯 이슈만 한눈에 정리합니다.
6. **Design**은 스포츠 전용 템플릿과 실제 `visual_items`를 설계합니다.
7. `assets.py`는 2~6번 카드에 대해서만 검증된 원문 페이지의 `og:image` / `twitter:image`를 탐색합니다.
8. `validation.py`는 7장 구조, 5개 이슈 중복, 다섯 카테고리 1개씩, 후보-출처-이미지 관계를 검사합니다.
9. `renderer.py`는 승인된 뉴스 이미지가 있으면 사용하고 실패하면 데이터 그래픽으로 fallback 합니다.
10. `visual_qa.py`는 7개 PNG와 7번 summary를 검사합니다.
11. 결과는 사람 승인 전 Draft PR로 제출합니다.

## 카드 역할

| 페이지 | league | 역할 |
|---|---|---|
| 1 | COVER | 표지 |
| 2~6 | KBO/KBL/NPB/EPL/NBA | 각 카테고리 대표 이슈 1개 |
| 7 | SUMMARY | 5개 이슈 한눈 요약 |

## 토큰 절감

- 후보 목표를 10개로 축소
- 메인 이슈를 5개로 축소
- 카드 출력을 7장으로 축소
- OpenAI 최대 출력 토큰을 16,000으로 축소
- Research/Editorial/Design 프롬프트를 짧게 재작성

공식 원문 검증, 이미지 연결 검증, 사람 승인 단계는 축소하지 않습니다.
