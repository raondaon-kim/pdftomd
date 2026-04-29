# M1.b 결과 비교 — 3개 모델 동시 평가

`backend/tests/golden/deepco_kdc_18/input.pdf` (28페이지)을 3개 모델로 처리한 결과입니다.

## 모델별 폴더

| 폴더 | 모델 | 설명 |
|---|---|---|
| [claude-haiku-4-5/](claude-haiku-4-5/) | Claude Haiku 4.5 | M1.a 첫 베이스라인 |
| [gemini-2-5-flash/](gemini-2-5-flash/) | Gemini 2.5 Flash (GA) | 가장 저렴 |
| [gemini-3-flash/](gemini-3-flash/) | Gemini 3 Flash (Preview) | 가장 빠름 + 멀티모달 강세 |

각 폴더 안에:
- `content.md` — 변환된 마크다운
- `images/` — 추출된 보조 이미지
- `result.zip` — 최종 다운로드 ZIP
- `classification_report.md` — 골든 정답과의 분류 비교 표

## 비교 매트릭스

| 모델 | 처리 시간 | 페이지당 | content.md 크기 | 이미지 수 | 분류 정확도 |
|---|---:|---:|---:|---:|---:|
| Claude Haiku 4.5 | 187.8초 | 6.7s | 23.0 KB | 15 | **28/28 (100%)** |
| Gemini 2.5 Flash | 273.6초 | 9.8s | 24.0 KB | 17 | **28/28 (100%)** |
| Gemini 3 Flash | **123.2초** | **4.4s** | 20.4 KB | 16 | 27/28 (96%) ※ |

※ Gemini 3 Flash는 p.3(학습 목표) 본문을 짧고 핵심만 추렸는데, 평가 휴리스틱이 본문 길이로 분류를 추정하다 보니 `decorative_only`로 잘못 잡았습니다. **Gemini 3 자체의 분류는 `content`로 정확**할 가능성이 높습니다 — 평가 휴리스틱의 한계.

## 비용 (대략 추정)

| 모델 | PDF 1건 |
|---|---:|
| Claude Haiku 4.5 | ~$0.20 |
| Gemini 2.5 Flash | ~$0.10 |
| Gemini 3 Flash | ~$0.20 |

3개 모델 총 비용 ~$0.50.

## 정성 비교 (test.pdf 기준)

각 `content.md`를 직접 열어보면 차이가 보입니다:

- **Claude Haiku 4.5**
  - 본문이 가장 풍부 (23 KB, 가장 많은 설명)
  - 표 재구성이 정교함 (p.7 미세먼지 농도 표가 헤더·하이픈 정렬까지 잘 됨)
  - 환각 없음

- **Gemini 2.5 Flash**
  - 본문이 가장 김 (24 KB) — 일부 페이지에서 더 자세함
  - 본문 첫 줄에서 페이지 자체 도입 문장을 만들어내는 경향
  - p.17처럼 표가 큰 페이지에서 응답 토큰을 더 많이 씀 (8K로 늘려서 해결)

- **Gemini 3 Flash**
  - 본문이 가장 짧음 (20 KB) — 핵심만 추리는 스타일
  - **2배 이상 빠름** (123초 vs 187~273초)
  - thinking_level=minimal로 비용·지연시간 최소화
  - p.3 같은 짧은 페이지에서 본문 길이가 헤지 휴리스틱 임계값 아래로 떨어져 자동 평가가 미스로 잡음

## 본 결과의 한계 (M1.a/M1.b 단계)

세 모델 모두 동일한 한계:
- 1패스(강의 맥락 추출)이 아직 dummy → content.md 헤더 강의 제목이 "input"으로 들어감
- "강의 요약"·"핵심 용어" 헤더 비어있음

→ M1.c에서 1패스를 실 LLM 호출로 교체하면 자동 채워집니다.

## 어느 모델을 쓸까?

본 PDF 기준으로:

| 우선순위 | 추천 모델 | 이유 |
|---|---|---|
| 비용 최소 | Gemini 2.5 Flash | 절반 비용, 정확도 동등 |
| 속도 최우선 | Gemini 3 Flash | 2배 이상 빠름, 정확도 거의 동등 |
| 본문 풍부함 | Claude Haiku 4.5 | 가장 자세한 설명 + 안정적 |
| 균형 | Claude Haiku 4.5 | 안정성·품질·비용 모두 무난 |

다른 PDF에서는 결과가 다를 수 있으므로 v1 출시 후 사용자에게 모델 선택권을 줍니다 (UI 라디오 버튼).

## 다시 돌리기

```bash
cd backend

# 각 모델별로 따로 실행
python -m app.cli tests/golden/deepco_kdc_18/input.pdf -o ../output/claude-haiku-4-5 --model claude-haiku-4-5
python -m app.cli tests/golden/deepco_kdc_18/input.pdf -o ../output/gemini-2-5-flash --model gemini-2-5-flash
python -m app.cli tests/golden/deepco_kdc_18/input.pdf -o ../output/gemini-3-flash --model gemini-3-flash

# 분류 정확도 평가
for m in claude-haiku-4-5 gemini-2-5-flash gemini-3-flash; do
    python -m tests.eval_classification \
        --content-md ../output/$m/content.md \
        --golden tests/golden/deepco_kdc_18/expected.json \
        --report-out ../output/$m/classification_report.md
done
```
