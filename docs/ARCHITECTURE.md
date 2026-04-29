# ARCHITECTURE — 시스템 아키텍처

## 1. 컴포넌트 구성도

```
┌─────────────────┐         ┌─────────────────────────┐
│                 │  HTTP   │                         │
│  Next.js (3000) │ ──────► │   FastAPI (8000)        │
│  - 업로드 UI     │ ◄────── │   - REST API            │
│  - 진행률 표시   │  poll   │   - 작업 enqueue/조회    │
│  - 다운로드 링크 │         │                         │
│                 │         └──────────┬──────────────┘
└─────────────────┘                    │
                                       │ enqueue
                                       ▼
                              ┌────────────────┐
                              │  Redis (6379)  │
                              │  - 작업 큐      │
                              │  - 진행 상태    │
                              └────────┬───────┘
                                       │ dequeue
                                       ▼
                              ┌────────────────────────────┐
                              │  RQ Worker (Python)        │
                              │  - PDF 처리                │
                              │  - LLM Provider 호출        │
                              │  - 이미지 크롭 / ZIP 생성   │
                              └────────┬───────────────────┘
                                       │ HTTPS
                                       ▼
                       ┌───────────────┴───────────────┐
                       │                               │
                ┌──────────────┐              ┌──────────────┐
                │ Anthropic    │              │ Google       │
                │ Claude API   │              │ Gemini API   │
                └──────────────┘              └──────────────┘
                  Haiku 4.5                   2.5 / 3 Flash

  공유 볼륨:
  ┌──────────────────────────────────────┐
  │  /data/                              │
  │  ├─ uploads/{job_id}/input.pdf       │  ← FastAPI가 쓰고 Worker가 읽음
  │  └─ outputs/{job_id}/                │  ← Worker가 쓰고 FastAPI가 읽음
  │     ├─ content.md                    │
  │     ├─ images/...                    │
  │     └─ result.zip                    │
  └──────────────────────────────────────┘
```

## 2. 컨테이너 구성 (docker-compose)

| 서비스 | 이미지 | 포트 | 역할 |
|---|---|---|---|
| `frontend` | node:20-alpine + Next.js | 3000 | 웹 UI |
| `backend` | python:3.11-slim + poppler-utils | 8000 | REST API |
| `worker` | (backend와 동일 이미지) | - | RQ 워커, PDF 처리 |
| `redis` | redis:7-alpine | 6379 | 큐 + 상태 |

`backend`와 `worker`는 동일한 Docker 이미지에서 다른 명령으로 실행:
- backend: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- worker: `rq worker pdf-jobs --url redis://redis:6379`

## 3. 데이터 플로우 (Sequence Diagram)

```
사용자       Next.js     FastAPI      Redis      Worker      LLM API
                                                            (선택된 모델)
  │            │           │            │          │             │
  │─[1]업로드─►│           │            │          │             │
  │            │─[2]POST──►│            │          │             │
  │            │  /jobs    │            │          │             │
  │            │           │─[3]save────┤          │             │
  │            │           │  PDF       │          │             │
  │            │           │─[4]enqueue►│          │             │
  │            │           │            │─[5]pop──►│             │
  │            │◄[6]job_id─│            │          │             │
  │            │           │            │          │─[7]rasterize│
  │            │           │            │          │  pages      │
  │            │           │            │          │             │
  │   ┌────────┤           │            │          │─[8]vision──►│
  │   │ 1초마다 폴링        │            │          │   per page  │
  │   │        │─[9]GET───►│            │          │◄────────────│
  │   │        │ /jobs/:id │─[10]get────│          │             │
  │   │        │           │  state     │          │             │
  │   │        │◄[11]상태──│            │          │─[12]crop────│
  │   │        │  진행률    │            │          │  & write    │
  │   └────────┤           │            │          │             │
  │            │           │            │          │─[13]done───►│
  │            │           │            │◄─────────│  set state  │
  │            │           │            │          │             │
  │            │─[14]GET──►│            │          │             │
  │            │ /download │─[15]read───┤          │             │
  │            │           │  result.zip│          │             │
  │◄[16]ZIP────│◄──────────│            │          │             │
```

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
│  │   │ 7. Redis에 진행률 업데이트              │       │     │
│  │   │    (job:{id}:progress = N/total)       │       │     │
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
│  [Redis status = done]                                       │
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
pdf-slide-extractor/
├── docker-compose.yml
├── .env.example                  # ANTHROPIC_API_KEY 등
├── README.md
├── docs/                         # 본 설계 문서
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py              # FastAPI 엔트리
│   │   ├── api/
│   │   │   ├── jobs.py          # POST/GET /jobs, GET /jobs/:id/download
│   │   │   └── health.py
│   │   ├── core/
│   │   │   ├── config.py        # 환경변수, 경로
│   │   │   └── queue.py         # RQ 큐 인스턴스
│   │   ├── pipeline/            # ⭐ 핵심 처리 로직
│   │   │   ├── runner.py        # 전체 파이프라인 진입점 (RQ task)
│   │   │   ├── pdf_io.py        # pdftoppm, pdfplumber 래퍼
│   │   │   ├── mosaic.py        # 1패스용 썸네일 모자이크 생성 (PIL)
│   │   │   ├── prompts.py       # 시스템 프롬프트 텍스트 (모델 무관)
│   │   │   ├── crop.py          # PIL bbox 크롭
│   │   │   ├── packager.py      # markdown 조립 + zip
│   │   │   └── providers/       # ⭐ LLM 어댑터
│   │   │       ├── __init__.py  # make_provider, list_available_providers
│   │   │       ├── base.py      # LLMProvider Protocol + LLMError 계열
│   │   │       ├── claude.py    # ClaudeHaikuProvider (Tool Use)
│   │   │       ├── gemini.py    # GeminiProvider (responseSchema, 2.5/3 공용)
│   │   │       ├── schemas.py   # Pydantic → tool/responseSchema 변환
│   │   │       └── registry.py  # 모델 ID ↔ display_name ↔ is_preview 매핑
│   │   ├── models/              # Pydantic 모델
│   │   │   ├── job.py
│   │   │   ├── lecture_context.py  # 1패스 출력 (모델 무관)
│   │   │   └── page_analysis.py    # 2패스 출력 (모델 무관)
│   │   └── storage/
│   │       └── files.py         # /data 경로 관리
│   └── tests/
│       ├── test_pipeline.py
│       ├── golden/              # 골든 데이터셋
│       │   └── deepco_kdc_18.pdf
│       └── fixtures/
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── next.config.js
│   ├── app/
│   │   ├── page.tsx             # 업로드 화면
│   │   ├── jobs/[id]/page.tsx   # 진행 상황 + 다운로드
│   │   └── api/                 # (BFF 역할이 필요할 때만)
│   ├── components/
│   │   ├── FileDropzone.tsx
│   │   ├── ProgressBar.tsx
│   │   └── DownloadButton.tsx
│   └── lib/
│       └── api.ts               # 백엔드 호출 래퍼
│
└── data/                         # docker volume 마운트 (.gitignore)
    ├── uploads/
    └── outputs/
```

## 6. 기술 선택 근거

### 6.1 왜 FastAPI + Next.js 분리?

처음엔 "Next.js만으로 (API Routes 사용해서) 한 덩이"가 더 단순해 보이지만:
- PDF 처리에 필요한 `pdfplumber`, `pdftoppm`, `Pillow` 같은 파이썬 도구가 노드에서 안 돎
- LLM 호출하면서 PDF 다루는 작업은 결국 파이썬으로 가야 함
- 그러면 어차피 백엔드는 파이썬, 프론트는 별도

### 6.2 왜 Redis + RQ?

| 옵션 | 장점 | 단점 |
|---|---|---|
| Celery | 산업 표준, 풍부한 기능 | 설정 복잡, 단일 워커엔 과함 |
| **RQ** | 간단, 코드 한 파일, Redis만 있으면 됨 | 분산 처리·재시도 설정이 단순 |
| FastAPI BackgroundTasks | 인프라 0개 | 워커 죽으면 작업 소실, 진행률 추적 어려움 |
| Dramatiq | RQ와 비슷, 좀 더 안정적 | 인지도 낮음 |

**RQ 선택**. 단일 노드·단일 큐 시나리오에 정확히 맞고, Redis는 어차피 진행률 저장용으로 필요.

### 6.3 왜 Next.js (Vite/Vue/SvelteKit 대신)?

특별한 이유 없이 — 의사결정자가 가장 익숙한 스택 가정. SPA 한 페이지짜리라 사실 어떤 프레임워크든 됨. **변경 가능**.

## 7. 보안 / 격리

개인용이지만 최소한의 위생:

- 업로드 PDF는 검증 후 사용자별 격리된 디렉토리(`/data/uploads/{job_id}/`)에 저장
- `job_id`는 UUID v4 (예측 불가)
- 1시간 후 cron/cleanup task가 결과 파일 삭제
- LLM API 키는 환경 변수로만 (`.env`, 절대 커밋 X)
  - `ANTHROPIC_API_KEY` (Claude)
  - `GEMINI_API_KEY` (Gemini 2.5/3 공통)
  - 키가 설정된 모델만 UI에 활성화로 노출
- CORS는 `localhost:3000`만 허용
- 업로드 파일 타입 검증 (`Content-Type` + `magic bytes`)

## 8. 향후 확장 포인트

| 확장 | 영향받는 컴포넌트 | 난이도 |
|---|---|---|
| 클라우드 배포 | INFRA.md 추가, S3 볼륨, Postgres 추가 | 중 |
| 다중 사용자 | 인증, job 소유자 체크 | 중 |
| 결과 미리보기 | Frontend + 새 API 엔드포인트 | 하 |
| OCR 폴백 | pipeline에 tesseract 단계 추가 | 중 |
| 작업 히스토리 | DB 도입 (지금은 Redis만) | 중 |

위 시점에 다시 설계서 갱신.
