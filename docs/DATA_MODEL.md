# DATA_MODEL — 내부 데이터 구조

이 도구는 영구 저장소(DB)를 쓰지 않습니다. 모든 데이터는:

- **InMemoryJobStore**: job 상태, 진행률 (프로세스 메모리, 재시작 시 휘발)
- **파일시스템**: PDF 입력, 결과 ZIP, 이미지, **사용량 로그(JSONL)**

## 1. Pydantic 모델

### 1.1 Job

```python
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"

class CurrentStep(str, Enum):
    VALIDATING = "validating"
    RASTERIZING = "rasterizing"
    EXTRACTING_TEXT = "extracting_text"
    EXTRACTING_CONTEXT = "extracting_context"  # 1패스
    ANALYZING_PAGE = "analyzing_page"          # 2패스
    CROPPING = "cropping"
    PACKAGING = "packaging"

class JobError(BaseModel):
    code: str
    message: str
    page: Optional[int] = None

class Job(BaseModel):
    job_id: str               # UUID v4
    status: JobStatus
    model_id: str             # "claude-haiku-4-5" 등 — 작업 생성 시 결정, 변경 불가
    pdf_filename: str         # 사용자가 업로드한 원본 파일명 (usage.log 기록용)
    total_pages: int = 0
    processed_pages: int = 0
    progress_pct: int = 0     # 0~100
    current_step: Optional[CurrentStep] = None
    current_page: Optional[int] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[JobError] = None
```

### 1.2 LectureContext (1패스 출력)

PDF 전체에서 한 번 추출되며, 2패스 시스템 프롬프트에 주입됩니다.

```python
class SlideOutlineEntry(BaseModel):
    page: int = Field(ge=1)
    title: str
    one_line: str

class LectureContext(BaseModel):
    title: str
    topic_summary: str
    slide_outline: list[SlideOutlineEntry]
    key_terms: list[str]
    domain_hints: str
```

검증 규칙:
- `slide_outline[*].page` 값이 1 ~ total_pages 범위 안에 있어야 함
- `slide_outline`의 page가 중복되면 안 됨
- `slide_outline` 길이가 total_pages를 초과하면 안 됨
  (총 페이지보다 적은 건 OK — LLM이 표지/구분 페이지를 빠뜨릴 수 있음)

위 검증이 실패하면 1패스 재시도(최대 3회). 모두 실패하면 strict 모드라 작업 실패.

### 1.3 PageAnalysis (2패스 출력)

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

Classification = Literal["content", "section_divider", "cover", "decorative_only"]

class BBox(BaseModel):
    x_min: float = Field(ge=0, le=1000)
    y_min: float = Field(ge=0, le=1000)
    x_max: float = Field(ge=0, le=1000)
    y_max: float = Field(ge=0, le=1000)

class PageAnalysis(BaseModel):
    page_num: int
    classification: Classification
    title: str
    markdown_body: str
    image_region: Optional[BBox] = None
    image_caption: Optional[str] = None
    reasoning: str
    # 처리 메타
    image_filename: Optional[str] = None  # 크롭 후 채워짐
    llm_call_failed: bool = False
```

### 1.4 PipelineResult

워커 처리가 끝난 후 패키저가 받는 입력.

```python
class PipelineResult(BaseModel):
    job_id: str
    pdf_filename: str             # 원본 파일명 (확장자 제외)
    model_id: str                 # 사용된 LLM 모델 (마크다운 헤더에 명시)
    context: LectureContext       # 1패스 결과 (마크다운 헤더에 사용)
    pages: list[PageAnalysis]     # 2패스 결과, 페이지 순서대로
    total_pages: int
```

## 2. InMemoryJobStore

작업 상태는 외부 의존성 없이 프로세스 메모리에 보관됩니다
(`backend/app/core/job_store.py`).

```python
class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, *, job_id, model_id, pdf_filename, total_pages) -> Job: ...
    def get(self, job_id: str) -> Job | None: ...
    def list(self) -> list[Job]: ...
    def delete(self, job_id: str) -> bool: ...

    def mark_started(self, job_id: str) -> None: ...
    def mark_done(self, job_id: str) -> None: ...
    def mark_failed(self, job_id: str, *, code, message, page=None) -> None: ...
    def update_progress(self, job_id: str, *, step, current_page=None,
                        processed_pages=None, progress_pct=None) -> None: ...
```

전역 싱글턴은 `app.core.job_store.get_job_store()`로 접근하며, 백그라운드 워커
(`api/worker.py`)와 API 핸들러(`api/jobs.py`)가 동일 인스턴스를 공유합니다.
모든 변경은 `threading.Lock`으로 직렬화됩니다.

### 2.1 라이프사이클

| 시점 | 호출 | 결과 상태 |
|---|---|---|
| `POST /jobs` 처리 직후 | `create(...)` | `queued`, `progress_pct=0` |
| 워커 진입 | `mark_started(job_id)` | `processing`, `started_at=now` |
| 페이지 처리 중 | `update_progress(...)` | `current_step`, `progress_pct` 갱신 |
| 정상 종료 | `mark_done(job_id)` | `done`, `progress_pct=100`, `finished_at=now` |
| 실패 | `mark_failed(job_id, code=..., message=...)` | `failed`, `error` 채워짐 |

**휘발성 주의**: 서버 재시작 시 `_jobs` dict이 비워지고 진행 중이던
`BackgroundTasks` 태스크도 함께 사라집니다. 결과 디렉토리(`outputs/{job_id}/`)는
디스크에 남지만 API로는 더 이상 조회되지 않습니다.

### 2.2 클라우드 이전 시

같은 메서드 시그니처로 Redis/Postgres 백엔드 구현체를 끼워 넣을 수 있도록
인터페이스가 분리돼 있습니다(`get_job_store()`만 교체).

## 3. 사용량 로그 (`logs/usage.log`)

`backend/app/pipeline/usage_log.py`가 **작업 1건당 1줄**의 JSONL을
`<DATA_DIR>/logs/usage.log`에 누적 기록합니다. 실패한 작업도 기록(`ok: false`).

### 3.1 레코드 스키마

```jsonc
{
  "ts": "2026-04-29T08:04:07.029979+00:00",  // UTC ISO-8601
  "job_id": "550e8400-...",                  // POST /jobs로 발급된 UUID (없는 경우 생략)
  "pdf": "강의자료.pdf",                      // 원본 업로드 파일명 (input.pdf 아님)
  "model": "gpt-5.4-mini",                   // 사용된 모델 ID
  "input_tokens": 169349,
  "output_tokens": 11412,
  "total_tokens": 180761,
  "pages": 28,
  "input_cost_usd": 0.127012,                // 모델 가격표에 있을 때만
  "output_cost_usd": 0.051354,
  "total_cost_usd": 0.178366,
  "ok": true,
  "error": "LLMSchemaValidationError: ..."   // ok=false일 때만
}
```

비용 필드는 `MODEL_PRICES_USD_PER_M`(같은 모듈)에 가격이 등록된 모델만 채워집니다.
가격이 없는 모델은 비용 3개 필드가 **생략**됩니다(0이 아님).

### 3.2 가격표 (USD per 1M tokens)

| 모델 | input | output |
|---|---|---|
| `claude-haiku-4-5` | 1.00 | 5.00 |
| `gemini-2-5-flash` | 0.30 | 2.50 |
| `gemini-3-flash` | 0.50 | 3.00 |
| `gpt-5-mini` | 0.25 | 2.00 |
| `gpt-5.4-mini` | 0.75 | 4.50 |

### 3.3 jq 집계 예시

```bash
# 모델별 누적 비용
jq -s 'group_by(.model) | map({model: .[0].model, total_usd: (map(.total_cost_usd // 0) | add)})' \
  data/logs/usage.log

# 비용 상위 5개 PDF
jq -s 'sort_by(-(.total_cost_usd // 0))[:5] | .[] | {pdf, model, total_cost_usd}' \
  data/logs/usage.log

# 실패한 작업 목록
jq 'select(.ok == false) | {ts, pdf, model, error}' data/logs/usage.log
```

**구버전과의 호환**: 비용 필드 도입 이전의 라인은 비용이 비어 있을 수 있어
집계 시 `// 0` (jq) 또는 `.fillna(0)` (pandas)로 채워서 처리합니다.

## 4. 파일시스템 레이아웃

```
<DATA_DIR>/
├── uploads/
│   └── {job_id}/
│       └── input.pdf                 # 원본 (수동 정리)
│
├── outputs/
│   └── {job_id}/
│       ├── pages/                    # 임시: 렌더링된 페이지 PNG들 (작업 직후 삭제)
│       │   ├── page-01.png
│       │   └── ...
│       ├── images/                   # 최종: 크롭된 시각자료
│       │   ├── 06_데이터분석모델.png
│       │   └── ...
│       ├── content.md                # 최종 마크다운
│       └── result.zip                # 다운로드 대상
│
└── logs/
    └── usage.log                     # JSONL 누적 (위 §3 참조)
```

처리 완료 후 `pages/` 폴더는 즉시 삭제 (임시 자료).
`outputs/{job_id}/` 와 `uploads/{job_id}/` 의 자동 정리는 v1에서는 미구현 —
운영자가 OS 작업 스케줄러로 직접 정리합니다 (INFRA.md §7 참고).

## 5. 이미지 파일명 규칙

```
{page_num:02d}_{slug}.png
```

- `page_num`: 2자리 0패딩 (예: `06`, `12`)
- `slug`: 슬라이드 제목에서 생성
  - 한글/영문/숫자만 남기고 나머지는 `_`로
  - 최대 30자
  - 예: `데이터 분석 모델이란?` → `데이터_분석_모델이란`

```python
import re

def slugify_korean(text: str, max_len: int = 30) -> str:
    # 한글, 영문, 숫자, 공백만 남김
    text = re.sub(r"[^\w가-힣\s]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:max_len]
```

## 6. 마크다운 출력 형식

`content.md` 구조 (종합 재처리 — 시각자료 의미가 텍스트에 통합됨, 1패스 맥락이 헤더에 포함됨):

```markdown
# 데이터 분석 인공지능 앱 제작하기 (18회차)

> 추출 일시: 2026-04-28
> 원본 PDF: deepco_kdc_18.pdf
> 원본 페이지 수: 28
> 분석 모델: Gemini 3 Flash (preview)

## 강의 요약

초·중·고 학생 대상 AI 교육 과정 중 데이터 분석 모델을 활용한 앱 제작 차시이다. 공공데이터(PAPS, 학생건강체력평가)를 사용해 비만도를 예측하는 회귀 모델을 만들고, 이를 블록 코딩 기반 앱(AI 모델러)에서 호출하는 학습용 앱을 제작한다. 텍스트·다이어그램·표·블록 코드 캡처가 혼합된 슬라이드 구성.

**도메인**: 초·중·고 학생 대상 AI 교육 / 블록 코딩 기반 IDE(AI 모델러) 사용 / 교육부 PAPS 공공데이터 활용 / 회귀 모델로 BMI 예측

**핵심 용어**: PAPS, BMI, Tabular, AI 모델러, DNN, 회귀, 독립변수, 종속변수, 심폐지구력, 유연성, 근력·근지구력, 순발력, 비만도, 고도비만, 경도비만, 과체중, 정상, 마름

---

## 슬라이드 6 — 데이터 분석 모델이란?

데이터 분석 모델은 다양한 수치 데이터를 학습해 규칙을 찾고 다음 결과를 예측하는 AI 모델입니다.

### 데이터 분석 모델의 역할

- 표 형태를 기반으로, 데이터 사이의 규칙을 학습해 새로운 입력이 들어왔을 때 결과를 예측함
- 정형/비정형 데이터에서 숨겨진 패턴과 추세를 찾아, 미래를 예측하거나 더 나은 의사결정에 활용함

### 머신러닝의 작동원리

- 데이터를 기반으로 학습하여 패턴을 인지하고, 새로운 데이터에 대해 예측이나 분류를 수행하는 인공지능 기술
- 대표적으로 '지도학습'을 사용
  - **분류(classification)**: 미리 정해진 범주로 나누기
  - **회귀(regression)**: 연속적인 값을 예측하기

---

## 슬라이드 7 — 데이터 분석 모델은 어떻게 만들어질까?

데이터 분석 모델은 다음 5단계를 거쳐 만들어집니다.

1. **데이터 수집** — 모델이 학습할 기반 정보를 모으는 단계
2. **데이터 전처리** — 수집한 데이터를 학습에 적합하도록 정제하는 과정
...

(이하 생략)
```

### 규칙

**문서 헤더 (1패스 결과 활용)**:
- H1 제목: `LectureContext.title` 사용 (PDF 파일명이 아닌 LLM이 추론한 강의 제목)
- 추출 메타: 일시, 원본 파일명, 페이지 수
- "강의 요약" 섹션: `topic_summary` + `domain_hints`
- "핵심 용어": `key_terms` 콤마 나열 (RAG 인덱스에 도움)

**페이지별 본문 (2패스 결과)**:
- 페이지마다 `## 슬라이드 N — {title}` (슬라이드 제목은 H2)
- `markdown_body`는 LLM이 시각자료 의미를 종합한 자급자족 본문
  - 본문 내 소제목은 `###` (슬라이드 제목보다 한 단계 작게)
  - 다이어그램·박스·표가 텍스트로 풀어쓰여 있음
- `image_region`이 있으면 본문 끝에 `![caption](images/...)` 추가 (보조 참조)
- `image_region`이 없으면 이미지 라인 자체가 없음 (예: 슬라이드 6)
- 페이지 사이는 `---` 구분선
- `cover` 분류 페이지는 마크다운에 안 나타남
- `section_divider` 페이지는 `## 슬라이드 N — {title}`만 남기고 본문 비움

## 7. 데이터 흐름 다이어그램 (요약)

```
PDF 업로드
   │
   ▼
[FastAPI] save → <DATA_DIR>/uploads/{job_id}/input.pdf
   │
   ▼
[FastAPI] store.create(...) → InMemoryJobStore[{id}] = Job(status=queued, ...)
[FastAPI] background_tasks.add_task(run_pipeline_job, ...)
   │
   ▼
[BG Worker] run_pipeline(job_id)
   │
   ├─ pdfinfo / 검증 → store.update_progress
   ├─ pdftoppm → <DATA_DIR>/outputs/{job_id}/pages/*.png
   ├─ pdfplumber → 페이지별 plain text (메모리)
   │
   ├─ for each page:
   │     ├─ provider.call_page_analysis → PageAnalysis
   │     ├─ if image_region: PIL crop → outputs/{job_id}/images/...
   │     └─ store.update_progress
   │
   ├─ build content.md → outputs/{job_id}/content.md
   ├─ zip → outputs/{job_id}/result.zip
   ├─ rm outputs/{job_id}/pages/  (임시 정리)
   ├─ append_usage_record(...) → logs/usage.log
   │
   ▼
[BG Worker] store.mark_done(job_id) → status=done, finished_at=now
   │
   ▼
[FastAPI] /jobs/{id}/download → result.zip
```
