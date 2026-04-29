# TESTING — 테스트 전략

## 1. 테스트 피라미드

```
        ┌─────────────┐
        │  E2E (수동)  │   1~2개 시나리오, 실제 PDF
        ├─────────────┤
        │ Integration │   파이프라인 전체 (LLM 모킹)
        ├─────────────┤
        │   Unit      │   pdf_io, crop, packager, prompts 검증
        └─────────────┘
```

개인용 도구라 100% 커버리지 추구 안 함. **회귀 방지에 가장 도움 되는 곳에 집중**:
1. 골든 데이터셋(LLM 응답 정확성)
2. 패키저(마크다운/ZIP 생성)
3. API 엔드포인트(상태 전이)

## 2. 골든 데이터셋

### 2.1 정답 데이터

`backend/tests/golden/deepco_kdc_18/`:

```
deepco_kdc_18.pdf                    # 원본
expected.json                        # 페이지별 정답 (수동 작성)
expected_images/                     # 정답 크롭 이미지
  06_데이터분석모델.png
  07_모델생성프로세스.png
  ...
```

### 2.2 `expected.json` 구조

```json
{
  "total_pages": 28,
  "pages": [
    {
      "page_num": 1,
      "classification": "cover",
      "title_contains": [],
      "should_have_image": false
    },
    {
      "page_num": 6,
      "classification": "content",
      "title_contains": ["데이터", "분석", "모델"],
      "markdown_must_contain": [
        "데이터 분석 모델",
        "지도학습"
      ],
      "should_have_image": true,
      "expected_bbox_loose": {
        "x_min_max": 100,
        "y_min_max": 200,
        "x_max_min": 800,
        "y_max_min": 800
      }
    },
    {
      "page_num": 19,
      "classification": "decorative_only",
      "title_contains": ["실습", "영상"],
      "should_have_image": false
    }
  ]
}
```

`expected_bbox_loose`는 **느슨한 검사** — bbox가 정확히 일치할 필요 없고 "이 영역을 포함하면 OK" 판정.

### 2.3 평가 지표

| 지표 | 목표 |
|---|---|
| 분류 정확도 | ≥ 90% |
| 본문 페이지에서 이미지 추출 여부 정확도 | ≥ 95% |
| 마크다운 필수 키워드 포함률 | ≥ 90% |
| bbox 합리적 범위 (헤더/푸터 제외) | ≥ 85% |

## 3. 단위 테스트

### 3.1 `tests/test_pdf_io.py`

```python
def test_get_page_count():
    assert get_page_count("tests/golden/deepco_kdc_18.pdf") == 28

def test_rasterize_pages(tmp_path):
    out = rasterize_pages("tests/golden/deepco_kdc_18.pdf", tmp_path, dpi=100)
    assert len(out) == 28
    assert all(p.exists() for p in out)
    assert all(p.suffix == ".png" for p in out)

def test_extract_text_per_page():
    texts = extract_text_per_page("tests/golden/deepco_kdc_18.pdf")
    assert len(texts) == 28
    assert "데이터 분석 모델" in texts[5]  # 페이지 6 = 인덱스 5
```

### 3.2 `tests/test_crop.py`

```python
def test_denormalize_bbox():
    bbox = BBox(x_min=0, y_min=0, x_max=500, y_max=1000)
    assert denormalize_bbox(bbox, 1000, 2000) == (0, 0, 500, 2000)

def test_crop_produces_png(tmp_path):
    src_image = "tests/fixtures/sample_page.png"
    bbox = BBox(x_min=100, y_min=100, x_max=900, y_max=900)
    out = crop_region(src_image, bbox, tmp_path / "out.png")
    assert out.exists()
    assert Image.open(out).size[0] > 0
```

### 3.3 `tests/test_packager.py`

```python
def test_build_markdown_skips_cover_pages():
    pages = [
        PageAnalysis(page_num=1, classification="cover", title="", markdown_body="", reasoning=""),
        PageAnalysis(page_num=2, classification="content", title="제목", markdown_body="본문", reasoning=""),
    ]
    md = build_markdown(pages, pdf_filename="test")
    assert "제목" in md
    assert "슬라이드 1" not in md  # cover 스킵
    assert "슬라이드 2" in md

def test_build_markdown_includes_image_link():
    pages = [PageAnalysis(
        page_num=6, classification="content",
        title="제목", markdown_body="본문",
        image_filename="06_제목.png",
        image_caption="설명",
        image_region=BBox(x_min=0, y_min=0, x_max=1000, y_max=1000),
        reasoning="",
    )]
    md = build_markdown(pages, pdf_filename="test")
    assert "![설명](images/06_제목.png)" in md

def test_zip_contains_files(tmp_path):
    # ...
```

### 3.4 `tests/test_prompts.py`

```python
def test_system_prompt_contains_classification_rules():
    prompt = get_system_prompt_template()
    for cls in ["content", "section_divider", "cover", "decorative_only"]:
        assert cls in prompt

def test_pydantic_validation_rejects_bad_bbox():
    bad = {"x_min": -10, "y_min": 0, "x_max": 100, "y_max": 100}
    with pytest.raises(ValidationError):
        BBox(**bad)

def test_build_system_prompt_injects_context():
    """1패스 결과가 시스템 프롬프트 동적 부분에 박히는지"""
    ctx = LectureContext(
        title="테스트 강의",
        topic_summary="요약",
        slide_outline=[{"page": 1, "title": "표지", "one_line": "강의 표지"}],
        key_terms=["PAPS", "BMI"],
        domain_hints="AI 교육",
    )
    prompt = build_system_prompt(ctx)
    assert "테스트 강의" in prompt
    assert "PAPS" in prompt
    assert "p.1 표지" in prompt
```

### 3.5 `tests/test_providers.py`

```python
def test_claude_provider_requires_key():
    with pytest.raises(TypeError):
        ClaudeHaikuProvider()  # api_key 필수

def test_gemini_provider_variants():
    p25 = GeminiProvider(api_key="x", variant="2-5")
    p3 = GeminiProvider(api_key="x", variant="3")
    assert p25.is_preview is False
    assert p3.is_preview is True
    assert p3.temperature == 1.0
    assert p3.thinking_level == "minimal"

def test_make_provider_dispatches_correctly():
    s = Settings(anthropic_api_key="x", gemini_api_key="y")
    assert isinstance(make_provider("claude-haiku-4-5", s), ClaudeHaikuProvider)
    assert isinstance(make_provider("gemini-3-flash", s), GeminiProvider)

def test_make_provider_raises_for_missing_key():
    s = Settings(anthropic_api_key=None, gemini_api_key="y")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        make_provider("claude-haiku-4-5", s)

def test_list_available_providers_marks_disabled():
    s = Settings(anthropic_api_key="x", gemini_api_key=None)
    infos = list_available_providers(s)
    by_id = {info.id: info for info in infos}
    assert by_id["claude-haiku-4-5"].enabled is True
    assert by_id["gemini-2-5-flash"].enabled is False
    assert by_id["gemini-3-flash"].enabled is False

def test_pydantic_to_gemini_schema_handles_optional():
    """Optional[BBox] → nullable: true"""
    schema = pydantic_to_gemini_schema(PageAnalysis)
    assert schema["properties"]["image_region"].get("nullable") is True
    # anyOf 같은 비호환 필드가 없어야 함
    import json
    assert "anyOf" not in json.dumps(schema)
```

## 4. 통합 테스트 (LLM 모킹)

LLM은 비용·시간·비결정성 때문에 모킹. provider 추상화 덕분에 모델 어떤 거든 똑같이 모킹 가능:

```python
# tests/test_pipeline.py
from unittest.mock import MagicMock

def test_pipeline_end_to_end_with_mock_provider(tmp_path):
    """LLMProvider를 모킹해서 파이프라인 흐름만 검증."""
    mock_provider = MagicMock()
    mock_provider.name = "claude-haiku-4-5"
    mock_provider.call_lecture_context.return_value = load_fixture("golden_lecture_context.json")
    mock_provider.call_page_analysis.side_effect = lambda **kwargs: \
        load_fixture(f"golden_page_p{kwargs['page_num']:02d}.json")

    result = run_pipeline(
        job_id="test-job",
        pdf_path="tests/golden/deepco_kdc_18.pdf",
        output_dir=tmp_path,
        provider=mock_provider,  # ← 직접 주입
    )

    assert (tmp_path / "content.md").exists()
    assert (tmp_path / "result.zip").exists()
    md = (tmp_path / "content.md").read_text()
    assert "데이터 분석 모델이란?" in md
    # content 페이지 14개 중 보조 이미지가 있는 것만 추출
    assert len(list((tmp_path / "images").glob("*.png"))) == EXPECTED_IMAGE_COUNT

def test_provider_factory_rejects_missing_key():
    """API 키 없으면 ValueError"""
    from app.pipeline.providers import make_provider
    settings = Settings(anthropic_api_key=None, gemini_api_key=None)
    with pytest.raises(ValueError, match="API_KEY"):
        make_provider("claude-haiku-4-5", settings)

def test_gemini_schema_conversion():
    """Pydantic → Gemini responseSchema 변환 검증"""
    from app.pipeline.providers.schemas import pydantic_to_gemini_schema
    from app.models import PageAnalysis

    schema = pydantic_to_gemini_schema(PageAnalysis)
    # Gemini는 anyOf 미지원 — nullable로 변환됐어야 함
    assert "anyOf" not in json.dumps(schema)
    # image_region이 nullable
    assert schema["properties"]["image_region"].get("nullable") is True
```

## 5. LLM 평가 테스트 (실제 호출)

CI에서는 안 돌리고 **수동/주기적**으로 실행. `pytest -m llm_eval`. 다중 모델 지원이라 모델별로 별도 평가:

### 5.1 모델별 단일 평가

```python
@pytest.mark.llm_eval
@pytest.mark.parametrize("model_id", [
    "claude-haiku-4-5",
    "gemini-2-5-flash",
    "gemini-3-flash",
])
def test_classification_accuracy_per_model(model_id):
    """각 모델로 골든 PDF를 처리해 정답과 비교."""
    expected = load_expected("deepco_kdc_18")
    actual = run_pipeline_real(
        "tests/golden/deepco_kdc_18.pdf",
        model_id=model_id,
    )

    correct = sum(
        1 for exp, act in zip(expected["pages"], actual.pages)
        if exp["classification"] == act.classification
    )
    accuracy = correct / len(expected["pages"])
    assert accuracy >= 0.90, f"{model_id} 분류 정확도 {accuracy:.0%}"
```

### 5.2 모델 간 비교 (벤치마크 모드)

같은 PDF·같은 정답으로 3개 모델을 비교 → README나 UI에 공개할 표 생성:

```python
@pytest.mark.llm_eval
def test_compare_all_models_on_golden():
    """3개 모델을 골든 셋으로 돌려 결과 비교 표 생성."""
    expected = load_expected("deepco_kdc_18")
    results = {}

    for model_id in ALL_MODEL_IDS:
        actual = run_pipeline_real(
            "tests/golden/deepco_kdc_18.pdf",
            model_id=model_id,
        )
        results[model_id] = {
            "classification_accuracy": _accuracy(expected, actual),
            "image_extraction_correctness": _image_correctness(expected, actual),
            "markdown_keyword_recall": _keyword_recall(expected, actual),
            "hallucination_rate": _hallucination_rate(expected, actual),
            "avg_seconds_per_page": _avg_seconds(actual),
            "total_cost_usd": _total_cost(actual),
        }

    # 결과를 markdown 표로 출력 (수동 비교용)
    print(_format_comparison_table(results))
    # 어느 모델도 90% 미달이면 경고
    for model_id, m in results.items():
        assert m["classification_accuracy"] >= 0.90, \
            f"{model_id} 정확도 {m['classification_accuracy']:.0%}"
```

출력 예시:

```
| 모델              | 분류 정확도 | 이미지 추출 | 키워드 재현율 | 환각률 | 페이지당 시간 | 총 비용 |
|---|---|---|---|---|---|---|
| Claude Haiku 4.5  | 93%        | 92%         | 88%           | 3%     | 4.2s         | $0.19  |
| Gemini 2.5 Flash  | 89%        | 90%         | 85%           | 5%     | 3.1s         | $0.09  |
| Gemini 3 Flash    | 95%        | 94%         | 92%           | 2%     | 3.8s         | $0.21  |
```

이 표는 **사용자가 모델을 고를 때 참고용**으로 README나 UI에 공개. v1 출시 시 1회 측정, 모델 업데이트 때마다 재측정.

### 5.3 평가 지표 정의

- **classification_accuracy**: `expected.classification == actual.classification` 비율
- **image_extraction_correctness**: `should_have_image` 일치 비율 (bbox 정확성은 별개)
- **markdown_keyword_recall**: 정답의 `markdown_must_contain` 키워드가 실제 결과 본문에 포함된 비율 (자급자족성 측정 — 특히 다이어그램 정보 누락 검출)
- **hallucination_rate**: 실제 결과에 정답에 없는 고유명사/숫자가 등장한 비율 (모델이 추측해서 만들어낸 내용 검출)
- **avg_seconds_per_page**: 1패스+2패스 합산 / 본문 페이지 수
- **total_cost_usd**: 실제 호출 응답에서 누적한 비용

### 5.4 Gemini 3 비결정성 주의

Gemini 3는 temperature=1.0이라 같은 입력에 다른 출력을 줍니다. 평가 결과 ±2~3% 분산을 가정하고:
- 결과가 임계 근처(예: 89~91%)면 **3회 평균**으로 판정
- 골든셋에 페이지가 충분히 많아야(28+) 분산이 줄어듦

### 5.5 단일 모델 평가 (간이)

Gemini 3가 가장 잘하는지 등 어림짐작은 위 매트릭스로. 빠른 회귀 확인용 — 하나의 모델만 돌리는 단축 명령:

```bash
pytest -m llm_eval -k "claude-haiku" -v
pytest -m llm_eval -k "gemini-3" -v
```

## 6. API 테스트

FastAPI TestClient로 엔드포인트 검증:

```python
# tests/test_api.py
from fastapi.testclient import TestClient

def test_post_jobs_with_valid_pdf(client: TestClient):
    with open("tests/golden/deepco_kdc_18.pdf", "rb") as f:
        res = client.post(
            "/jobs",
            files={"file": ("test.pdf", f, "application/pdf")},
            data={"model": "claude-haiku-4-5"},
        )
    assert res.status_code == 201
    body = res.json()
    assert "job_id" in body
    assert body["status"] == "queued"
    assert body["model"] == "claude-haiku-4-5"

def test_post_jobs_rejects_non_pdf(client: TestClient):
    res = client.post(
        "/jobs",
        files={"file": ("test.txt", b"not a pdf", "text/plain")},
        data={"model": "claude-haiku-4-5"},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_FILE_TYPE"

def test_post_jobs_rejects_unknown_model(client: TestClient):
    with open("tests/golden/deepco_kdc_18.pdf", "rb") as f:
        res = client.post(
            "/jobs",
            files={"file": ("test.pdf", f, "application/pdf")},
            data={"model": "gpt-4"},
        )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_MODEL"

def test_post_jobs_rejects_model_without_key(client_no_gemini: TestClient):
    """GEMINI_API_KEY가 없는 환경에서 Gemini 모델 선택 시"""
    with open("tests/golden/deepco_kdc_18.pdf", "rb") as f:
        res = client_no_gemini.post(
            "/jobs",
            files={"file": ("test.pdf", f, "application/pdf")},
            data={"model": "gemini-3-flash"},
        )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "MODEL_NOT_AVAILABLE"

def test_get_models_returns_available(client: TestClient):
    res = client.get("/models")
    assert res.status_code == 200
    models = res.json()["models"]
    ids = {m["id"] for m in models}
    assert ids == {"claude-haiku-4-5", "gemini-2-5-flash", "gemini-3-flash"}
    # 키 있는 모델은 enabled
    for m in models:
        assert isinstance(m["enabled"], bool)
        assert isinstance(m["is_preview"], bool)

def test_get_job_returns_404_for_unknown(client: TestClient):
    res = client.get("/jobs/nonexistent")
    assert res.status_code == 404
```

## 7. 프론트엔드 테스트

v1 범위에서는 최소화:

- 컴포넌트 단위 테스트 안 함 (UI가 단순)
- E2E 1개: Playwright 또는 수동 체크리스트

수동 E2E 체크리스트:

```
[ ] /에 접속 → 드롭존 + 모델 라디오 보임
[ ] 모델 라디오에 3개 옵션 표시 (Claude Haiku, Gemini 2.5, Gemini 3)
[ ] Gemini 3에 "베타" 라벨 표시
[ ] 키 없는 모델은 회색 + 호버 안내
[ ] 텍스트 파일 업로드 시도 → 거부 메시지
[ ] PDF 파일 업로드 + 모델 선택 → /jobs/{id} 이동
[ ] 진행 화면에 사용 모델 배지 표시
[ ] 진행률 0~100%까지 부드럽게 증가 (extracting_context → analyzing_page 단계 전환)
[ ] 처리 완료 → /jobs/{id}/done 이동
[ ] 다운로드 버튼 → ZIP 받아짐
[ ] ZIP 압축 해제 → content.md, images/ 존재
[ ] content.md 헤더에 강의 요약·핵심 용어·사용 모델 등장
[ ] content.md에서 이미지 참조가 깨지지 않음
[ ] 같은 PDF를 다른 모델로 다시 처리 → 결과가 달라짐 (모델 선택이 실제 동작)
```

## 8. CI 구성 (선택)

개인용이라 무거운 CI는 안 만들지만 GitHub Actions 한 개:

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: |
          sudo apt-get install -y poppler-utils
          pip install -e backend
          pip install pytest pytest-asyncio
      - run: pytest backend/tests -v -m "not llm_eval"

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: |
          cd frontend
          npm ci
          npm run build
          npm run lint
```

LLM 평가 테스트는 수동 실행 — API 키가 PR에 노출되면 안 되므로.

## 9. 성능 벤치마크

`tests/benchmark.py`:

```python
def bench_full_pipeline():
    """전체 파이프라인 처리 시간 측정 (LLM 호출 포함)."""
    start = time.time()
    result = run_pipeline_real("tests/golden/deepco_kdc_18.pdf")
    elapsed = time.time() - start
    print(f"28페이지 처리: {elapsed:.1f}초 ({elapsed/28:.1f}초/페이지)")
    assert elapsed < 300  # 5분 이내
```

목표: 페이지당 ≤ 10초 (28페이지 ≤ 5분).
