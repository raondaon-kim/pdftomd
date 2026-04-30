# ARCHITECTURE — 시스템 아키텍처

## 1. 컴포넌트 구성도

```
┌─────────────────┐         ┌─────────────────────────────────┐
│                 │  HTTP   │   FastAPI (uvicorn, 9007)       │
│  Next.js (9017) │ ──────► │   ┌─────────────────────────┐   │
│  - 업로드 UI     │ ◄────── │   │ REST API (api/jobs.py)  │   │
│  - 진행률 표시   │  poll   │   └────────┬────────────────┘   │
│  - 다운로드 링크 │         │            │ schedule            │
│                 │         │   ┌────────▼────────────────┐   │
└─────────────────┘         │   │ BackgroundTasks worker  │   │
                            │   │ (api/worker.py)         │   │
                            │   │  - run_pipeline 호출    │   │
                            │   │  - InMemoryJobStore     │   │
                            │   │    에 진행률 갱신       │   │
                            │   └────────┬────────────────┘   │
                            └────────────┼────────────────────┘
                                         │ HTTPS
                                         ▼
                       ┌─────────────────┼─────────────────────┐
                       │                 │                     │
              ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
              │ Anthropic      │ │ Google         │ │ OpenAI         │
              │ Claude API     │ │ Gemini API     │ │ Chat API       │
              │ (Tool Use)     │ │ (responseSchema)│ │ (Strict JSON)  │
              └────────────────┘ └────────────────┘ └────────────────┘
                Haiku 4.5         2.5 / 3 Flash      GPT-5 / 5.4 mini

  데이터 디렉토리 (DATA_DIR):
  ┌────────────────────────────────────────────┐
  │  data/                                     │
  │  ├─ uploads/{job_id}/input.pdf             │  ← API가 저장
  │  ├─ outputs/{job_id}/                      │  ← Worker가 생성
  │  │   ├─ content.md                         │
  │  │   ├─ images/...                         │
  │  │   └─ result.zip                         │
  │  └─ logs/usage.log                         │  ← Worker가 1줄씩 누적
  └────────────────────────────────────────────┘
```

## 2. 프로세스 구성

단일 프로세스/단일 노드. 외부 인프라 없음.

| 컴포넌트 | 명령 | 포트 | 역할 |
|---|---|---|---|
| backend | `python -m app.main` (uvicorn) | 9007 | REST API + 같은 프로세스의 BackgroundTasks 워커 |
| frontend | `next dev` | 9017 | 웹 UI |

작업 상태는 `app.core.job_store.InMemoryJobStore`(프로세스 메모리, threading.Lock
보호)에 보관. **재시작 시 휘발됩니다.** 단일 사용자/사내 도구 시나리오라
이 트레이드오프를 받아들였습니다 — 클라우드 이전 시 같은 인터페이스로 Redis 등에
교체할 수 있도록 작업 저장소가 분리돼 있습니다.

## 3. 데이터 플로우 (Sequence Diagram)

```
사용자       Next.js     FastAPI API    JobStore    BG Worker    LLM API
                        (api/jobs.py)  (in-mem)   (api/worker)  (선택 모델)
  │            │           │              │           │             │
  │─[1]업로드─►│           │              │           │             │
  │            │─[2]POST──►│              │           │             │
  │            │  /jobs    │─[3]save PDF─►│           │             │
  │            │           │  + create    │           │             │
  │            │           │─[4]schedule─────────────►│             │
  │            │◄[5]job_id─│              │           │             │
  │            │           │              │           │─[6]validate │
  │            │           │              │           │  + render   │
  │   ┌────────┤           │              │           │             │
  │   │ 1초마다 폴링        │              │           │─[7]vision──►│
  │   │        │─[8]GET───►│─[9]read─────►│           │   per page  │
  │   │        │ /jobs/:id │              │           │◄────────────│
  │   │        │◄[10]상태──│              │           │             │
  │   │        │  진행률    │              │◄─────────│ update      │
  │   └────────┤           │              │           │  progress   │
  │            │           │              │           │─[11]crop─── │
  │            │           │              │           │  + zip      │
  │            │           │              │◄─────────│ mark_done +  │
  │            │           │              │           │ append usage│
  │            │           │              │           │  log        │
  │            │─[12]GET──►│              │           │             │
  │            │ /download │              │           │             │
  │◄[13]ZIP────│◄[14]read──result.zip─────│           │             │
```

핵심: 워커는 별도 프로세스/큐가 아니라 **같은 uvicorn 프로세스 안의
`BackgroundTasks`** 입니다. API 핸들러가 `background_tasks.add_task(run_pipeline_job, ...)`
로 스케줄하면, 응답 반환 직후 같은 이벤트 루프가 작업을 실행합니다.

## 4. 워커 처리 파이프라인 (페이지별)

```
┌─────────────────────────────────────────────────────────────┐
│  [PDF 입력]                                                  │
│      │                                                       │
│      ▼                                                       │
│  ┌────────────────────────┐                                  │
│  │ 1. pdfinfo + 검증       │  (페이지 수, 크기 체크)          │
│  └────────────────────────┘                                  │
│      │                                                       │
│      ▼                                                       │
│  ┌────────────────────────┐                                  │
│  │ 2. pdftoppm 페이지 렌더 │  (150 DPI PNG, 임시 파일)        │
│  │    + 100 DPI 썸네일도   │  (1패스 모자이크용)              │
│  └────────────────────────┘                                  │
│      │                                                       │
│      ▼                                                       │
│  ┌────────────────────────┐                                  │
│  │ 3. pdfplumber 텍스트    │  (페이지별 plain text)          │
│  └────────────────────────┘                                  │
│      │                                                       │
│      ▼                                                       │
│  ┌─────────────────────────────────────────────┐             │
│  │ 4. ★ 1패스: 강의 맥락 추출                  │             │
│  │    - 썸네일 모자이크 1장 생성 (PIL)         │             │
│  │    - 모든 페이지 텍스트 합치기              │             │
│  │    - Claude Vision 1회 호출                 │             │
│  │    - 출력: LectureContext                   │             │
│  │      (title, topic_summary, slide_outline,  │             │
│  │       key_terms, domain_hints)              │             │
│  │    - strict: 실패 시 작업 실패 (재시도 3회) │             │
│  └─────────────────────────────────────────────┘             │
│      │                                                       │
│      ▼                                                       │
│  ┌─── 페이지 N개 루프 (2패스) ─────────────────────────┐     │
│  │                                                    │     │
│  │   ┌────────────────────────────────────────┐       │     │
│  │   │ 5. Claude Vision 호출 (페이지별)         │       │     │
│  │   │    입력:                                │       │     │
│  │   │      - 시스템 프롬프트 + LectureContext │       │     │
│  │   │      - 페이지 이미지 + 페이지 텍스트     │       │     │
│  │   │    출력: PageAnalysis (JSON)           │       │     │
│  │   │      - classification                  │       │     │
│  │   │      - title                           │       │     │
│  │   │      - markdown_body                   │       │     │
│  │   │      - image_bbox? (정규화 0~1000)     │       │     │
│  │   │      - image_caption?                  │       │     │
│  │   └────────────────────────────────────────┘       │     │
│  │       │                                             │     │
│  │       ▼                                             │     │
│  │   ┌────────────────────────────────────────┐       │     │
│  │   │ 6. content == 'content'이고 bbox 있으면 │       │     │
│  │   │    PIL로 페이지 이미지 크롭             │       │     │
│  │   │    → /data/outputs/{job_id}/images/    │       │     │
│  │   └────────────────────────────────────────┘       │     │
│  │       │                                             │     │
│  │       ▼                                             │     │
│  │   ┌────────────────────────────────────────┐       │     │
│  │   │ 7. InMemoryJobStore 진행률 업데이트     │       │     │
│  │   │    (store.update_progress(...))        │       │     │
│  │   └────────────────────────────────────────┘       │     │
│  └────────────────────────────────────────────────────┘     │
│      │                                                       │
│      ▼                                                       │
│  ┌────────────────────────┐                                  │
│  │ 8. content.md 조립      │  (LectureContext도 헤더에 메타로 │
│  │    (페이지 순서대로)     │   추가 가능: 강의 요약, 핵심 용어)│
│  └────────────────────────┘                                  │
│      │                                                       │
│      ▼                                                       │
│  ┌────────────────────────┐                                  │
│  │ 9. result.zip 생성      │                                  │
│  └────────────────────────┘                                  │
│      │                                                       │
│      ▼                                                       │
│  ┌────────────────────────┐                                  │
│  │ 10. usage.log 1줄 추가  │  (job_id, 원본 PDF명, 모델,      │
│  │     (logs/usage.log)    │   토큰, USD 비용, ok=true)       │
│  └────────────────────────┘                                  │
│      │                                                       │
│      ▼                                                       │
│  [JobStore status = done]                                    │
└─────────────────────────────────────────────────────────────┘
```

**진행률 계산** (1패스도 진행률에 반영):
- 1패스 호출이 끝나면 progress_pct를 5%로 설정 (기여도 약간 작게)
- 2패스 페이지마다 5% + (page_num/total) * 95%

진행률 단계 매핑:
- `validating` → 0~2%
- `rasterizing` → 2~3%
- `extracting_text` → 3~4%
- `extracting_context` (1패스) → 4~5%
- `analyzing_page` (2패스) → 5~95%
- `cropping` → 95~98%
- `packaging` → 98~100%

## 5. 디렉토리 구조

```
pdftomd/
├── start_server.bat / stop_server.bat    # Windows 더블클릭 런처
├── .env.example                          # ANTHROPIC/GEMINI/OPENAI_API_KEY 등
├── README.md
├── docs/                                 # 본 설계 문서
│
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py                      # FastAPI 엔트리
│   │   ├── api/
│   │   │   ├── jobs.py                  # POST/GET /jobs, GET /jobs/:id/download
│   │   │   ├── health.py                # GET /health
│   │   │   └── worker.py                # BackgroundTasks 워커 함수
│   │   ├── core/
│   │   │   ├── config.py                # Settings (환경변수, 경로)
│   │   │   └── job_store.py             # InMemoryJobStore
│   │   ├── pipeline/                    # ⭐ 핵심 처리 로직
│   │   │   ├── runner.py                # run_pipeline 진입점
│   │   │   ├── pdf_io.py                # pdftoppm, pdfplumber 래퍼
│   │   │   ├── prompts.py               # 시스템 프롬프트 (모델 무관)
│   │   │   ├── crop.py                  # PIL bbox 크롭
│   │   │   ├── packager.py              # markdown 조립 + zip
│   │   │   ├── usage_log.py             # ⭐ 토큰/USD 비용 JSONL 로거
│   │   │   └── providers/               # ⭐ LLM 어댑터
│   │   │       ├── __init__.py          # make_provider, list_available_providers
│   │   │       ├── base.py              # LLMProvider Protocol + LLMError 계열
│   │   │       ├── claude.py            # ClaudeHaikuProvider (Tool Use)
│   │   │       ├── gemini.py            # GeminiProvider (2.5/3, responseSchema)
│   │   │       ├── openai.py            # OpenAIProvider (Strict JSON schema)
│   │   │       ├── schemas.py           # Pydantic → vendor schema 변환
│   │   │       └── registry.py          # 모델 ID ↔ display_name ↔ is_preview
│   │   └── models/                      # Pydantic 모델
│   │       ├── job.py                   # Job, JobStatus, JobError, CurrentStep
│   │       ├── lecture_context.py       # 1패스 출력
│   │       └── page_analysis.py         # 2패스 출력
│   └── tests/                           # 117 tests, pytest
│       ├── test_api.py
│       ├── test_pipeline.py
│       ├── test_provider_factory.py
│       ├── test_openai_schema.py
│       ├── test_usage_log.py
│       └── golden/                      # 골든 데이터셋 (LLM 평가용)
│
├── frontend/
│   ├── package.json
│   ├── next.config.js
│   ├── app/
│   │   ├── page.tsx                     # 업로드 + 진행 + 결과 (단일 페이지 흐름)
│   │   └── jobs/[id]/page.tsx           # 작업 URL 직접 진입 시
│   ├── components/                      # FileDropzone, ProgressBar, ...
│   └── lib/                             # api.ts, usePolling.ts
│
└── data/                                 # DATA_DIR (.gitignore)
    ├── uploads/{job_id}/
    ├── outputs/{job_id}/
    └── logs/usage.log
```

## 6. 기술 선택 근거

### 6.1 왜 FastAPI + Next.js 분리?

처음엔 "Next.js만으로 (API Routes 사용해서) 한 덩이"가 더 단순해 보이지만:
- PDF 처리에 필요한 `pdfplumber`, `pdftoppm`, `Pillow` 같은 파이썬 도구가 노드에서 안 돎
- LLM 호출하면서 PDF 다루는 작업은 결국 파이썬으로 가야 함
- 그러면 어차피 백엔드는 파이썬, 프론트는 별도

### 6.2 왜 BackgroundTasks + InMemoryJobStore?

| 옵션 | 장점 | 단점 |
|---|---|---|
| Celery | 산업 표준, 풍부한 기능 | 설정 복잡, 단일 워커엔 과함 |
| RQ | 간단, 코드 한 파일 | Redis 의존 — 개인 PC에 띄울 추가 인프라 |
| **FastAPI BackgroundTasks + InMemoryJobStore** | 외부 의존성 0, 더블클릭 한 번으로 실행 | 프로세스 재시작 시 진행 중 작업 소실, 단일 사용자 가정 |
| Dramatiq | RQ와 비슷, 좀 더 안정적 | 인지도 낮음 |

**BackgroundTasks + InMemoryJobStore 선택**. 사내/개인용 단일 사용자 도구라 작업
손실의 비용이 낮고, "윈도우에서 더블클릭 한 번으로 실행" 요구가 명시적이었습니다.
`InMemoryJobStore`는 작업 저장소 인터페이스를 분리해 두어, 다중 사용자/클라우드로
이전할 때 같은 메서드 시그니처로 Redis 구현을 끼워 넣을 수 있습니다.

### 6.3 왜 Next.js (Vite/Vue/SvelteKit 대신)?

특별한 이유 없이 — 의사결정자가 가장 익숙한 스택 가정. SPA 한 페이지짜리라 사실 어떤 프레임워크든 됨. **변경 가능**.

## 7. 보안 / 격리

개인용이지만 최소한의 위생:

- 업로드 PDF는 검증 후 사용자별 격리된 디렉토리(`/data/uploads/{job_id}/`)에 저장
- `job_id`는 UUID v4 (예측 불가)
- 1시간 후 cron/cleanup task가 결과 파일 삭제
- LLM API 키는 환경 변수로만 (`.env`, 절대 커밋 X)
  - `ANTHROPIC_API_KEY` (Claude Haiku 4.5)
  - `GEMINI_API_KEY` (Gemini 2.5 / 3 Flash 공통)
  - `OPENAI_API_KEY` (GPT-5 mini / GPT-5.4 mini 공통)
  - 키가 설정된 모델만 UI에 활성화로 노출
- CORS는 `CORS_ORIGINS`(기본 `http://localhost:9017`)만 허용
- 업로드 파일 타입 검증 (`Content-Type` + `magic bytes`)

## 8. 향후 확장 포인트

| 확장 | 영향받는 컴포넌트 | 난이도 |
|---|---|---|
| 클라우드 배포 | INFRA.md 추가, S3 볼륨, Postgres 추가 | 중 |
| 다중 사용자 | 인증, job 소유자 체크, `InMemoryJobStore` → Redis/Postgres 교체 | 중 |
| 결과 미리보기 | Frontend + 새 API 엔드포인트 | 하 |
| OCR 폴백 | pipeline에 tesseract 단계 추가 | 중 |
| 작업 히스토리 | DB 도입 (지금은 메모리 + `usage.log` JSONL만) | 중 |
| 비용 대시보드 | `usage.log` 집계 UI (jq 대용) | 하 |

위 시점에 다시 설계서 갱신.
