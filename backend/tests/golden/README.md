# Golden Dataset

회귀 테스트용 정답 데이터. 다양한 슬라이드 스타일의 PDF를 누적합니다.

## 구조

```
backend/tests/golden/
├── README.md                  # 이 파일
└── {pdf_slug}/
    ├── input.pdf              # 원본 PDF
    ├── expected.json          # 페이지별 정답 (수동 작성)
    └── expected_images/       # (선택) 정답 크롭 이미지
```

`{pdf_slug}` 명명: 영소문자 + 숫자 + 언더스코어. 예: `deepco_kdc_18`, `kdc_19`, `coursera_ml_intro`.

## 현재 보유 PDF

| 슬러그 | 페이지 | 출처 / 스타일 |
|---|---|---|
| `deepco_kdc_18` | 28 | 딥코 KDC 18회차 — 한국어 / PowerPoint / 비교 박스·다이어그램·블록 코드 캡처 혼합 |

## 새 PDF 추가하기

1. 새 폴더 생성: `mkdir backend/tests/golden/<slug>`
2. PDF 복사: `cp my.pdf backend/tests/golden/<slug>/input.pdf`
3. `_inspect_pdf.py` 같은 스크립트로 페이지별 텍스트/이미지/벡터 객체 통계 확인
4. 페이지마다 분류(`content` / `section_divider` / `cover` / `decorative_only`) 결정
5. `expected.json` 작성 (`deepco_kdc_18/expected.json` 참조)
   - 본문 페이지의 `markdown_must_contain`은 환각 검출보다 누락 검출 위주로 (있으면 좋은 키워드)
   - `should_have_image`는 시각자료가 텍스트로 풀어쓰기 어려운 경우만 `true`
   - `expected_bbox_loose`는 헤더(상단 ~10%)·푸터(하단 ~10%) 제외 영역에 들어가는지 느슨하게 검사
6. `lecture_context` 섹션은 1패스 검증용 — 강의 전체 제목/용어/도메인 단서

## 평가 지표 (`expected.json` 사용)

- 분류 정확도: `expected.classification == actual.classification` 비율
- 키워드 재현율: `markdown_must_contain` 단어가 결과 본문에 포함된 비율
- 이미지 첨부 정합성: `should_have_image == (actual.image_region is not None)` 비율
- 환각 검출: `hallucination_red_flags.terms` 단어가 결과에 등장하면 경고

## 다양한 PDF 스타일을 모으는 이유

도구는 강의 슬라이드 PDF 일반을 다뤄야 합니다. 단일 PDF에 과적합된 프롬프트를 만들지 않으려면 다음 변종을 누적할 가치가 있습니다:

- **레이아웃**: 좌우 비교 / 그리드 / 풀블리드 다이어그램 / 불릿만 / 코드 위주
- **언어**: 한국어 / 영어 / 혼합
- **출처**: PowerPoint / Keynote / Google Slides / LaTeX Beamer
- **페이지 수**: 짧음(~15) / 중간(~30) / 김(~80, 1패스 모자이크 샘플링 트리거)
- **시각자료 밀도**: 텍스트 위주 / 다이어그램 위주 / UI 캡처 위주 / 차트 위주
