# PDF Slide Extractor (`pdftomd`)

**한국어** · [English](README.en.md)

LLM Vision으로 PDF(주로 강의 슬라이드)를 **자급자족 마크다운 + 잘라낸 이미지**로 변환하는 로컬 단일 사용자용 웹 도구입니다. 텍스트만 읽어도 학습 내용이 완결되도록 다이어그램·표·박스·화살표의 의미를 함께 풀어 씁니다.

- 🧠 **2-pass 파이프라인**: ① 강의 전체 맥락(주제/용어/슬라이드 개요) 추출 → ② 페이지별 마크다운 + 이미지 영역 결정
- 🔌 **모델 5종**: `claude-haiku-4-5` (Anthropic), `gemini-2-5-flash`, `gemini-3-flash` (Google), `gpt-5-mini`, `gpt-5.4-mini` (OpenAI)
- 🖥️ **단일 프로세스 백엔드**: FastAPI + `BackgroundTasks`. Redis/Docker/별도 워커 없음
- 🧩 **다중 PDF 큐**: 여러 PDF를 드래그앤드롭 → 완전 직렬 자동 연속 처리
- ✅ **테스트 100개** (`pytest`), 28페이지 골든 PDF로 분류 100% 검증

## 목차

1. [무엇이 만들어지나 (입력/출력)](#1-무엇이-만들어지나-입력출력)
2. [동작 방식](#2-동작-방식)
3. [디렉토리 구조](#3-디렉토리-구조)
4. [요구 사항](#4-요구-사항)
5. [설치 + 실행](#5-설치--실행)
6. [환경 변수](#6-환경-변수)
7. [CLI](#7-cli)
8. [REST API](#8-rest-api)
9. [모델 비교](#9-모델-비교)
10. [개발](#10-개발)
11. [트러블슈팅](#11-트러블슈팅)
12. [한계 / 비목표](#12-한계--비목표)
13. [로드맵](#13-로드맵)
14. [라이선스](#14-라이선스)

---

## 1. 무엇이 만들어지나 (입력/출력)

**입력**: PDF 1개(파일당 ≤100MB / ≤100페이지). 한글 / 공백이 들어간 파일명도 OK.

**출력**: ZIP 1개. 풀어보면:

```
result.zip
├── content.md          # 페이지 순서대로 합쳐진 마크다운
└── images/
    ├── 06_데이터분석모델.png
    ├── 11_공공데이터포털화면.png
    └── ...
```

`content.md` 예:

```markdown
# 데이터 사이언스 입문 — 18회차

> **핵심 용어**: 공공데이터, OpenAPI, JSON, 시각화

## 6. 데이터 분석 모델이란?

데이터 분석 모델은 …(다이어그램 내용을 텍스트로 풀어서 설명)…

![데이터 분석 모델 도식](images/06_데이터분석모델.png)
*그림: 입력→전처리→모델→결과 흐름*

## 8. 공공데이터 알아보기
...
```

**핵심 원칙**: 마크다운만 RAG/파인튜닝 인덱스에 넣어도 학습 내용이 완결되어야 합니다. 이미지는 시각 보조 *참조용*입니다.

페이지 분류는 LLM이 4가지 중 하나로 결정합니다:

| 분류 | 처리 |
|---|---|
| `content` | 본문. 마크다운 작성 + (필요 시) 이미지 영역 추출 |
| `section_divider` | "오늘의 학습 알아보기" 같은 구분 페이지 → H2 제목만 |
| `cover` | 표지/종료 → 마크다운에 넣지 않음 |
| `decorative_only` | 일러스트만 있는 페이지 → 텍스트만, 이미지 추출 안 함 |

## 2. 동작 방식

### 2.1 2-pass 파이프라인

```
   PDF 입력
      │
      ▼
[1] 검증 (≤100MB, ≤100p) ─ pdfplumber + PyMuPDF
[2] 페이지 래스터화 (150 DPI PNG) ─ PyMuPDF/fitz
[3] 페이지별 텍스트 추출 ─ pdfplumber
      │
      ▼
[4] ★ Pass 1: 강의 전체 맥락 추출 (LLM 1회)
      • 6×5 썸네일 모자이크 1장 (8000px max) ─ Pillow
      • 모든 페이지 텍스트 합치기 (페이지당 1000자 트림)
      • 출력: LectureContext { title, topic_summary, slide_outline[], key_terms[], domain_hints }
      • strict 모드 — 검증 실패 시 3회 지수 백오프 재시도, 전부 실패하면 작업 실패
      │
      ▼
[5] ★ Pass 2: 페이지별 분석 (페이지당 LLM 1회)
      • 입력: 시스템 프롬프트 + LectureContext 요약 + 페이지 PNG + 페이지 텍스트
      • 출력: PageAnalysis { classification, title, markdown_body, image_region?, image_caption?, reasoning }
      │
      ▼
[6] image_region이 있는 'content' 페이지에 대해 PIL 크롭 → images/<n>_<slug>.png
[7] content.md 조립 (페이지 순서대로) + result.zip 패키징
```

**진행률 매핑**: `validating(0–2%) → rasterizing(2–3%) → extracting_text(3–4%) → extracting_context(4–5%) → analyzing_page(5–95%) → cropping(95–98%) → packaging(98–100%)`

### 2.2 LLM 어댑터

각 모델 SDK의 차이를 `LLMProvider` Protocol 한 겹으로 흡수합니다.

| 모델 | SDK | 구조화 출력 방식 | 비고 |
|---|---|---|---|
| Claude Haiku 4.5 | `anthropic` | **Tool Use** (`tools=[{input_schema:...}]`) | 한국어 / 안정성 균형 |
| Gemini 2.5 Flash | `google-genai` | **`response_schema`** (OpenAPI subset) | 가장 저렴 |
| Gemini 3 Flash | `google-genai` | **`response_schema`** | 속도 약 2배 |
| GPT-5.4 mini | `openai` | **Strict JSON Schema** (`response_format`) | 비전·추론 강세, 다이어그램에 유리 |

Pydantic JSON Schema → Gemini OpenAPI Schema 변환기(`providers/schemas.py`)가 `$ref` 인라인화, `Optional[X]` → `nullable: true`, 타입 대문자화, 미지원 키 제거를 해줍니다.

`patch_page_analysis_payload()`는 LLM이 흔히 내는 작은 위반(빠진 `page_num`, [0,1000] 초과 bbox, `decorative_only`인데 `image_region` 채움, `image_region` 없는데 `image_caption` 있음 등)을 자동 보정합니다.

### 2.3 작업 큐 (단일 프로세스)

- API가 PDF를 받으면 `uploads/{job_id}/input.pdf`로 저장하고 `BackgroundTasks`로 파이프라인을 즉시 디스패치합니다.
- 작업 상태는 인메모리 `InMemoryJobStore`(스레드 락 보호) — 서버 재시작 시 휘발됩니다.
- 결과 파일은 `outputs/{job_id}/`에 `content.md`, `images/`, `result.zip`으로 저장됩니다.
- 프론트엔드는 1초 간격 폴링으로 상태를 받고, 완료 즉시 다음 PDF를 자동으로 시작합니다 (완전 직렬).

> ⚠️ 인메모리 큐는 단일 사용자 가정입니다. 서버를 재시작하면 진행 중이던 작업의 메타가 사라집니다 (디스크의 결과 ZIP은 남음). 다중 사용자 / 영속 큐가 필요하면 [13. 로드맵](#13-로드맵) 참조.

## 3. 디렉토리 구조

```
pdftomd/
├── README.md                    ← 이 문서
├── .env.example                 ← 환경 변수 템플릿
├── docs/                        ← 설계 문서 (PRD / ARCHITECTURE / API / DATA_MODEL / FRONTEND / LLM_PROMPTS / INFRA / ROADMAP / TESTING)
│
├── backend/
│   ├── pyproject.toml
│   └── app/
│       ├── main.py              ← FastAPI 엔트리 (CORS, 예외 매퍼)
│       ├── cli.py               ← 단독 CLI: python -m app.cli <pdf>
│       ├── api/
│       │   ├── jobs.py          ← POST /jobs, GET /jobs/{id}, /download, /content, /images/{file}, DELETE
│       │   ├── models.py        ← GET /models
│       │   ├── health.py        ← GET /health
│       │   ├── worker.py        ← run_pipeline_job (BackgroundTasks 함수)
│       │   └── errors.py
│       ├── core/
│       │   ├── config.py        ← Pydantic Settings (.env 로딩, data_dir 해석)
│       │   └── job_store.py     ← InMemoryJobStore (threading.Lock)
│       ├── models/              ← Pydantic
│       │   ├── job.py           ← Job, JobStatus, JobStep, JobError
│       │   ├── page_analysis.py ← Pass 2 출력
│       │   └── lecture_context.py ← Pass 1 출력
│       └── pipeline/
│           ├── runner.py        ← 전체 파이프라인 entry
│           ├── pdf_io.py        ← validate / rasterize / extract_text
│           ├── mosaic.py        ← Pass 1용 썸네일 모자이크 (PIL)
│           ├── lecture_pass.py  ← Pass 1 호출 + retry/검증
│           ├── crop.py          ← bbox(0–1000) → PNG
│           ├── packager.py      ← content.md 조립 + ZIP
│           ├── prompts.py       ← 시스템/유저 프롬프트 (모델 무관)
│           └── providers/
│               ├── base.py      ← LLMProvider Protocol, ProviderInfo, payload patcher
│               ├── claude.py    ← ClaudeHaikuProvider (Tool Use)
│               ├── gemini.py    ← GeminiProvider (variant=2-5/3)
│               ├── schemas.py   ← Pydantic JSON Schema → Gemini OpenAPI 변환
│               └── registry.py  ← 모델 ID ↔ display_name ↔ enabled
│
├── frontend/
│   ├── package.json             ← Next 14, React 18, Tailwind 3, react-dropzone
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── next.config.mjs
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── globals.css
│   │   ├── page.tsx             ← 업로드 + 큐 + 모델 선택 + 자동 연속 처리
│   │   └── jobs/[id]/page.tsx   ← 상세: queued/processing/done/failed 한 페이지에 분기
│   ├── components/
│   │   ├── FileDropzone.tsx     ← 다중 PDF 드롭 (react-dropzone)
│   │   ├── ModelSelector.tsx    ← 라디오 + 비활성/베타 라벨
│   │   ├── ProgressBar.tsx
│   │   ├── QueueItem.tsx        ← 큐 1개 카드 (pending/uploading/running/done/failed)
│   │   ├── DownloadButton.tsx
│   │   ├── ModelBadge.tsx
│   │   ├── ErrorBox.tsx
│   │   └── MarkdownPreview.tsx  ← /jobs/[id] 완료 화면용 인라인 미리보기
│   └── lib/
│       ├── api.ts               ← listModels / uploadPdf / getJob / getJobContent / deleteJob / getDownloadUrl / getImageUrl
│       ├── usePolling.ts        ← /jobs/[id] 1초 폴링 훅
│       ├── types.ts             ← API 응답 타입 + ApiError
│       └── format.ts            ← stepLabel, ETA, formatBytes
│
└── data/                        ← 런타임 (gitignored)
    ├── uploads/{job_id}/input.pdf
    └── outputs/{job_id}/
        ├── content.md
        ├── images/
        └── result.zip
```

## 4. 요구 사항

| 항목 | 버전 |
|---|---|
| Python | **3.11+** |
| Node.js | **20+** (npm 10+) |
| OS | Windows 10/11, macOS, Linux 동일하게 동작 |
| LLM API 키 | **`ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` 중 최소 1개** |

> Docker나 Redis는 필요 없습니다. PDF 래스터화는 **PyMuPDF**가 처리하므로 poppler/pdftoppm 시스템 의존성도 없습니다.

## 5. 설치 + 실행

### 5.1 저장소 받기

```bash
git clone https://github.com/<owner>/pdftomd.git
cd pdftomd
```

### 5.2 환경 변수 설정

```bash
cp .env.example .env
# 편집기로 .env 열어서 ANTHROPIC_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY 중 하나 채우기
```

자세한 항목은 [§6 환경 변수](#6-환경-변수) 참고.

### 5.3 ⭐ Windows: 더블클릭 한 번으로 시작 (권장)

가장 간단한 사용 방법. 사내 동료에게 배포할 때 이 방식을 쓰세요.

`start_server.bat` 파일을 **더블클릭**하면:

1. 9007/9017 포트가 이미 사용 중이면 PID와 종료 명령을 알려주고 종료 (재실행 안내)
2. 처음 실행 시 백엔드/프론트엔드 의존성을 자동 설치 (`pip install -e .` + `npm install`)
3. 백엔드(9007)를 새 콘솔 창에 띄움 → 헬스체크 응답 대기
4. 프론트엔드(9017)를 또 다른 콘솔 창에 띄움 → 헬스체크 응답 대기
5. 기본 브라우저로 http://localhost:9017 자동 오픈
6. 런처 창은 5초 후 자동 종료. 백엔드/프론트 창은 그대로 유지

종료할 때는 `stop_server.bat` 더블클릭 (또는 백엔드/프론트엔드 콘솔 창 직접 닫기).

> **사내 배포 메모**: bat 파일은 자기 위치(`%~dp0`)를 기준으로 동작하므로 어떤 드라이브 / 폴더(공백·한글 이름 포함)에 풀어 두어도 작동합니다. **사전 요구**: Python 3.11+ / Node 20+가 PATH에 있어야 하고, 프로젝트 루트에 `.env`가 있어야 합니다(`.env.example` 복사 후 키 채우기).
>
> **기술 메모**: bat 메시지는 인코딩 사고를 피하려고 ASCII 영문으로만 작성됐습니다. `chcp 65001`(UTF-8) 전환은 일부 Windows 10 빌드에서 cmd 파서를 깨뜨리는 알려진 이슈가 있어 사용하지 않습니다. 한글 폴더명을 에러 메시지에 출력할 때만 깨져 보일 수 있지만 동작 자체는 정상입니다.

### 5.4 수동 실행 (개발자용 / macOS / Linux)

수정 작업 중이거나 비-Windows 환경이라면 수동으로 시작:

#### 백엔드 (포트 9007)

```bash
cd backend
python -m venv .venv
# Windows (Git Bash):
source .venv/Scripts/activate
# macOS/Linux:
# source .venv/bin/activate

pip install -e .[dev]

# 서버 시작
python -m uvicorn app.main:app --host 127.0.0.1 --port 9007 --reload
```

**확인**: http://127.0.0.1:9007/health → `{"status":"ok", ...}`

#### 프론트엔드 (포트 9017)

새 터미널에서:

```bash
cd frontend
npm install
npm run dev
```

**확인**: 브라우저에서 http://localhost:9017 → 업로드 화면이 나타나면 OK.

### 5.5 사용

1. PDF를 드롭존에 드래그앤드롭 (여러 개 가능 — 한글/공백 파일명 OK)
2. 분석 모델 선택 (기본: Gemini 2.5 Flash)
3. **추출 시작** 클릭 → 큐에 있는 PDF가 하나씩 자동으로 처리됨
4. 각 항목이 완료되면 카드에 **📥 ZIP 다운로드** 버튼이 나타남
5. ZIP 파일명은 원본 PDF명 그대로 (`강의자료.pdf` → `강의자료.zip`)

> 💡 처리 중에 PDF를 더 드롭하면 큐 끝에 추가되어 그것도 차례로 처리됩니다. 페이지를 닫아도 백엔드 작업은 계속 진행되므로 `/jobs/{id}` URL을 북마크하면 다시 와서 결과를 받을 수 있습니다 (서버 재시작 전까지).

## 6. 환경 변수

`.env`를 프로젝트 루트(`pdftomd/`)에 둡니다. 백엔드가 자동으로 찾아 읽습니다.

| 변수 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | × | — | 설정 시 `claude-haiku-4-5` 활성화. **미설정이어도 서버는 정상 기동됨** |
| `GEMINI_API_KEY` | × | — | 설정 시 `gemini-2-5-flash` / `gemini-3-flash` 활성화 |
| `OPENAI_API_KEY` | × | — | 설정 시 `gpt-5-mini` / `gpt-5.4-mini` 활성화 |
| `MAX_PDF_SIZE_MB` | × | `100` | 업로드 크기 제한 (MB) |
| `MAX_PDF_PAGES` | × | `100` | 페이지 수 제한 |
| `RESULT_TTL_SECONDS` | × | `3600` | 결과 보존 시간 (초) — 현재 자동 삭제는 미구현, 메타값만 |
| `RENDER_DPI` | × | `150` | Pass 2 페이지 래스터 DPI |
| `DATA_DIR` | × | `./data` | uploads/outputs 루트. **상대 경로는 프로젝트 루트 기준**으로 해석됨 |
| `BACKEND_PORT` | × | `9007` | 정보용 (uvicorn 명령에 직접 전달 필요) |
| `FRONTEND_PORT` | × | `9017` | 정보용 (`package.json` 스크립트에 하드코딩됨) |
| `CORS_ORIGINS` | × | `http://localhost:9017` | 콤마 구분 허용 origin |

> **API 키 없이도 서버가 기동됩니다.** 키는 `POST /jobs` 요청 시 `api_key` 필드로 직접 전달할 수 있습니다 ([§8 백엔드 단독 사용](#백엔드-단독-사용-프론트-없이-api-직접-호출) 참고). env에 키를 설정하면 프론트엔드 UI에서 해당 모델이 활성화되고, 미설정 시 비활성화(회색)로 표시됩니다.

### 프론트엔드용

`frontend/.env.local` (선택):

```
NEXT_PUBLIC_API_BASE=http://localhost:9007
```

미설정 시 `http://localhost:9007`을 기본값으로 씁니다.

> 🔒 `.env`와 `frontend/.env.local`은 `.gitignore`에 들어 있습니다. 절대 커밋하지 마세요. 키가 노출되었다면 즉시 콘솔에서 회전(revoke + 신규 발급)하세요.

## 7. CLI

GUI 없이 단일 PDF를 처리하려면:

```bash
cd backend
python -m app.cli path/to/input.pdf -o ./out --model claude-haiku-4-5
```

**옵션**:

| 플래그 | 설명 |
|---|---|
| `-o`, `--output-dir DIR` | 결과 폴더 (기본 `./out`) |
| `--model {claude-haiku-4-5,gemini-2-5-flash,gemini-3-flash,gpt-5-mini,gpt-5.4-mini}` | 모델 ID (생략 시 첫 번째 enabled 모델) |
| `--dpi N` | Pass 2 래스터 DPI (기본 `RENDER_DPI`) |
| `--keep-pages` | 임시 `pages/` 디렉토리를 남김 (디버깅용) |
| `--list-models` | 모델별 enabled / preview / 비용 표 출력 후 종료 |
| `-v` / `-vv` | INFO / DEBUG 로그 |

**종료 코드**: `0` 성공, `2` 잘못된 사용/모델 키 없음, `3` PDF 검증 실패, `4` LLM 호출 실패, `130` `Ctrl+C`.

예:

```bash
python -m app.cli --list-models
# ID                  enabled  preview  cost/PDF   name
# claude-haiku-4-5    yes      no       $0.20      Claude Haiku 4.5
# gemini-2-5-flash    yes      no       $0.10      Gemini 2.5 Flash
# gemini-3-flash      yes      no       $0.20      Gemini 3 Flash
# gpt-5-mini          yes      no       $0.30      GPT-5 mini
# gpt-5.4-mini        yes      no       $0.45      GPT-5.4 mini

python -m app.cli ./test.pdf -o ./out --model gemini-3-flash -v
# input:    test.pdf
# output:   out
# model:    gemini-3-flash
# [ 95%] analyzing_page: page 28/28
# Done in 142.3s
#   pages:    28
#   content:  out/content.md
#   zip:      out/result.zip
```

## 8. REST API

기준 URL: `http://localhost:9007`. 모든 응답은 JSON. 상세 사양은 [docs/API.md](docs/API.md)를 참고하세요.

### 공통 에러 응답

```json
{ "error": { "code": "INVALID_PDF", "message": "...", "details": null } }
```

| HTTP | code | 의미 |
|---|---|---|
| 400 | `INVALID_FILE_TYPE` | PDF가 아닌 파일, 또는 잘못된 magic bytes |
| 400 | `FILE_TOO_LARGE` | `MAX_PDF_SIZE_MB` 초과 |
| 400 | `TOO_MANY_PAGES` | `MAX_PDF_PAGES` 초과 |
| 400 | `INVALID_MODEL` | 알 수 없는 모델 ID |
| 400 | `MODEL_NOT_AVAILABLE` | 해당 모델의 API 키가 서버에 없음 |
| 400 | `INVALID_FILENAME` | 이미지 경로에 `..` `/` `\` 포함 |
| 404 | `JOB_NOT_FOUND` | 존재하지 않거나 삭제된 job_id |
| 404 | `RESULT_NOT_READY` | 작업이 아직 done 상태가 아님 |
| 404 | `IMAGE_NOT_FOUND` | 요청한 이미지가 outputs/<id>/images에 없음 |
| 500 | `INTERNAL_ERROR` | 잡지 못한 예외 |
| 500 | `CONTEXT_EXTRACTION_FAILED` | Pass 1 3회 재시도 후에도 실패 |
| 502 | `LLM_API_ERROR` | LLM 호출 자체 실패 |

### 엔드포인트

#### `GET /health`

```json
{ "status": "ok", "data_dir": "D:\\pdftomd\\data", "active_jobs": 0 }
```

#### `GET /models`

키가 설정된 모델만 `enabled: true`.

```json
{ "models": [
  { "id": "claude-haiku-4-5", "display_name": "Claude Haiku 4.5", "provider": "anthropic",
    "is_preview": false, "enabled": true, "estimated_cost_per_pdf_usd": 0.20,
    "notes": "한국어와 안정성 균형. 비전 양호." },
  { "id": "gemini-2-5-flash", "display_name": "Gemini 2.5 Flash", "provider": "google",
    "is_preview": false, "enabled": true, "estimated_cost_per_pdf_usd": 0.10,
    "notes": "가장 저렴. 한국어 양호." },
  { "id": "gemini-3-flash", "display_name": "Gemini 3 Flash", "provider": "google",
    "is_preview": false, "enabled": true, "estimated_cost_per_pdf_usd": 0.20,
    "notes": "속도 약 2배. 멀티모달 이해 강세 — 블록 코드/복잡 다이어그램에 유리." },
  { "id": "gpt-5.4-mini", "display_name": "GPT-5.4 mini", "provider": "openai",
    "is_preview": false, "enabled": true, "estimated_cost_per_pdf_usd": 0.45,
    "notes": "비전·추론 모두 강세. GPT-5 mini 대비 약 2배 빠르고 멀티모달 이해 향상." }
]}
```

#### `POST /jobs` — 작업 생성

`multipart/form-data`:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `file` | File | ✓ | PDF (UTF-8 한글/공백 파일명 OK) |
| `model` | string | ✓ | 모델 ID (`/models` 응답 중 하나) |
| `api_key` | string | ✓ | 해당 모델 공급자의 API 키 (Anthropic / Google / OpenAI) |
| `callback_url` | string | — | 완료/실패 시 백엔드가 POST할 웹훅 URL (선택) |

응답 `201`:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "total_pages": 28,
  "model": "gpt-5.4-mini",
  "created_at": "2026-04-29T05:30:00+00:00"
}
```

```bash
# 기본 (폴링으로 완료 확인)
curl -X POST http://localhost:9007/jobs \
  -F "file=@강의자료.pdf" \
  -F "model=gpt-5.4-mini" \
  -F "api_key=sk-proj-..."

# 웹훅 사용 (완료 시 내 서버로 알림)
curl -X POST http://localhost:9007/jobs \
  -F "file=@강의자료.pdf" \
  -F "model=gpt-5.4-mini" \
  -F "api_key=sk-proj-..." \
  -F "callback_url=https://my-server.com/notify"
```

#### `GET /jobs/{job_id}` — 상태 폴링

```json
{
  "job_id": "550e...", "status": "processing", "model": "gemini-2-5-flash",
  "total_pages": 28, "processed_pages": 12, "progress_pct": 43,
  "current_step": "analyzing_page", "current_page": 12,
  "started_at": "2026-04-29T05:30:05+00:00", "finished_at": null, "error": null
}
```

`status`: `queued` → `processing` → `done` | `failed`. `current_step`은 [§2.1](#21-2-pass-파이프라인) 참고.

#### `GET /jobs/{job_id}/download` — 결과 ZIP

`status == "done"`일 때만. `Content-Disposition: attachment; filename="<원본PDF명>.zip"` (한글/공백은 RFC 5987 `filename*=utf-8''…` 추가).

#### `GET /jobs/{job_id}/content` — `content.md`만

미리보기용 편의 엔드포인트. `text/markdown; charset=utf-8`로 응답.

#### `GET /jobs/{job_id}/images/{filename}` — 개별 이미지

경로 traversal 방지를 위해 `..`, `/`, `\` 포함 시 `400 INVALID_FILENAME`.

#### `DELETE /jobs/{job_id}` — 작업 + 디스크 정리

`204 No Content`. 인메모리 메타와 `uploads/{id}` / `outputs/{id}` 폴더를 함께 삭제합니다.

### 백엔드 단독 사용 (프론트 없이 API 직접 호출)

프론트엔드 없이 백엔드만 사용할 수 있습니다. `.env` 파일이 없어도 서버가 기동되며, API 키는 요청마다 `api_key` 필드로 전달합니다.

#### 1) 서버 기동

```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 9007
```

#### 2) 완료 확인 방법 선택

**방법 A — 폴링** (주기적으로 상태 확인)

```bash
# 작업 생성
JOB_ID=$(curl -s -X POST http://localhost:9007/jobs \
  -F "file=@강의자료.pdf" \
  -F "model=gpt-5.4-mini" \
  -F "api_key=sk-proj-..." \
  | python -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

# 완료될 때까지 5초 간격으로 폴링
while true; do
  RESP=$(curl -s http://localhost:9007/jobs/$JOB_ID)
  STATUS=$(echo $RESP | python -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo $RESP
  [ "$STATUS" = "done" ] || [ "$STATUS" = "failed" ] && break
  sleep 5
done

# 결과 다운로드
curl -OJ http://localhost:9007/jobs/$JOB_ID/download
```

**방법 B — 웹훅** (완료 시 내 서버로 알림)

```python
import requests

r = requests.post("http://localhost:9007/jobs",
    files={"file": ("강의자료.pdf", open("강의자료.pdf","rb"), "application/pdf")},
    data={
        "model": "gpt-5.4-mini",
        "api_key": "sk-proj-...",
        "callback_url": "https://my-server.com/notify",  # 완료 시 여기로 POST
    }
)
job_id = r.json()["job_id"]
```

완료 시 `callback_url`로 전달되는 페이로드:

```json
// 성공
{"job_id": "550e...", "status": "done"}

// 실패
{"job_id": "550e...", "status": "failed", "error": {"code": "LLM_API_ERROR", "message": "..."}}
```

> 웹훅은 **best-effort** — 전송 실패 시 재시도 없이 로그만 기록합니다. 중요한 완료 처리는 폴링을 병행하거나 `GET /jobs/{id}`로 최종 확인하세요.

## 9. 모델 비교

`backend/tests/golden/deepco_kdc_18/input.pdf` (28페이지 한국어 강의 슬라이드) 기준:

| 모델 | 처리 시간 | 분류 정확도 | PDF당 비용 (대략) | 비고 |
|---|---|---|---|---|
| Claude Haiku 4.5 | ~3분 | 100% (28/28) | $0.20 | 한국어/안정성 균형 |
| Gemini 2.5 Flash | ~2분 | 100% (28/28) | $0.10 | 최저 비용 |
| Gemini 3 Flash | ~1.5분 | 100% (28/28) | $0.20 | 속도 약 2배 / 복잡 다이어그램 강세 |
| GPT-5 mini | 측정 예정 | 측정 예정 | $0.30 | GPT-5 시리즈 검증된 비전 + 추론 |
| GPT-5.4 mini | ~2분 17초 | 100% (28/28) | $0.45 | 비전·추론 강세, 다이어그램에 유리 |

> 비용은 추정치이며, 페이지 수 / 텍스트 길이 / 이미지 해상도에 따라 변합니다. 현재 frontend 초기 선택은 **GPT-5 mini**.

## 10. 개발

### 10.1 백엔드 테스트

```bash
cd backend
python -m pytest -q              # 전체 100개
python -m pytest tests/test_runner.py -v
python -m pytest -m llm_eval     # 실제 LLM API를 치는 테스트 (수동)
```

테스트 카테고리 (대표):

| 파일 | 무엇을 다루나 |
|---|---|
| `test_pdf_io.py` | 검증, 래스터화, 텍스트 추출 |
| `test_models.py` | Pydantic 검증 (BBox 순서, image_region/classification 일관성) |
| `test_crop.py` | bbox(0–1000) → 픽셀 변환 / PNG 저장 |
| `test_mosaic.py` | 6×5 썸네일 모자이크 빌더 |
| `test_packager.py` | content.md 조립 / ZIP |
| `test_schemas.py` | Pydantic → Gemini OpenAPI 변환 (`$ref` 인라인, `nullable`, types 대문자, 미지원 키 strip) |
| `test_provider_patch.py` | LLM 출력 페이로드 보정 (bbox 클램핑, orphan caption strip 등) |
| `test_provider_factory.py` | enabled 플래그, 모델 ID 라우팅 |
| `test_claude_provider.py` / `test_gemini_provider.py` | SDK 호출 mocking |
| `test_lecture_pass.py` | Pass 1 retry / 검증 |
| `test_runner.py` | end-to-end (LLM mock) |
| `test_api.py` | FastAPI TestClient (라이프사이클 / path-traversal / 잘못된 모델 등) |

### 10.2 프론트엔드 빌드

```bash
cd frontend
npm run type-check    # tsc --noEmit
npm run lint          # next lint (eslint-config-next)
npm run build         # next build (운영용 빌드 검증)
```

### 10.3 골든 데이터셋 평가

```bash
cd backend
python tests/eval_classification.py path/to/output_dir
```

`tests/golden/deepco_kdc_18/expected.json`과 분류 결과를 비교합니다.

### 10.4 토큰 사용량 + 비용 로그

각 PDF 처리가 끝나면 `<DATA_DIR>/logs/usage.log`에 JSONL 한 줄이 추가됩니다. 모델별 비용 추적, 평균 토큰 사용량 분석, 작업별 비용 추정에 활용하세요.

```jsonl
{"ts":"2026-04-29T15:21:30+00:00","job_id":"550e...","pdf":"강의자료.pdf","model":"gpt-5.4-mini","input_tokens":169349,"output_tokens":11412,"total_tokens":180761,"pages":28,"input_cost_usd":0.127012,"output_cost_usd":0.051354,"total_cost_usd":0.178366,"ok":true}
{"ts":"2026-04-29T15:30:11+00:00","job_id":"abc1...","pdf":"broken.pdf","model":"gemini-3-flash","input_tokens":2400,"output_tokens":0,"total_tokens":2400,"pages":0,"input_cost_usd":0.0012,"output_cost_usd":0.0,"total_cost_usd":0.0012,"ok":false,"error":"LLMSchemaValidationError: ..."}
```

**기록 필드**

- `pdf` — 사용자가 업로드한 **원본 파일명** (백엔드의 임시 `input.pdf`가 아님)
- `job_id` — outputs/uploads 디렉토리와 매칭되는 작업 ID
- `model`, `input_tokens`, `output_tokens`, `total_tokens`, `pages`
- `input_cost_usd`, `output_cost_usd`, `total_cost_usd` — vendor 가격표 기반 USD 추정치 (소수점 6자리 반올림)
- `ok` — 성공/실패. 실패 시 `error` 필드 추가

**가격표** (USD per 1M tokens, 2026-04 기준 — `app/pipeline/usage_log.py`의 `MODEL_PRICES_USD_PER_M`이 단일 출처)

| 모델 | Input | Output |
|---|---|---|
| `claude-haiku-4-5` | $1.00 | $5.00 |
| `gemini-2-5-flash` | $0.30 | $2.50 |
| `gemini-3-flash` | $0.50 | $3.00 |
| `gpt-5-mini` | $0.25 | $2.00 |
| `gpt-5.4-mini` | $0.75 | $4.50 |

**SDK별 토큰 추출** — Anthropic `usage.input_tokens` / `usage.output_tokens`, Google `usage_metadata.{prompt,candidates}_token_count`, OpenAI `usage.{prompt,completion}_tokens`.

**집계 예시 (jq)**

```bash
# 모델별 누적 비용
jq -s 'group_by(.model) | map({model:.[0].model, total_cost_usd: (map(.total_cost_usd // 0) | add)})' data/logs/usage.log

# 가장 비싸게 처리된 PDF 5개
jq -s 'sort_by(-.total_cost_usd)[0:5] | map({pdf,model,total_cost_usd})' data/logs/usage.log
```

**CLI 종료 시 stderr에도** `tokens: input=... output=... total=...` 와 `cost: ~$0.1784 USD` 가 한 줄 표시됩니다.

## 11. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| `MODEL_NOT_AVAILABLE` 또는 `api_key is required` 오류 | `POST /jobs` 시 `api_key` 필드가 비어 있거나 누락된 경우. 해당 모델 공급자의 API 키를 `api_key` 필드로 전달하세요 |
| `ModuleNotFoundError: No module named 'google.api_core'` (또는 다른 빠진 모듈) | 의존성이 동기화되지 않았습니다. `start_server.bat`을 다시 실행하면 `pip install -e .`이 자동으로 빠진 패키지를 설치합니다. 수동으로 하려면 `cd backend && python -m pip install -e .` |
| `git pull` 후 의존성 누락 에러 | 누군가 `pyproject.toml`이나 `package.json`을 갱신했을 때 발생. `start_server.bat`이 매 실행마다 `pip install -e .` + `npm install`을 돌려 자동 동기화하므로 그냥 다시 실행하면 됩니다 |
| `/health`의 `data_dir`이 `\data` 또는 `D:\data`처럼 이상함 | `.env`에 `DATA_DIR=/data`처럼 절대 루트가 들어간 경우. `DATA_DIR=./data`로 바꾸세요 (상대 경로는 프로젝트 루트 기준으로 자동 해석됨) |
| 포트 9007/9017이 이미 사용 중 | (Win) `Get-NetTCPConnection -LocalPort 9007 -State Listen` 후 `Stop-Process -Id <PID>`. (\*nix) `lsof -i :9007` 후 `kill <PID>` |
| `MODEL_NOT_AVAILABLE` 응답 | 해당 모델 키가 `.env`에 없음. `/models`로 enabled 모델 확인 |
| 업로드 성공 후 `failed` 즉시 발생 | 백엔드 로그를 보세요. 자주: `LLM_API_ERROR` (네트워크/쿼터), `CONTEXT_EXTRACTION_FAILED` (Pass 1 검증 3회 실패) |
| Gemini가 `MAX_TOKENS`로 응답 절단 | 큰 페이지에서 가끔 발생. `providers/gemini.py`의 `_MAX_OUTPUT_TOKENS_BY_VARIANT`(현재 65,536) 상향 |
| 한글/공백 파일명이 다운로드 시 깨짐 | Starlette `FileResponse`가 자동으로 RFC 5987 인코딩을 추가합니다. 깨진다면 사용 중인 다운로드 도우미(curl 등)의 문제일 수 있음 |
| 처리 중 페이지 닫음 → 작업 사라짐 | `BackgroundTasks`라 서버가 안 죽으면 작업은 계속 진행됩니다. 다만 **인메모리** 큐라 서버를 재시작하면 메타가 사라집니다 (디스크 ZIP은 남음) |
| Windows에서 한글 콘솔 깨짐 | UTF-8 코드페이지: `chcp 65001` 또는 PowerShell에서 `[Console]::OutputEncoding = [Text.UTF8Encoding]::new()` |

## 12. 한계 / 비목표

이 도구가 **하지 않는 것** (의도적):

- ❌ **다중 사용자 / 인증** — 로컬 1인용. job_id를 알면 누구나 결과를 받을 수 있음 (UUID v4라 사실상 안전하지만 외부 공개 환경에는 부적합)
- ❌ **OCR 폴백** — 텍스트 레이어가 없는 스캔 PDF는 LLM Vision에만 의존. 결과 품질 낮을 수 있음
- ❌ **영속 큐 / 재기동 후 작업 복원** — 인메모리. 서버 재시작 시 진행 중 작업의 메타 사라짐
- ❌ **결과 자동 정리** — `RESULT_TTL_SECONDS`는 메타값일 뿐. 현재는 수동 `DELETE /jobs/{id}` 또는 디스크 정리 필요
- ❌ **Docker / 클라우드 배포** — 로컬 개발 가정. 배포가 필요하면 [docs/INFRA.md](docs/INFRA.md) 참고
- ❌ **모바일 / 다크모드 / i18n / 접근성 강화** — 데스크톱 한국어 기본
- ⚠️ **강의 슬라이드 외 PDF**는 *동작은 하지만* 분류 체계 (`cover` / `section_divider` / `content` / `decorative_only`)와 Pass 1의 LectureContext가 슬라이드 가정에 맞춰져 있어 논문/리포트/매뉴얼 등에서는 결과 품질이 낮을 수 있습니다. 다양한 PDF 종류 지원은 로드맵에 있음

## 13. 로드맵

- [x] M0 — 저장소 골격 / 골든 정답 / 환경 점검
- [x] M1.a — Claude Haiku 4.5 단일 2-pass 파이프라인 (28페이지 100%)
- [x] M1.b — Gemini 2.5 / 3 Flash 어댑터 + Pydantic→OpenAPI 스키마 변환기
- [x] M1.c — Pass 1 (LectureContext) 실 LLM 호출 + retry/검증
- [x] M2 — FastAPI + BackgroundTasks 단일 프로세스 백엔드 (Redis/RQ/Docker 없음)
- [x] M3 — Next.js 프론트엔드 (다중 PDF 큐, 자동 연속 처리)
- [ ] **M4** — 결과 자동 정리(`RESULT_TTL_SECONDS` 강제) + 더 나은 manual E2E 워크플로
- [ ] 다양한 PDF 종류 지원 (문서 타입 자동 감지 + 분기 프롬프트)
- [ ] 페이지 단위 부분 실패 처리 (한 페이지 실패해도 나머지로 ZIP 생성)
- [ ] Docker Compose 옵션 (배포가 필요해질 경우)
- [ ] 영어 슬라이드 PDF 지원
- [ ] 슬라이드별 결과 미리보기 카드 (드래그로 bbox 수정)

자세한 로드맵은 [docs/ROADMAP.md](docs/ROADMAP.md). 설계 문서 전체는 [docs/](docs/) 폴더 참조.

## 14. 라이선스

내부/개인 도구로 작성됨. 명시된 라이선스 없음 — 외부 공개 사용 시 별도 합의 필요.

---

### 만든 사람

- 디자인 / 구현: badasan@ubion.co.kr


