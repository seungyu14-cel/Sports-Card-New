# 운영안과 구현 대응 관계

## 하루 한 편 흐름

1. **Research**가 KBO·KBL·NPB·EPL·NBA 5개 카테고리를 모두 조사하고 8개 이슈를 고를 수 있도록 후보 풀을 만듭니다.
2. 후보마다 중요도·한국 독자 관련성·출처 신뢰도·설명 가치·최신성·팬 관심도·시각화 잠재력·독창성을 기록합니다.
3. **Editorial**은 총 10장을 구성합니다. 1번은 COVER, 2~9번은 서로 다른 8개 이슈, 10번은 SUMMARY입니다.
4. 2~9번에는 5개 카테고리가 모두 들어가며 카테고리당 최대 2개까지만 허용합니다. 정상 분포는 2·2·2·1·1입니다.
5. **Design**은 이슈 유형에 맞춰 match_result, match_preview, player, stat, ranking, breaking, schedule 등을 배치하고 10번에는 summary 템플릿을 사용합니다.
6. AI는 뉴스 이미지 URL을 추측하지 않습니다. `assets.py`가 검증 완료된 실제 원문 페이지에서 `og:image` / `twitter:image`를 읽어 대표 이미지를 발견합니다.
7. 운영 정책상 사용 허용된 뉴스 이미지는 `VisualAsset`에 원문 Fact, URL, 크레딧, 사용 범위와 승인 근거를 기록한 뒤 카드와 연결합니다.
8. `validation.py`가 10장 구조, 8개 이슈 중복 여부, 5개 카테고리 포함, 2개 상한, 후보-카드-출처 관계, 뉴스 이미지와 원문 Fact 관계를 검사합니다.
9. 검증 실패 시 공식 원문 재조사와 전체 패키지 자동 복구를 제한 횟수만큼 수행합니다.
10. `renderer.py`는 승인된 뉴스 이미지가 있으면 사진 중심 패널을 렌더링하고 이미지 로드가 실패하면 데이터 그래픽으로 fallback 합니다.
11. `visual_qa.py`는 정확히 10장의 PNG, 중복 headline, 템플릿 편중, 마무리 summary 등을 검사합니다.
12. 결과는 Draft PR과 Artifact로 제출되며 게시 여부는 사람이 최종 결정합니다.

## 카드 데이터 역할

| 페이지 | league | candidate_title | 역할 |
|---|---|---|---|
| 1 | COVER | 빈 값 | 표지 |
| 2~9 | KBO/KBL/NPB/EPL/NBA | 실제 후보 title | 서로 다른 8개 메인 이슈 |
| 10 | SUMMARY | 빈 값 | 여덟 이슈 한눈 요약 |

## 뉴스 이미지 자산

뉴스 이미지는 다음 조건을 충족할 때 자동 연결됩니다.

- 카드가 2~9번 메인 이슈일 것
- 카드의 `source_ids` 중 하나가 원문 직접 확인 + 검증 완료일 것
- 해당 원문 페이지에 `og:image` 또는 `twitter:image`가 있을 것
- `allow_news_images=true`
- `auto_approve_verified_news_images=true`

등록되는 주요 필드:

- `asset_type = news_image`
- `source_fact_id`
- `source_url`
- `rights_status = 뉴스 이미지 사용 승인`
- `usage_scope = ["instagram_post"]`
- `license_evidence`
- `approved_for_publish = true`

렌더러가 이미지 다운로드에 실패해도 카드 자체는 데이터 그래픽으로 생성됩니다.

## 사람 승인

자동화는 인스타그램 게시, Draft PR 병합, 정정 판단을 자동 수행하지 않습니다. 팩트·이미지·최종 문구를 검토한 뒤 사람이 게시를 결정합니다.
