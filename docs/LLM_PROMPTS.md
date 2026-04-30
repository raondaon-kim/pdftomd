# LLM_PROMPTS — Claude Vision 프롬프트 설계

이 문서는 **이 프로젝트의 핵심**입니다. 프롬프트 품질이 곧 도구의 품질입니다.

## 0. 출력 모드 — "종합 재처리"

이 도구의 출력 마크다운은 단순한 OCR/텍스트 추출이 아닙니다. **슬라이드의 텍스트와 시각자료(다이어그램·표·박스·화살표)를 LLM이 함께 이해해서 의미를 텍스트로 풀어쓴 자급자족(self-contained) 마크다운**을 만듭니다.

| 비교 | 단순 추출 (X) | 종합 재처리 (O, 이 도구) |
|---|---|---|
| 다이어그램 | 이미지로 떼고 끝 | 다이어그램의 의미를 텍스트로 설명 + 보조 이미지 첨부 |
| 박스/카드 | 박스별 텍스트 나열 | 박스가 표현하려는 관계·구조를 풀어씀 |
| 표 | 이미지로 떼고 끝 | 마크다운 표로 재구성 |
| 화살표·플로우 | 무시 | "A → B → C" 식 순서 표현 |
| 이미지 첨부 | 필수 | **보조용** (없어도 텍스트만으로 의미 완결) |

**핵심 원칙**: 마크다운만 읽어도 슬라이드의 학습 내용을 이해할 수 있어야 합니다. 이미지는 시각적 보조일 뿐.

용도: RAG·파인튜닝 데이터·검색 인덱스·재요약 등 **데이터 재처리**.

## 1. 처리 구조 — 2-pass

이 도구는 **2패스 처리**를 사용합니다. 1패스에서 강의 전체 맥락을 뽑고, 2패스에서 그 맥락을 주입한 채 페이지마다 상세 분석합니다.

```
[1패스] 강의 맥락 추출 (LLM 1회)
   입력: 모든 페이지의 plain text + 모든 페이지 썸네일을 합친 모자이크 1장
   출력: LectureContext (주제 요약 + 전체 제목 목록 + 핵심 용어)
              ↓
[2패스] 페이지별 상세 분석 (LLM × N회, N = 페이지 수)
   입력: 페이지 이미지 + 페이지 텍스트 + LectureContext (시스템 프롬프트에 주입)
   출력: PageAnalysis × N
```

### 왜 2-pass인가?

블록 코드(p.24-25)·복잡 다이어그램·도메인 특수 페이지를 LLM이 정확하게 "이 강의 맥락에서 무슨 의미인지" 파악하려면 강의 전체 흐름을 알아야 합니다. 1패스만으로는 LLM이 페이지를 고립된 이미지로 보기 때문에 환각 위험이 큽니다.

### 왜 strict인가?

1패스 실패 시 graceful 폴백(맥락 없이 2패스 진행)을 하면 결과 품질이 비결정적이 됩니다. 같은 PDF를 두 번 돌렸을 때 한 번은 맥락 있고 한 번은 없으면 디버깅이 어렵습니다. strict로 가서 항상 일관된 품질을 보장합니다. 대신 1패스 자체의 안정성에 신경 씁니다(재시도 + 입력 크기 제한).

### 모델 / 공통

이 도구는 **5개의 LLM 모델**을 지원하며 사용자가 작업마다 선택합니다. 1패스와 2패스는 항상 같은 모델을 사용합니다(단순화).

| 모델 ID (내부) | 실제 모델명 | 제공자 | 상태 |
|---|---|---|---|
| `claude-haiku-4-5` | Claude Haiku 4.5 | Anthropic | GA |
| `gemini-2-5-flash` | Gemini 2.5 Flash | Google | GA |
| `gemini-3-flash` | Gemini 3 Flash | Google | GA |
| `gpt-5-mini` | GPT-5 mini | OpenAI | GA |
| `gpt-5.4-mini` | GPT-5.4 mini | OpenAI | GA |

모든 모델은 같은 1패스/2패스 시스템 프롬프트를 사용합니다 — 모델별 분기 없음. 차이는 SDK 호출 방식과 JSON 강제 방식뿐이며 어댑터(§1.6)가 흡수합니다.

### 모델별 호출 차이 (어댑터 흡수 대상)

| 항목 | Claude Haiku 4.5 | Gemini 2.5/3 Flash | GPT-5 / 5.4 mini |
|---|---|---|---|
| SDK | `anthropic` | `google-genai` | `openai` |
| JSON 강제 | Tool Use (`tools` + `tool_choice`) | `responseSchema` + `responseMimeType: application/json` | Strict JSON (`response_format=json_schema`, `strict=true`) |
| temperature 권장 | 0.0 | 2.5: 0.0 / 3: **1.0** (낮추면 looping) | 0.0 |
| thinking 제어 | 없음 | 3만 `thinking_level: minimal` | 없음 |
| 이미지 입력 | base64 + media_type | inline_data (base64) | base64 data URL |
| 컨텍스트 윈도 | 200K | 1M | 400K (5.x mini) |
| max_tokens | 64,000 | 65,536 | 128,000 |
| 한국어 OCR | 우수 | 2.5 양호 / 3 우수 | 양호 |
| 시각자료 이해 | 양호 | 3는 최상 (블록 코드/복잡 다이어그램) | 5.4-mini 양호+ |

**재현성 트레이드오프**: Claude/Gemini 2.5/GPT는 temperature=0으로 결정적이지만, Gemini 3는 temperature=1.0이 권장이라 출력이 매번 약간 다릅니다. Gemini 3를 골든셋 평가에 사용할 때는 결과 분산을 인지해야 합니다.

### 모델별 비용 (28페이지 PDF 기준 추정)

가격은 2026.04 기준입니다. 단일 진실 원천(`MODEL_PRICES_USD_PER_M`,
`backend/app/pipeline/usage_log.py`)에서 가져옵니다 — 가격이 바뀌면 그 dict만
갱신하면 모든 곳에 반영됩니다.

| 모델 | 입력가 ($/1M) | 출력가 ($/1M) | 1패스 비용 | 2패스 합계 | PDF 1건 |
|---|---|---|---|---|---|
| Claude Haiku 4.5 | $1.00 | $5.00 | ~$0.02 | ~$0.18 | **~$0.20** |
| Gemini 2.5 Flash | $0.30 | $2.50 | ~$0.01 | ~$0.10 | **~$0.10** |
| Gemini 3 Flash | $0.50 | $3.00 | ~$0.02 | ~$0.18 | **~$0.20** |
| GPT-5 mini | $0.25 | $2.00 | ~$0.03 | ~$0.27 | **~$0.30** |
| GPT-5.4 mini | $0.75 | $4.50 | ~$0.04 | ~$0.41 | **~$0.45** |

Gemini 2.5 Flash가 가장 저렴, Gemini 3 Flash는 시각 이해 강세, GPT-5 mini는 비전·추론 안정성과 검증된 strict-JSON, GPT-5.4 mini는 GPT 시리즈 중 가장 빠르고 멀티모달 이해 향상. Claude Haiku는 한국어와 안정성에서 균형.

실제 비용은 작업이 끝날 때마다 `data/logs/usage.log`에 USD로 기록됩니다([DATA_MODEL.md §3](DATA_MODEL.md)).

## 1.6. LLM Provider 어댑터

### 1.6.1 인터페이스

```python
from typing import Protocol
from app.models import LectureContext, PageAnalysis

class LLMProvider(Protocol):
    """모델 어댑터 공통 인터페이스. 1패스/2패스 메서드만 노출."""

    name: str  # "claude-haiku-4-5" 등 모델 ID
    display_name: str  # "Claude Haiku 4.5" 등 UI 표기명
    is_preview: bool  # Preview 모델 여부 (UI 베타 라벨)

    def call_lecture_context(
        self,
        page_texts: list[str],
        mosaic_image_bytes: bytes,
        total_pages: int,
    ) -> LectureContext:
        """1패스. 실패 시 LLMError 발생."""
        ...

    def call_page_analysis(
        self,
        page_image_bytes: bytes,
        page_text: str,
        page_num: int,
        total_pages: int,
        context: LectureContext,
    ) -> PageAnalysis:
        """2패스. 페이지별 호출. 실패 시 LLMError 발생."""
        ...
```

### 1.6.2 모델별 구현 요약

```python
# pipeline/providers/claude.py
class ClaudeHaikuProvider:
    name = "claude-haiku-4-5"
    display_name = "Claude Haiku 4.5"
    is_preview = False

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model_id = "claude-haiku-4-5-20251001"  # 정확한 ID는 출시 시점 확인

    def call_lecture_context(self, page_texts, mosaic, total_pages):
        # Tool Use 방식
        response = self.client.messages.create(
            model=self.model_id,
            max_tokens=4096,
            temperature=0.0,
            tools=[TOOL_LECTURE_CONTEXT_ANTHROPIC],
            tool_choice={"type": "tool", "name": "report_lecture_context"},
            system=SYSTEM_PROMPT_PASS1,
            messages=[...],
        )
        tool_block = next(b for b in response.content if b.type == "tool_use")
        return LectureContext(**tool_block.input)


# pipeline/providers/gemini.py
class GeminiProvider:
    """Gemini 2.5와 3 둘 다 사용. 차이는 model_id, temperature, thinking_level."""

    def __init__(self, api_key: str, variant: Literal["2-5", "3"]):
        from google import genai
        self.client = genai.Client(api_key=api_key)
        if variant == "2-5":
            self.name = "gemini-2-5-flash"
            self.display_name = "Gemini 2.5 Flash"
            self.model_id = "gemini-2.5-flash"
            self.temperature = 0.0
            self.thinking_level = None
            self.is_preview = False
        else:  # "3"
            self.name = "gemini-3-flash"
            self.display_name = "Gemini 3 Flash"
            self.model_id = "gemini-3-flash-preview"
            self.temperature = 1.0  # 3.x 권장
            self.thinking_level = "minimal"  # 속도/비용 우선
            self.is_preview = True

    def call_lecture_context(self, page_texts, mosaic, total_pages):
        # responseSchema 방식
        config = {
            "response_mime_type": "application/json",
            "response_schema": LECTURE_CONTEXT_SCHEMA_GEMINI,
            "temperature": self.temperature,
            "system_instruction": SYSTEM_PROMPT_PASS1,
        }
        if self.thinking_level:
            config["thinking_config"] = {"thinking_level": self.thinking_level}

        response = self.client.models.generate_content(
            model=self.model_id,
            contents=[mosaic_part, text_part],
            config=config,
        )
        return LectureContext(**json.loads(response.text))


# pipeline/providers/openai.py
class OpenAIProvider:
    """GPT-5 mini와 GPT-5.4 mini 둘 다 사용. Strict JSON Schema 응답 형식."""

    def __init__(self, api_key: str, model_id: str = "gpt-5.4-mini"):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model_id = model_id  # "gpt-5-mini" 또는 "gpt-5.4-mini"
        self.name = model_id
        self.display_name = _OPENAI_DISPLAY[model_id]
        self.is_preview = False

    def call_page_analysis(self, page_image_bytes, page_text, page_num, total_pages, context):
        # response_format=json_schema, strict=true
        schema = _prepare_strict_schema(PageAnalysis)  # OpenAI Strict 호환 변환
        response = self.client.chat.completions.create(
            model=self.model_id,
            temperature=0.0,
            max_tokens=128_000,  # 벤더 max
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "page_analysis",
                    "strict": True,
                    "schema": schema,
                },
            },
            messages=[
                {"role": "system", "content": build_system_prompt(context)},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": _to_data_url(page_image_bytes)}},
                    {"type": "text", "text": _build_user_text(page_num, total_pages, page_text)},
                ]},
            ],
        )
        return PageAnalysis(**json.loads(response.choices[0].message.content))
```

### 1.6.3 스키마 변환 (Anthropic Tool ↔ Gemini responseSchema ↔ OpenAI Strict)

같은 Pydantic 모델을 세 형식으로 변환하는 헬퍼:

```python
def pydantic_to_anthropic_tool(model: type[BaseModel], tool_name: str, description: str) -> dict:
    """Pydantic → Anthropic Tool input_schema (JSON Schema)"""
    return {
        "name": tool_name,
        "description": description,
        "input_schema": model.model_json_schema(),
    }

def pydantic_to_gemini_schema(model: type[BaseModel]) -> dict:
    """Pydantic → Gemini responseSchema (subset of OpenAPI Schema)"""
    schema = model.model_json_schema()
    # Gemini는 anyOf/oneOf 일부만 지원. 후처리 필요.
    return _normalize_for_gemini(schema)

def _prepare_strict_schema(model_cls: type[BaseModel]) -> dict:
    """Pydantic → OpenAI Strict JSON Schema.

    Strict 모드 요구사항:
    - 모든 object의 additionalProperties=false
    - 모든 필드가 required에 포함 (Optional은 type 리스트로 nullable 표현)
    - $ref 인라인 (참조 해소)
    - default/format 등 일부 키워드 제거
    - anyOf [T, null] → type: [T, "null"]로 평탄화
    """
    schema = model_cls.model_json_schema()
    return _convert_to_openai_strict(schema)
```

**주의**:
- Gemini `responseSchema`는 OpenAPI 3.0 Schema의 **부분집합**만 지원. `anyOf`, `oneOf`, `additionalProperties`가 안 먹힐 수 있어 nullable 필드는 `nullable: true`로 변환.
- OpenAI Strict는 더 엄격해 모든 object에 `additionalProperties: false`와 모든 필드 required를 강제. nullable은 `type: ["string", "null"]`처럼 type 리스트로 표현. 자세한 건 [OpenAI Structured Outputs 문서](https://platform.openai.com/docs/guides/structured-outputs) 및 `backend/tests/test_openai_schema.py` 참조.

### 1.6.4 팩토리

```python
# pipeline/providers/__init__.py
_OPENAI_MODEL_IDS = {"gpt-5-mini", "gpt-5.4-mini"}

def make_provider(model_id: str, settings: Settings) -> LLMProvider:
    """모델 ID와 설정으로 provider 인스턴스 생성. 키 미설정 시 ValueError."""
    if model_id == "claude-haiku-4-5":
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        return ClaudeHaikuProvider(settings.anthropic_api_key)
    elif model_id == "gemini-2-5-flash":
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
        return GeminiProvider(settings.gemini_api_key, variant="2-5")
    elif model_id == "gemini-3-flash":
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
        return GeminiProvider(settings.gemini_api_key, variant="3")
    elif model_id in _OPENAI_MODEL_IDS:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")
        return OpenAIProvider(settings.openai_api_key, model_id=model_id)
    else:
        raise ValueError(f"알 수 없는 모델: {model_id}")


def list_available_providers(settings: Settings) -> list[ProviderInfo]:
    """현재 사용 가능한 모델 목록 (UI 드롭다운용). 키 없으면 비활성."""
    available = []
    for model_id in ALL_MODEL_IDS:
        info = MODEL_REGISTRY[model_id]
        info.enabled = _has_api_key(model_id, settings)
        available.append(info)
    return available
```

### 1.6.5 에러 처리 통일

각 SDK가 다른 예외를 던지므로 공통 에러로 래핑:

```python
class LLMError(Exception):
    """모든 provider 에러의 공통 부모."""
    pass

class LLMRateLimitError(LLMError): pass
class LLMAuthError(LLMError): pass
class LLMSchemaValidationError(LLMError): pass  # JSON 검증 실패
class LLMTransientError(LLMError): pass         # 재시도 가능

# provider 안에서
try:
    response = self.client.messages.create(...)
except anthropic.RateLimitError as e:
    raise LLMRateLimitError(str(e)) from e
except anthropic.AuthenticationError as e:
    raise LLMAuthError(str(e)) from e
# Gemini도 동일 패턴
```

이렇게 하면 runner.py는 provider가 무엇이든 같은 예외 처리 코드로 동작.

## 1.5. 1패스 — 강의 맥락 추출

### 1.5.1 입력 구성

**(a) 모든 페이지의 plain text** (pdfplumber): 페이지별 구분자로 합침

```
=== Page 1 ===
{page 1 text}

=== Page 2 ===
{page 2 text}
...
```

**(b) 페이지 썸네일 모자이크** (PIL): 모든 페이지를 그리드로 합친 1장의 이미지

- 각 페이지를 100 DPI로 렌더링 (4000x2250 → 약 1000x563)
- 한 변에 N장씩 격자로 배치 (28페이지면 6×5 그리드, 마지막 줄 일부 빔)
- 페이지마다 좌상단에 페이지 번호 라벨 추가
- 최종 이미지 크기는 6000~8000px 너비 정도 (Vision API 권장 한도 내)
- 큰 PDF(50페이지+)는 1패스에서 페이지 일부만 사용 (예: 짝수 페이지만, 또는 균등 샘플 25장)

```python
def build_thumbnail_mosaic(page_pngs: list[Path], cols: int = 6) -> Path:
    """모든 페이지를 그리드 모자이크로 합침. 각 셀에 페이지 번호 표시."""
    thumbs = [Image.open(p).resize((1000, 563)) for p in page_pngs]
    rows = math.ceil(len(thumbs) / cols)
    canvas = Image.new("RGB", (cols * 1000, rows * 563), "white")
    for i, thumb in enumerate(thumbs):
        x, y = (i % cols) * 1000, (i // cols) * 563
        canvas.paste(thumb, (x, y))
        # 페이지 번호 라벨 추가
        draw_label(canvas, x + 20, y + 20, f"p.{i+1}")
    return canvas
```

**입력 크기 제한**:
- PDF 페이지 수 > 50 → 균등 샘플 25장만 모자이크에 포함 (텍스트는 전부)
- 모자이크 이미지 너비가 8000px 초과하면 cols 늘려서 재구성

### 1.5.2 1패스 출력 스키마

```typescript
interface LectureContext {
  // 강의 전체 제목 (예: "데이터 분석 인공지능 앱 제작하기")
  title: string;

  // 강의 한 단락 요약 (3~5문장, 도메인·대상·다루는 도구 포함)
  topic_summary: string;

  // 페이지별 한 줄 요약
  slide_outline: Array<{
    page: number;
    title: string;
    one_line: string;  // 이 페이지의 핵심을 한 줄로
  }>;

  // 강의 전체에서 반복되는 핵심 용어 (RAG 인덱스에 유용)
  // 영어/약어는 원문 표기 유지
  key_terms: string[];

  // 도메인 단서 (대상 학년, 사용 도구, 제작물 등)
  // 예: "초·중·고 학생 대상 AI 교육, 블록 코딩 IDE 사용, PAPS 데이터로 비만도 분석 앱 제작"
  domain_hints: string;
}
```

### 1.5.3 1패스 시스템 프롬프트

```
당신은 한국어 강의 슬라이드 PDF의 전체 맥락을 추출하는 분석 도구입니다.

[입력]
1. 모든 페이지의 plain text를 페이지 구분자와 함께 이어붙인 텍스트
2. 모든 페이지의 썸네일을 격자로 합친 모자이크 이미지 (각 셀에 p.N 라벨)

[목적]
이 출력은 2패스 처리에서 페이지별 상세 분석에 맥락으로 주입됩니다. 따라서:
- 강의의 주제와 흐름을 파악할 수 있어야 함
- 페이지별 한 줄 요약은 2패스가 "이 페이지의 위치"를 알게 함
- 핵심 용어는 단어 표기 일관성을 위해 (PAPS, BMI, Tabular 등)

[금지]
- 추측·창작 금지: 슬라이드에 보이지 않는 내용 추가 X
- 학습 콘텐츠 자체를 자세히 풀어쓰지 마세요(그건 2패스의 일). 여기는 "맥락"만.
- 페이지별 한 줄 요약은 한 문장 이내(20자~40자).

[응답]
report_lecture_context 도구를 호출하여 결과를 반환하세요.
```

### 1.5.4 1패스 사용자 메시지

```python
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "<thumbnail mosaic base64>"
                }
            },
            {
                "type": "text",
                "text": (
                    "[입력 1] 페이지별 plain text:\n"
                    "---\n"
                    f"{joined_page_texts}\n"
                    "---\n\n"
                    "[입력 2] 첨부된 모자이크는 모든 페이지의 썸네일입니다. "
                    "각 셀의 p.N 라벨을 보고 페이지를 식별하세요.\n\n"
                    f"이 PDF는 총 {total_pages}페이지입니다.\n"
                    "report_lecture_context 도구를 호출해 결과를 반환하세요."
                )
            }
        ]
    }
]
```

### 1.5.5 1패스 출력 예시 (딥코 KDC 18회차)

```json
{
  "title": "데이터 분석 인공지능 앱 제작하기 (18회차)",
  "topic_summary": "초·중·고 학생 대상 AI 교육 과정 중 데이터 분석 모델을 활용한 앱 제작 차시이다. 공공데이터(PAPS, 학생건강체력평가)를 사용해 비만도를 예측하는 회귀 모델을 만들고, 이를 블록 코딩 기반 앱(AI 모델러)에서 호출하는 학습용 앱을 제작한다. 텍스트·다이어그램·표·블록 코드 캡처가 혼합된 슬라이드 구성.",
  "slide_outline": [
    { "page": 1, "title": "표지", "one_line": "강의 표지" },
    { "page": 5, "title": "데이터 분석 모델 개념 복습하기", "one_line": "섹션 구분 슬라이드" },
    { "page": 6, "title": "데이터 분석 모델이란?", "one_line": "모델의 역할과 머신러닝 작동원리 비교" },
    { "page": 7, "title": "데이터 분석 모델은 어떻게 만들어질까?", "one_line": "모델 생성 5단계 + 독립/종속변수 정의 + 예시 표" },
    { "page": 12, "title": "우리가 활용할 공공데이터 미리보기", "one_line": "PAPS 평가 항목 5종 소개" },
    { "page": 14, "title": "PAPS와 비만도 분석 앱 설계 하기", "one_line": "데이터 분석 모델과 AI 앱의 관계 도식" },
    { "page": 18, "title": "데이터 분석 모델 만들기", "one_line": "AI 모델러에서 TABULAR 회귀 모델 학습 화면" },
    { "page": 23, "title": "1번 화면 – 정답 코드 (1)", "one_line": "앱 화면 디자인: 레이어 구성 + AI 모델 연결" },
    { "page": 24, "title": "2번 화면 – 정답 코드 (2)", "one_line": "블록 코드: 라디오 버튼/예측 버튼 처리 + grade==1 분기" },
    { "page": 25, "title": "2번 화면 – 정답 코드 (3)", "one_line": "블록 코드: grade==2,3 분기 + BMI 결과 표시" }
  ],
  "key_terms": [
    "PAPS", "BMI", "Tabular", "AI 모델러", "DNN", "회귀", "독립변수", "종속변수",
    "심폐지구력", "유연성", "근력·근지구력", "순발력", "비만도",
    "고도비만", "경도비만", "과체중", "정상", "마름"
  ],
  "domain_hints": "초·중·고 학생 대상 AI 교육 / 블록 코딩 기반 IDE(AI 모델러) 사용 / 교육부 PAPS 공공데이터 활용 / 회귀 모델로 BMI 예측"
}
```

### 1.5.6 1패스 Tool 정의

```python
TOOL_LECTURE_CONTEXT = {
    "name": "report_lecture_context",
    "description": "Report the lecture-wide context extracted from all pages.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "topic_summary": {"type": "string"},
            "slide_outline": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "page": {"type": "integer", "minimum": 1},
                        "title": {"type": "string"},
                        "one_line": {"type": "string"}
                    },
                    "required": ["page", "title", "one_line"]
                }
            },
            "key_terms": {
                "type": "array",
                "items": {"type": "string"}
            },
            "domain_hints": {"type": "string"}
        },
        "required": ["title", "topic_summary", "slide_outline", "key_terms", "domain_hints"]
    }
}
```

### 1.5.7 1패스 안정성 (strict 모드 대응)

strict로 가기 때문에 1패스 실패가 곧 작업 실패. 다음으로 안정성 확보:

| 위험 | 대응 |
|---|---|
| LLM 응답 JSON 검증 실패 | 즉시 1회 재시도, 그래도 실패면 작업 실패 (`error.code = LLM_API_ERROR`) |
| API 일시 장애 | 재시도(지수 백오프, 최대 3회) |
| 모자이크 이미지가 너무 큼 | 사전에 cols/dpi 조정해서 8000px 이하로 |
| 텍스트 너무 김 (큰 PDF) | 페이지당 plain text 최대 1000자로 자름 |
| 페이지 50장 초과 | 균등 샘플 25장으로 모자이크 (텍스트는 전부) |
| 컨텍스트 윈도 초과 | 입력 토큰 사전 추정 → 한도 초과 시 텍스트 더 잘라내기 |

### 1.5.8 1패스 비용 추정

- 모자이크 이미지 (6000x2800 정도): ~3,500 토큰
- 모든 페이지 텍스트 (28페이지 × 평균 300자): ~7,000 토큰
- 시스템 프롬프트: ~600 토큰
- 응답 (slide_outline 28개 + 용어 + 요약): ~2,500 토큰

1패스 1회당 입력 ~11,000 토큰 + 출력 2,500 토큰 → **약 $0.05~$0.08**.

## 2. 2패스 — 페이지별 상세 분석

### 2.1 입력 구성

페이지 1개당 1번의 LLM 호출. 입력은:

1. **시스템 프롬프트** (§3): 작성 규칙 + **1패스에서 받은 LectureContext가 주입됨**
2. **사용자 메시지**:
   - 해당 페이지 이미지 (150 DPI PNG, base64)
   - 해당 페이지의 plain text (pdfplumber 추출)
   - 페이지 번호와 전체 페이지 수

**왜 페이지 텍스트도 함께 넣는가?**
- LLM Vision이 한국어 OCR을 완벽히 하지 못할 수 있음 (특히 작은 글씨·로고)
- pdfplumber 텍스트는 "정답 단어 후보" 역할 — LLM이 시각자료 의미를 풀어쓸 때 단어 표기를 텍스트와 일치시키도록 유도
- 텍스트만으로는 다이어그램 의미를 모르므로 이미지가 주(主), 텍스트가 보(補)

### 2.2 출력 JSON 스키마

```typescript
interface PageAnalysis {
  // 페이지 분류
  classification:
    | "content"           // 본문 슬라이드 — 마크다운 + (선택)이미지
    | "section_divider"   // 큰 글씨 섹션 구분 — 제목만
    | "cover"             // 표지/종료 — 마크다운에 안 들어감
    | "decorative_only";  // 안내문만 있는 장식 페이지 — 한 줄 안내만

  // 슬라이드 제목 (페이지 좌상단의 슬라이드 제목)
  title: string;

  // ⭐ 종합 재처리된 마크다운 본문
  // - 텍스트 + 시각자료 의미를 통합한 자급자족 마크다운
  // - 자세한 작성 규칙은 §3 시스템 프롬프트 참조
  markdown_body: string;

  // 보조 참조 이미지의 영역 (정규화 좌표 0~1000)
  // - "이 페이지의 시각자료가 추가 참조 가치가 있는가?" 판단
  // - 다이어그램/표가 텍스트 설명만으로 충분히 전달되면 null
  // - 시각적으로 봐야 의미가 명확한 경우(앱 화면, 코드 캡처, 복잡한 플로우차트)에만 첨부
  // - classification != "content"이면 항상 null
  image_region: BBox | null;

  // 첨부 이미지의 alt 텍스트
  image_caption: string | null;

  // 분류·작성 사유 (디버깅/로깅용)
  reasoning: string;
}

interface BBox {
  // 페이지 좌상단 = (0, 0), 우하단 = (1000, 1000)
  x_min: number;  // 0~1000
  y_min: number;
  x_max: number;
  y_max: number;
}
```

### 예시 1 — 다이어그램 페이지 (p.7, 모델 생성 프로세스)

원본: 좌측에 "데이터 수집 → 전처리 → 디자인 → 훈련/평가 → 테스트" 5단계 플로우, 우측에 "독립변수/종속변수" 박스 + 미세먼지 예시 표

```json
{
  "classification": "content",
  "title": "데이터 분석 모델은 어떻게 만들어질까?",
  "markdown_body": "데이터 분석 모델은 다음 5단계를 거쳐 만들어집니다.\n\n1. **데이터 수집** — 모델이 학습할 기반 정보를 모으는 단계\n2. **데이터 전처리** — 수집한 데이터를 학습에 적합하도록 정제하는 과정\n3. **모델 디자인** — 모델 구조를 설계하고 하이퍼파라미터를 설정하는 단계\n4. **훈련 및 성능 평가** — 학습 데이터로 모델을 훈련시키고 성능을 점검·최적화\n5. **모델 테스트** — 훈련에 사용되지 않은 데이터로 최종 성능 확인\n\n## 핵심 단어\n\n- **독립 변수**: 결과에 영향을 주는 원인 (예: 월, 요일, 시간)\n- **종속 변수**: 그에 따라 바뀌는 결과 (예: 미세먼지 농도)\n\n## 예시: 우리 교실의 요일과 시간에 따른 미세먼지 농도 측정 데이터\n\n| 월 | 요일 | 시간 | 미세먼지 농도 |\n|---|---|---|---|\n| 4 | 0 | 2 | 35 |\n| 6 | 1 | 3 | 42 |\n| 3 | 2 | 5 | 91 |\n| 8 | 3 | 4 | 28 |\n\n이 데이터는 CSV 형태로 제공됩니다.",
  "image_region": {
    "x_min": 60, "y_min": 160, "x_max": 970, "y_max": 950
  },
  "image_caption": "모델 생성 5단계 프로세스와 독립/종속 변수 예시",
  "reasoning": "본문 슬라이드. 5단계 플로우와 변수 정의·예시 표를 모두 텍스트로 풀어씀. 시각적 흐름이 직관적이라 보조 이미지도 함께 첨부."
}
```

### 예시 2 — 비교 박스 페이지 (p.6, 데이터 분석 모델이란)

원본: "데이터 분석 모델의 역할" 박스와 "머신러닝의 작동원리" 박스가 좌우로 배치

```json
{
  "classification": "content",
  "title": "데이터 분석 모델이란?",
  "markdown_body": "데이터 분석 모델은 다양한 수치 데이터를 학습해 규칙을 찾고 다음 결과를 예측하는 AI 모델입니다.\n\n## 데이터 분석 모델의 역할\n\n- 표 형태를 기반으로, 데이터 사이의 규칙을 학습해 새로운 입력이 들어왔을 때 결과를 예측함\n- 정형/비정형 데이터에서 숨겨진 패턴과 추세를 찾아, 미래를 예측하거나 더 나은 의사결정에 활용함\n\n## 머신러닝의 작동원리\n\n- 데이터를 기반으로 학습하여 패턴을 인지하고, 새로운 데이터에 대해 예측이나 분류를 수행하는 인공지능 기술\n- 대표적으로 '지도학습'을 사용\n  - **분류(classification)**: 미리 정해진 범주로 나누기\n  - **회귀(regression)**: 연속적인 값을 예측하기",
  "image_region": null,
  "image_caption": null,
  "reasoning": "본문 슬라이드. 두 박스의 내용이 단순 텍스트로 충분히 전달되므로 이미지 첨부 생략."
}
```

**주목**: 비교 박스는 텍스트만으로 충분 → `image_region: null`. 마크다운에 시각자료의 모든 내용이 다 들어가 있어요.

### 예시 3 — 화면 캡처 페이지 (p.18, AI 모델러 화면)

원본: TABULAR AI 모델 카드 + 모델러의 학습/테스트 UI 스크린샷

```json
{
  "classification": "content",
  "title": "데이터 분석 모델 만들기",
  "markdown_body": "AI 모델러에서 데이터 분석 모델을 생성합니다.\n\n## 작업 흐름\n\nPAPS 데이터(CSV 파일)를 불러와 **독립변수**와 **종속변수**를 정의하고, 전처리와 훈련 과정을 거쳐 모델을 생성한 뒤 테스트로 성능을 검증합니다.\n\n## 모델 정보 (예시)\n\n- 모델 유형: TABULAR (회귀)\n- 알고리즘: DNN\n- 에포크: 70 / 학습률: 0.001\n- 모델 정확도: 0 / 모델 오차(MSE): 0.0779 / Loss: 0.0142\n\n*이미지는 AI 모델러의 실제 학습/테스트 화면 — 데이터 입력란과 분석 결과 표시 영역 참조.*",
  "image_region": {
    "x_min": 30, "y_min": 200, "x_max": 970, "y_max": 940
  },
  "image_caption": "AI 모델러의 모델 카드와 학습/테스트 화면",
  "reasoning": "복잡한 UI 캡처라 텍스트 설명만으로는 인터페이스를 떠올리기 어려움. 핵심 정보(파라미터·성능)는 텍스트로 옮기고 이미지를 보조로 첨부."
}
```

**주목**: 표 안의 숫자(에포크 70, MSE 0.0779 등)도 텍스트로 옮겨 적음. 이미지 없어도 학습 가능.

### 예시 4 — 장식만 있는 페이지 (p.19, 실습 영상 안내)

```json
{
  "classification": "decorative_only",
  "title": "실습 영상 확인",
  "markdown_body": "영상을 보고 잘 만들었는지 확인합니다.",
  "image_region": null,
  "image_caption": null,
  "reasoning": "영상 시청 안내 페이지. 일러스트는 학습 콘텐츠가 아닌 장식. 본문도 한 줄 안내문뿐."
}
```

### 예시 5 — 표지 (p.1)

```json
{
  "classification": "cover",
  "title": "",
  "markdown_body": "",
  "image_region": null,
  "image_caption": null,
  "reasoning": "표지 페이지."
}
```

---

## 3. 2패스 시스템 프롬프트

이 프롬프트는 **고정 부분 + 1패스 결과로 채워지는 동적 부분**으로 구성됩니다.

### 3.1 프롬프트 조립 방법

```python
SYSTEM_PROMPT_TEMPLATE = """\
당신은 한국어 강의 슬라이드 PDF에서 텍스트와 시각자료를 종합하여 자급자족 마크다운으로 재구성하는 전문 분석 도구입니다.

[이 강의의 맥락 — 1패스에서 추출됨]
강의 제목: {title}

강의 요약:
{topic_summary}

도메인 단서: {domain_hints}

전체 슬라이드 흐름:
{slide_outline_formatted}

핵심 용어 (단어 표기 일치 기준):
{key_terms_formatted}

[맥락 활용 규칙]
- 위 맥락은 단어 표기 일관성과 도메인 인지에만 사용하세요.
- 슬라이드에 보이지 않는 내용을 맥락으로부터 추측해서 추가하지 마세요(환각 방지).
- 핵심 용어는 위 표기를 그대로 사용 (예: PAPS, BMI, Tabular).
- "이 슬라이드는 강의 흐름에서 N번째이므로..." 같은 메타 표현 금지.

[이 작업의 목적]
출력 마크다운은 RAG/파인튜닝/검색 인덱스 등의 데이터 재처리에 사용됩니다. 따라서:
- 텍스트만 읽어도 슬라이드의 학습 내용이 완결되어야 합니다.
- 다이어그램·박스·표·화살표 등 시각자료의 의미를 텍스트로 풀어쓰세요.
- 이미지 첨부는 보조 참조용입니다(텍스트 설명을 이미지로 떼우려고 하지 마세요).

[입력]
1. 슬라이드 한 페이지의 이미지 (PNG)
   페이지 좌표는 좌상단=(0,0), 우하단=(1000,1000)으로 정규화하여 응답하세요.
2. 같은 페이지를 PDF 텍스트 추출기로 뽑아낸 plain text
   - 단어 표기를 일치시키는 데 활용하세요(특히 고유명사/약어).
   - 누락이나 순서 오류 가능. 시각적으로 보이는 내용이 우선입니다.

[당신이 해야 할 일]
1. 페이지를 4가지 종류로 분류
2. 본문 페이지면 텍스트와 시각자료를 종합한 마크다운을 작성
3. 시각자료가 텍스트 설명만으로 부족할 경우 보조 이미지 영역(bbox)을 결정

[페이지 분류 기준]

1. "content" — 본문 슬라이드:
   - 학습 내용이 텍스트, 다이어그램, 표, 코드, 화면 캡처 등으로 표현된 페이지
   - 단순 제목이 아니라 학습자가 읽고 이해해야 할 정보가 있음

2. "section_divider" — 섹션 구분 슬라이드:
   - 페이지 가운데에 큰 글씨로 섹션 제목만 있는 페이지
   - 예: "데이터 분석 모델 개념 복습하기", "공공데이터 알아보기", "학습 마무리"
   - 보조 아이콘/장식이 있을 수 있지만 학습 콘텐츠는 없음
"""

def build_system_prompt(ctx: LectureContext) -> str:
    outline = "\n".join(
        f"- p.{s.page} {s.title}: {s.one_line}"
        for s in ctx.slide_outline
    )
    terms = ", ".join(ctx.key_terms)
    return SYSTEM_PROMPT_TEMPLATE.format(
        title=ctx.title,
        topic_summary=ctx.topic_summary,
        domain_hints=ctx.domain_hints,
        slide_outline_formatted=outline,
        key_terms_formatted=terms,
    ) + REST_OF_PROMPT  # 나머지 분류 기준·작성 규칙·금지사항 등
```

### 3.2 시스템 프롬프트 — 고정 부분 (분류 기준 이후)

위 동적 부분 뒤에 다음 고정 부분이 이어집니다:

```

3. "cover" — 표지/종료 페이지:
   - 강의 시작/종료 페이지, 회사 로고, 강의 제목만 크게 있는 페이지
   - "다음 시간에 만나요" 등 인사 페이지

4. "decorative_only" — 장식뿐인 페이지:
   - 한두 줄 안내문 + 장식 일러스트 (학습 다이어그램이 아님)
   - 예: "실습 영상 확인" + 일러스트 캐릭터

[마크다운 작성 규칙 — 이 도구의 핵심]

▣ 시각자료 종합 원칙
- 다이어그램의 박스/화살표 구조 → 리스트, 순서 목록, "A → B → C" 식 표현
- 비교 박스 → 헤딩(##)으로 항목 구분 후 리스트로 풀어씀
- 표 → 마크다운 표로 재구성 (행/열 구조 보존)
- 정의 박스("독립변수: 원인") → "**독립변수**: 결과에 영향을 주는 원인" 식
- 플로우차트 → 번호 매긴 순서 목록으로 변환
- 차트/그래프 → 데이터 트렌드를 한 문장으로 요약 (구체 숫자가 보이면 표로)

▣ 적정한 설명 깊이
- 시각자료에 보이는 모든 텍스트와 라벨은 마크다운에 등장해야 함
- 단, 추측·창작 금지: 슬라이드에 없는 부연 설명을 추가하지 마세요
- "이 다이어그램이 뜻하는 바는..." 같은 메타 해설 금지
- 슬라이드의 어조·강조를 보존하되 장식적 표현(대박! 신기하죠?)은 제거

▣ 형식 규칙
- 슬라이드 제목은 markdown_body에 다시 포함하지 않음 (title 필드와 중복 방지)
- 본문 안 소제목은 ## 또는 ### 사용 (슬라이드 제목보다 한 단계 작게)
- 불릿 기호(•, ◎, ✓ 등)는 마크다운 -로 변환
- 강조 색상이 있는 단어는 **굵게**로
- 영어/약어는 원문 표기 유지 (Tabular, BMI, PAPS, CSV, API 등)

▣ 코드/화면 캡처 처리
- 코드가 페이지에 보이면 ```언어 코드블록으로 옮기되, OCR 자신 없으면 *"이미지의 코드 참조"* 한 줄로 대체
- UI 스크린샷의 라벨/버튼 텍스트는 마크다운에 명시
- 복잡한 화면은 핵심 요소만 텍스트로 추리고 보조 이미지 첨부

▣ 분류별 본문
- "content": 위 규칙대로 충실히 작성
- "section_divider": 빈 문자열 또는 매우 짧은 한 줄
- "cover": 빈 문자열
- "decorative_only": 안내문 한 줄만 (예: "영상을 보고 잘 만들었는지 확인합니다.")

[보조 이미지(image_region) 결정 규칙]

bbox를 첨부할 가치가 있는가?
- 텍스트로 설명했지만 시각적 배치/관계를 보면 더 명확한 경우 → 첨부
- 화면 캡처/코드 캡처처럼 시각적 정보가 본질인 경우 → 첨부
- 단순 비교 박스 두 개라 텍스트로 충분한 경우 → null
- 장식 일러스트만 있는 경우 → null

bbox 좌표 결정:
1) 페이지 상단의 "타이틀 영역"(슬라이드 제목 + 회색 띠)은 제외
2) 페이지 하단의 "푸터"(로고·페이지번호) 제외
3) 본문 영역 안에서 시각자료(다이어그램·표·박스·캡처)와 그것의 라벨이 모두 들어가도록 약간 여유있게
4) 텍스트 본문(슬라이드 부제목)은 가능하면 제외하되, 시각자료와 인접해서 떼기 어려우면 함께 포함
5) 좌표는 0~1000 정규화

여러 시각자료가 흩어져 있으면 둘을 모두 포함하는 큰 bbox 한 개를 반환.

[금지사항]
- 추측/창작 금지: 슬라이드에 없는 내용 추가 X
- 의역으로 의미 변경 금지
- "이 슬라이드에서는...", "그림을 보면..." 같은 메타 표현 사용 금지
- 한국어로 된 영어/약어를 한국어로 임의 번역 금지

[응답]
report_page_analysis 도구를 호출하여 결과를 반환하세요.
```

---

## 4. 사용자 메시지 (Messages API)

```python
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "<base64-encoded page image>"
                }
            },
            {
                "type": "text",
                "text": (
                    "[참고용] 이 페이지에서 pdfplumber로 추출한 텍스트:\n"
                    "---\n"
                    f"{plain_text}\n"
                    "---\n\n"
                    f"이 페이지는 PDF의 {page_num}/{total_pages}번째 페이지입니다.\n"
                    "report_page_analysis 도구를 호출해 결과를 반환하세요."
                )
            }
        ]
    }
]
```

## 5. JSON 강제 전략 — 모델별 차이

JSON 출력 강제 방식이 모델마다 다릅니다. 어댑터(§1.6)가 이 차이를 흡수합니다.

### 5.1 공통 입력 스키마 (Pydantic)

```python
# 한 곳에서 정의, 모든 모델이 공유
class PageAnalysis(BaseModel):
    classification: Classification
    title: str
    markdown_body: str
    image_region: Optional[BBox] = None
    image_caption: Optional[str] = None
    reasoning: str
```

### 5.2 Claude — Tool Use

```python
TOOL_PAGE_ANALYSIS_ANTHROPIC = {
    "name": "report_page_analysis",
    "description": (
        "Report the analysis result of a single PDF slide page. "
        "Use this tool to return the classification, title, "
        "self-contained markdown body, and optional reference image region."
    ),
    "input_schema": PageAnalysis.model_json_schema(),
}

# Claude provider 내부
response = self.client.messages.create(
    model=self.model_id,
    max_tokens=4096,
    temperature=0.0,
    tools=[TOOL_PAGE_ANALYSIS_ANTHROPIC],
    tool_choice={"type": "tool", "name": "report_page_analysis"},
    system=system_prompt,
    messages=messages,
)
tool_block = next(b for b in response.content if b.type == "tool_use")
analysis = PageAnalysis(**tool_block.input)
```

### 5.3 Gemini — responseSchema

Gemini는 `tools` 대신 `responseSchema`로 JSON 강제. tool_use가 아닌 일반 응답을 JSON으로 받음:

```python
PAGE_ANALYSIS_SCHEMA_GEMINI = pydantic_to_gemini_schema(PageAnalysis)
# anyOf, additionalProperties 등 비호환 필드 제거됨

# Gemini provider 내부
config = {
    "response_mime_type": "application/json",
    "response_schema": PAGE_ANALYSIS_SCHEMA_GEMINI,
    "temperature": self.temperature,  # 2.5는 0.0, 3은 1.0
    "system_instruction": system_prompt,
}
if self.thinking_level:  # Gemini 3만
    config["thinking_config"] = {"thinking_level": self.thinking_level}

response = self.client.models.generate_content(
    model=self.model_id,
    contents=[image_part, text_part],
    config=config,
)
analysis = PageAnalysis(**json.loads(response.text))
```

### 5.4 OpenAI — Strict JSON Schema

GPT-5/5.4 mini는 `response_format`에 `json_schema`를 지정하고 `strict: true`로 스키마 준수를 강제합니다:

```python
# OpenAI provider 내부
schema = _prepare_strict_schema(PageAnalysis)
# → 모든 object에 additionalProperties=false, 모든 필드 required,
#   $ref 인라인, anyOf [T, null] → type: [T, "null"], default/format 제거

response = self.client.chat.completions.create(
    model=self.model_id,                      # gpt-5-mini / gpt-5.4-mini
    temperature=0.0,
    max_tokens=128_000,                       # 벤더 max (큰 페이지 안전)
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "page_analysis",
            "strict": True,
            "schema": schema,
        },
    },
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": user_text},
        ]},
    ],
)
analysis = PageAnalysis(**json.loads(response.choices[0].message.content))
```

스키마 변환(`_prepare_strict_schema`) 동작은 `backend/tests/test_openai_schema.py`에 단위 테스트로 고정돼 있습니다.

### 5.5 공통 후처리 — Pydantic 검증

어떤 모델이든 응답을 받으면 동일하게 Pydantic으로 재검증:

```python
try:
    analysis = PageAnalysis.model_validate(raw_dict)
except ValidationError as e:
    # 1회 재시도, 그래도 실패면 LLMSchemaValidationError
    raise LLMSchemaValidationError(str(e))
```

### 5.6 모델별 함정 (개발 시 주의)

**Claude**:
- `tool_choice`로 강제하지 않으면 가끔 자연어 응답을 함 → 항상 `{"type": "tool", "name": ...}` 명시
- `max_tokens`이 부족하면 tool_use 블록이 잘릴 수 있음 → 최소 4096

**Gemini 2.5/3 공통**:
- `responseSchema`는 OpenAPI Schema의 부분집합만 지원. `anyOf`, `oneOf`, `additionalProperties` 등은 변환 헬퍼에서 제거/평탄화 필요
- nullable 필드는 `{"nullable": true}`로 변환 (Pydantic의 `Optional[X]`)
- enum 필드는 `{"type": "string", "enum": [...]}` 그대로 OK

**Gemini 3 추가 함정**:
- `thinking_level: minimal`을 안 주면 reasoning 토큰을 많이 써서 응답이 느려지고 비싸짐
- temperature를 0.0으로 강제하면 looping 위험. 1.0 유지
- thought signatures를 multi-turn에서 다시 보내야 하지만, 우리는 single-turn이라 무시 가능

**OpenAI (GPT-5 / 5.4 mini)**:
- `response_format=json_schema`에 `strict: true`를 주려면 스키마가 엄격 호환이어야 함 (`_prepare_strict_schema` 변환 필수)
- `additionalProperties: false`를 빠뜨리면 400 에러 — Pydantic 변환에서 모든 object에 명시적으로 추가
- nullable은 `anyOf: [T, null]`이 아니라 `type: [T, "null"]` 리스트 형식 — `_convert_to_openai_strict`가 평탄화
- `max_tokens=128_000` 권장 (벤더 max). 작게 두면 큰 페이지 응답 잘림 + JSON 파싱 실패
- 토큰 사용량은 `usage.prompt_tokens` / `usage.completion_tokens`로 누적

## 6. Pydantic 검증

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional

Classification = Literal["content", "section_divider", "cover", "decorative_only"]

class BBox(BaseModel):
    x_min: float = Field(ge=0, le=1000)
    y_min: float = Field(ge=0, le=1000)
    x_max: float = Field(ge=0, le=1000)
    y_max: float = Field(ge=0, le=1000)

class PageAnalysis(BaseModel):
    classification: Classification
    title: str
    markdown_body: str
    image_region: Optional[BBox] = None
    image_caption: Optional[str] = None
    reasoning: str
```

검증 실패 시: 1회 재시도(같은 호출), 그래도 실패면 페이지를 `failed`로 마킹하고 다음 페이지로 진행.

## 7. bbox 좌표 변환

```python
def denormalize_bbox(bbox: BBox, image_width: int, image_height: int) -> tuple[int, int, int, int]:
    """0~1000 정규화 → PIL crop 형식 (left, top, right, bottom)"""
    return (
        int(bbox.x_min / 1000 * image_width),
        int(bbox.y_min / 1000 * image_height),
        int(bbox.x_max / 1000 * image_width),
        int(bbox.y_max / 1000 * image_height),
    )
```

## 8. 비용 추정

### 1패스 토큰 사용량 (전 모델 공통)
- 모자이크 이미지: ~3,500 토큰
- 모든 페이지 텍스트 합산: ~7,000 토큰
- 시스템 프롬프트: ~600 토큰
- 응답: ~2,500 토큰

### 2패스 토큰 사용량 (페이지당, 전 모델 공통)
- 페이지 이미지: ~1,100 토큰
- 시스템 프롬프트(맥락 포함): ~2,500 토큰
- 페이지 텍스트: ~200~500 토큰
- 응답: ~800~1,500 토큰

### 모델별 28페이지 PDF 비용 (대략, 2026.04 기준)

가격은 출시 시점 변동 가능. 실제 비용은 PDF 1건 처리 시 `data/logs/usage.log`에 USD로 기록 ([DATA_MODEL.md §3](DATA_MODEL.md)).

| 모델 | 1패스 | 2패스 합계 | **PDF 1건** |
|---|---|---|---|
| Claude Haiku 4.5 | ~$0.02 | ~$0.18 | **~$0.20** |
| Gemini 2.5 Flash | ~$0.01 | ~$0.10 | **~$0.10** |
| Gemini 3 Flash | ~$0.02 | ~$0.18 | **~$0.20** |
| GPT-5 mini | ~$0.03 | ~$0.27 | **~$0.30** |
| GPT-5.4 mini | ~$0.04 | ~$0.41 | **~$0.45** |

50페이지 PDF는 위의 ~1.5배. 100페이지면 ~3배. 모두 사내용으로 감당 가능한 수준.

### 비용 로깅

`logs/usage.log` JSONL 1줄/작업:

```json
{"ts": "...", "job_id": "550e...", "pdf": "강의자료.pdf",
 "model": "gpt-5.4-mini", "input_tokens": 169349, "output_tokens": 11412,
 "total_tokens": 180761, "pages": 28,
 "input_cost_usd": 0.127012, "output_cost_usd": 0.051354,
 "total_cost_usd": 0.178366, "ok": true}
```

CLI(`python -m app.cli ...`)는 작업 종료 시 stderr에 추정 총비용을 함께 출력합니다.

## 9. 프롬프트 개선 사이클

골든 데이터셋(딥코 KDC 18회차 14개 본문 페이지)으로 회귀:

```
1. 프롬프트 v1로 14페이지 처리
2. 페이지별 정답 마크다운(수동 작성)과 비교
3. 평가 항목:
   - 분류 정확도
   - 시각자료 정보 누락률 (다이어그램의 박스 텍스트가 마크다운에 다 있는가?)
   - 환각/창작 발생률 (슬라이드에 없는 내용이 들어갔는가?)
   - 형식 일관성 (헤딩 깊이, 리스트 마커)
4. 실패 케이스 분석 → 시스템 프롬프트 보강
5. v2로 다시 처리 → 비교
```

자세한 평가 방법은 [TESTING.md](TESTING.md) 참조.

## 10. 알려진 위험과 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| **1패스 실패** (strict 모드) | 전체 작업 실패 | 재시도 3회(지수 백오프), 입력 크기 사전 제한, 명확한 에러 메시지 |
| **맥락 의존 환각** (LLM이 맥락으로 슬라이드에 없는 내용 추가) | 데이터 오염 | 시스템 프롬프트 "맥락은 표기 일치·도메인 인지에만 사용, 콘텐츠 추가 금지" 강조 + 골든 셋에서 환각 검출 |
| **1패스가 슬라이드 흐름을 잘못 요약** | 2패스가 잘못된 맥락 받음 | slide_outline의 page 번호와 실제 페이지 일치 검증, 불일치 시 1패스 재시도 |
| LLM이 시각자료 정보를 누락 (박스 텍스트가 마크다운에 안 들어감) | 자급자족성 깨짐 | "모든 텍스트와 라벨 등장" 강조 + 평가 지표 모니터링 |
| LLM이 추측/창작으로 부연 설명 추가 | 데이터 오염 | "추측 금지", "메타 표현 금지" + 평가에서 환각 검출 |
| OCR 오류로 한국어 단어 변형 | 검색 인덱스 품질 저하 | 텍스트 입력 + key_terms 표기를 단어 기준으로 활용 |
| bbox에 헤더/푸터 포함 | 결과 이미지에 회사 로고 | "헤더/푸터 제외" + 후처리 상하단 5% trim 옵션 |
| 분류 오판 (decorative를 content로) | 장식 일러스트가 첨부됨 | 골든 셋 회귀 테스트 |
| 마크다운에 슬라이드 제목 중복 | content.md에 같은 제목 두 번 | 시스템 프롬프트 명시 + 패키저 후처리 검사 |
| 토큰 한도 초과 | 응답 잘림 | max_tokens 4096, 과도 긴 본문 검출 시 재시도 |
| 한국어가 아닌 슬라이드 | 분류 기준 모호 | v1은 한국어 슬라이드만 지원 |
| 같은 슬라이드를 두 번 호출하면 다른 결과 (Claude/Gemini 2.5) | 비결정성 | temperature=0 |
| **Gemini 3는 temperature=1.0이 권장** | 비결정성 (재현성 약함) | 골든셋 평가 시 분산 인지, 모델별로 별도 평가 베이스라인 |
| **모자이크 이미지가 컨텍스트 한도 초과** | 1패스 호출 실패 | 사전 토큰 추정 → 페이지 샘플링 또는 cols 조정 |
| **Gemini responseSchema가 일부 Pydantic 필드 미지원** (anyOf 등) | 어댑터 변환 실패 | `pydantic_to_gemini_schema` 헬퍼에서 평탄화 + 단위 테스트로 검증 |
| **Gemini 3 Preview 사양 변경** | API 호출 실패 / 동작 변화 | UI에 베타 라벨 + provider에 model_id 상수 분리해 빠르게 갱신 가능하게 |
| **사용자가 키 없는 모델 선택** | 작업 시작 시 에러 | UI에서 키 없는 모델 비활성, API 단에서도 친절한 에러 메시지 |
| **모델 간 OCR 정확도 편차** | 한국어 단어 변형 차이 | 골든셋 평가 결과를 README/UI에 모델별로 공개 → 사용자가 선택 시 참고 |
