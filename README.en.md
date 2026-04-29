# PDF Slide Extractor (`pdftomd`)

[한국어](README.md) · **English**

A local single-user web tool that uses LLM Vision to convert PDFs (primarily lecture slides) into **self-contained markdown + cropped images**. The output is structured so that the markdown alone — with no images — already conveys the lesson, by translating the meaning of diagrams, tables, boxes, and arrows into prose.

- 🧠 **2-pass pipeline**: ① extract lecture-wide context (topic, key terms, slide outline) → ② per-page markdown + image-region decisions
- 🔌 **5 models**: `claude-haiku-4-5` (Anthropic), `gemini-2-5-flash`, `gemini-3-flash` (Google), `gpt-5-mini`, `gpt-5.4-mini` (OpenAI)
- 🖥️ **Single-process backend**: FastAPI + `BackgroundTasks`. No Redis, no Docker, no separate worker
- 🧩 **Multi-PDF queue**: drag-and-drop several PDFs → fully serial, auto-continuous processing
- ✅ **100 tests** (`pytest`), 100% classification accuracy verified on a 28-page golden PDF

## Table of contents

1. [What you get (input/output)](#1-what-you-get-inputoutput)
2. [How it works](#2-how-it-works)
3. [Directory layout](#3-directory-layout)
4. [Requirements](#4-requirements)
5. [Install + run](#5-install--run)
6. [Environment variables](#6-environment-variables)
7. [CLI](#7-cli)
8. [REST API](#8-rest-api)
9. [Model comparison](#9-model-comparison)
10. [Development](#10-development)
11. [Troubleshooting](#11-troubleshooting)
12. [Limitations / non-goals](#12-limitations--non-goals)
13. [Roadmap](#13-roadmap)
14. [License](#14-license)

---

## 1. What you get (input/output)

**Input**: one PDF (≤100MB / ≤100 pages per file). Filenames with Korean characters or spaces are fine.

**Output**: one ZIP. When unpacked:

```
result.zip
├── content.md          # markdown stitched together in page order
└── images/
    ├── 06_data-analysis-model.png
    ├── 11_open-data-portal.png
    └── ...
```

Example `content.md`:

```markdown
# Intro to Data Science — Session 18

> **Key terms**: open data, OpenAPI, JSON, visualization

## 6. What is a data analysis model?

A data analysis model is …(diagram contents narrated as prose)…

![Data analysis model diagram](images/06_data-analysis-model.png)
*Figure: input → preprocessing → model → output flow*

## 8. Exploring open data
...
```

**Core principle**: feeding only the markdown into a RAG / fine-tuning index should already cover the lesson. Images are *visual references*, not the source of truth.

The LLM classifies each page into one of four categories:

| Class | How it's handled |
|---|---|
| `content` | Body slide. Generates markdown + (when useful) crops an image region |
| `section_divider` | Section break ("Today's lesson", etc.) → keeps an H2 title only |
| `cover` | Title / closing page → omitted from the markdown |
| `decorative_only` | Page with only decorative illustrations → keeps text, no image crop |

## 2. How it works

### 2.1 The 2-pass pipeline

```
   PDF input
      │
      ▼
[1] Validate (≤100MB, ≤100p) ─ pdfplumber + PyMuPDF
[2] Rasterize pages (150 DPI PNG) ─ PyMuPDF/fitz
[3] Per-page text extraction ─ pdfplumber
      │
      ▼
[4] ★ Pass 1: extract lecture-wide context (1 LLM call)
      • One 6×5 thumbnail mosaic (8000px max) ─ Pillow
      • Concatenated per-page text (trimmed to 1000 chars/page)
      • Output: LectureContext { title, topic_summary, slide_outline[], key_terms[], domain_hints }
      • Strict mode — on validation failure, retry 3× with exponential backoff;
        if all retries fail, the whole job fails
      │
      ▼
[5] ★ Pass 2: per-page analysis (1 LLM call per page)
      • Inputs: system prompt + LectureContext summary + page PNG + page text
      • Output: PageAnalysis { classification, title, markdown_body,
                               image_region?, image_caption?, reasoning }
      │
      ▼
[6] For 'content' pages with image_region, PIL crops → images/<n>_<slug>.png
[7] Assemble content.md (page order) and package result.zip
```

**Progress mapping**: `validating(0–2%) → rasterizing(2–3%) → extracting_text(3–4%) → extracting_context(4–5%) → analyzing_page(5–95%) → cropping(95–98%) → packaging(98–100%)`

### 2.2 LLM adapters

A single `LLMProvider` Protocol papers over the differences between the SDKs.

| Model | SDK | Structured output | Notes |
|---|---|---|---|
| Claude Haiku 4.5 | `anthropic` | **Tool Use** (`tools=[{input_schema:...}]`) | Balanced Korean / stability |
| Gemini 2.5 Flash | `google-genai` | **`response_schema`** (OpenAPI subset) | Cheapest |
| Gemini 3 Flash | `google-genai` | **`response_schema`** | ~2× faster |
| GPT-5.4 mini | `openai` | **Strict JSON Schema** (`response_format`) | Strong vision + reasoning; great with diagrams |

A Pydantic-JSON-Schema → Gemini-OpenAPI-Schema converter (`providers/schemas.py`) inlines `$ref`, turns `Optional[X]` into `nullable: true`, uppercases types, and strips unsupported keys.

`patch_page_analysis_payload()` cleans up small violations the models tend to produce (missing `page_num`, bbox coordinates outside [0,1000], `image_region` filled in for a `decorative_only` page, `image_caption` set without an `image_region`, etc.).

### 2.3 Job queue (single process)

- When the API receives a PDF it stores it under `uploads/{job_id}/input.pdf` and dispatches the pipeline immediately via `BackgroundTasks`.
- Job state lives in an in-memory `InMemoryJobStore` (protected by a thread lock) — it is wiped on server restart.
- Result artifacts go to `outputs/{job_id}/` as `content.md`, `images/`, and `result.zip`.
- The frontend polls every second and, the moment a job finishes, automatically starts the next PDF (fully serial).

> ⚠️ The in-memory queue assumes a single user. Restarting the server drops in-progress job metadata (the result ZIP on disk survives). For multi-user / persistent queues see [§13 Roadmap](#13-roadmap).

## 3. Directory layout

```
pdftomd/
├── README.md                    ← Korean version (primary)
├── README.en.md                 ← this document
├── .env.example                 ← environment variable template
├── docs/                        ← design docs (PRD / ARCHITECTURE / API / DATA_MODEL / FRONTEND / LLM_PROMPTS / INFRA / ROADMAP / TESTING)
│
├── backend/
│   ├── pyproject.toml
│   └── app/
│       ├── main.py              ← FastAPI entry (CORS, exception mappers)
│       ├── cli.py               ← Standalone CLI: python -m app.cli <pdf>
│       ├── api/
│       │   ├── jobs.py          ← POST /jobs, GET /jobs/{id}, /download, /content, /images/{file}, DELETE
│       │   ├── models.py        ← GET /models
│       │   ├── health.py        ← GET /health
│       │   ├── worker.py        ← run_pipeline_job (BackgroundTasks function)
│       │   └── errors.py
│       ├── core/
│       │   ├── config.py        ← Pydantic Settings (.env loader, data_dir resolution)
│       │   └── job_store.py     ← InMemoryJobStore (threading.Lock)
│       ├── models/              ← Pydantic
│       │   ├── job.py           ← Job, JobStatus, JobStep, JobError
│       │   ├── page_analysis.py ← Pass 2 output
│       │   └── lecture_context.py ← Pass 1 output
│       └── pipeline/
│           ├── runner.py        ← full pipeline entry
│           ├── pdf_io.py        ← validate / rasterize / extract_text
│           ├── mosaic.py        ← Pass 1 thumbnail mosaic (PIL)
│           ├── lecture_pass.py  ← Pass 1 call + retry/validation
│           ├── crop.py          ← bbox(0–1000) → PNG
│           ├── packager.py      ← assemble content.md + ZIP
│           ├── prompts.py       ← system / user prompts (model-agnostic)
│           └── providers/
│               ├── base.py      ← LLMProvider Protocol, ProviderInfo, payload patcher
│               ├── claude.py    ← ClaudeHaikuProvider (Tool Use)
│               ├── gemini.py    ← GeminiProvider (variant=2-5/3)
│               ├── schemas.py   ← Pydantic JSON Schema → Gemini OpenAPI
│               └── registry.py  ← model id ↔ display_name ↔ enabled
│
├── frontend/
│   ├── package.json             ← Next 14, React 18, Tailwind 3, react-dropzone
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── next.config.mjs
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── globals.css
│   │   ├── page.tsx             ← upload + queue + model picker + auto-continue
│   │   └── jobs/[id]/page.tsx   ← detail: queued/processing/done/failed in one route
│   ├── components/
│   │   ├── FileDropzone.tsx     ← multi-PDF drop (react-dropzone)
│   │   ├── ModelSelector.tsx    ← radio + disabled / beta labels
│   │   ├── ProgressBar.tsx
│   │   ├── QueueItem.tsx        ← per-queue card (pending/uploading/running/done/failed)
│   │   ├── DownloadButton.tsx
│   │   ├── ModelBadge.tsx
│   │   ├── ErrorBox.tsx
│   │   └── MarkdownPreview.tsx  ← inline preview on the /jobs/[id] done state
│   └── lib/
│       ├── api.ts               ← listModels / uploadPdf / getJob / getJobContent / deleteJob / getDownloadUrl / getImageUrl
│       ├── usePolling.ts        ← 1-second polling hook for /jobs/[id]
│       ├── types.ts             ← API response types + ApiError
│       └── format.ts            ← stepLabel, ETA, formatBytes
│
└── data/                        ← runtime (gitignored)
    ├── uploads/{job_id}/input.pdf
    └── outputs/{job_id}/
        ├── content.md
        ├── images/
        └── result.zip
```

## 4. Requirements

| Item | Version |
|---|---|
| Python | **3.11+** |
| Node.js | **20+** (npm 10+) |
| OS | Windows 10/11, macOS, Linux all work the same |
| LLM API key | **`ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` — at least one** |

> Docker and Redis are not required. PDF rasterization goes through **PyMuPDF**, so there is no poppler / pdftoppm system dependency either.

## 5. Install + run

### 5.1 Clone

```bash
git clone https://github.com/<owner>/pdftomd.git
cd pdftomd
```

### 5.2 Configure environment

```bash
cp .env.example .env
# Open .env and fill in at least one of ANTHROPIC_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY
```

See [§6 Environment variables](#6-environment-variables) for every option.

### 5.3 ⭐ Windows: launch with one double-click (recommended)

Easiest path. This is what we ship to non-developer coworkers.

Double-click `start_server.bat` and it will:

1. If 9007 / 9017 are already in use, print the offending PID and the `taskkill` command, then exit and ask the user to re-run
2. On first launch, install backend / frontend dependencies (`pip install -e .` + `npm install`)
3. Start the backend (9007) in its own console window and wait for `/health` to respond
4. Start the frontend (9017) in another console window and wait for it to respond
5. Open http://localhost:9017 in the default browser
6. The launcher window closes itself after 5 seconds; the backend / frontend windows stay up

To stop, double-click `stop_server.bat` (or simply close the backend / frontend console windows).

> **Deployment note**: the bat anchors itself with `%~dp0` so it works no matter which drive or folder it sits in (spaces and Korean characters in the path are fine). **Pre-reqs**: Python 3.11+ and Node 20+ on PATH, and a `.env` at the project root (copy `.env.example` and fill in a key).
>
> **Encoding note**: messages are ASCII-only on purpose. `chcp 65001` (UTF-8) is *not* used because it is known to break the cmd interpreter on some Windows 10 builds. Korean folder names may render as mojibake if they appear in error messages, but the script itself works end-to-end.

### 5.4 Manual run (for development / macOS / Linux)

#### Backend (port 9007)

```bash
cd backend
python -m venv .venv
# Windows (Git Bash):
source .venv/Scripts/activate
# macOS/Linux:
# source .venv/bin/activate

pip install -e .[dev]

# Start the server
python -m uvicorn app.main:app --host 127.0.0.1 --port 9007 --reload
```

**Verify**: visit http://127.0.0.1:9007/health → `{"status":"ok", ...}`

#### Frontend (port 9017)

In a new terminal:

```bash
cd frontend
npm install
npm run dev
```

**Verify**: open http://localhost:9017 in a browser. You should see the upload screen.

### 5.5 Use it

1. Drag PDFs onto the dropzone (multiple files supported — Korean / spaces in filenames OK)
2. Pick an analysis model (default: Gemini 2.5 Flash)
3. Click **추출 시작** (Start extraction) → the queue is processed one at a time, automatically
4. Each item sprouts a **📥 ZIP 다운로드** button when it completes
5. The downloaded ZIP keeps the original PDF's basename (e.g. `lecture.pdf` → `lecture.zip`)

> 💡 You can drop more PDFs while a run is in progress; they get appended to the queue. If you close the tab the backend keeps working — bookmark `/jobs/{id}` to come back and grab the result (until the server restarts).

## 6. Environment variables

Place `.env` at the project root (`pdftomd/`). The backend will find it automatically.

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | ◐ | — | If empty, `claude-haiku-4-5` is disabled in the UI |
| `GEMINI_API_KEY` | ◐ | — | If empty, `gemini-2-5-flash` / `gemini-3-flash` are disabled |
| `OPENAI_API_KEY` | ◐ | — | If empty, `gpt-5.4-mini` is disabled |
| `MAX_PDF_SIZE_MB` | × | `100` | Upload size limit (MB) |
| `MAX_PDF_PAGES` | × | `100` | Page count limit |
| `RESULT_TTL_SECONDS` | × | `3600` | Result retention seconds — currently informational; auto-cleanup is unimplemented |
| `RENDER_DPI` | × | `150` | Pass 2 page rasterization DPI |
| `DATA_DIR` | × | `./data` | Root for uploads/outputs. **Relative paths resolve to the project root**, not CWD |
| `BACKEND_PORT` | × | `9007` | Informational (pass to uvicorn explicitly) |
| `FRONTEND_PORT` | × | `9017` | Informational (hard-coded in `package.json` scripts) |
| `CORS_ORIGINS` | × | `http://localhost:9017` | Comma-separated allowed origins |

**◐ = at least one of these is required**. With all empty the backend refuses to start with:

```
RuntimeError: No LLM API key configured. Set ANTHROPIC_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY in environment / .env.
```

### Frontend

`frontend/.env.local` (optional):

```
NEXT_PUBLIC_API_BASE=http://localhost:9007
```

Defaults to `http://localhost:9007` when unset.

> 🔒 Both `.env` and `frontend/.env.local` are gitignored — never commit them. If a key leaks, rotate it (revoke + reissue) immediately.

## 7. CLI

To process a single PDF without the UI:

```bash
cd backend
python -m app.cli path/to/input.pdf -o ./out --model claude-haiku-4-5
```

**Flags**:

| Flag | Description |
|---|---|
| `-o`, `--output-dir DIR` | Output folder (default `./out`) |
| `--model {claude-haiku-4-5,gemini-2-5-flash,gemini-3-flash,gpt-5-mini,gpt-5.4-mini}` | Model id (defaults to the first enabled one) |
| `--dpi N` | Pass 2 rasterization DPI (default: `RENDER_DPI`) |
| `--keep-pages` | Keep the temporary `pages/` directory (debugging) |
| `--list-models` | Print enabled / preview / cost table and exit |
| `-v` / `-vv` | INFO / DEBUG logging |

**Exit codes**: `0` success, `2` bad usage / missing key, `3` PDF validation failure, `4` LLM call failure, `130` Ctrl+C.

Examples:

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

Base URL: `http://localhost:9007`. All responses are JSON. Full spec at [docs/API.md](docs/API.md).

### Common error envelope

```json
{ "error": { "code": "INVALID_PDF", "message": "...", "details": null } }
```

| HTTP | code | Meaning |
|---|---|---|
| 400 | `INVALID_FILE_TYPE` | Not a PDF, or bad magic bytes |
| 400 | `FILE_TOO_LARGE` | Exceeds `MAX_PDF_SIZE_MB` |
| 400 | `TOO_MANY_PAGES` | Exceeds `MAX_PDF_PAGES` |
| 400 | `INVALID_MODEL` | Unknown model id |
| 400 | `MODEL_NOT_AVAILABLE` | API key for that model is not configured |
| 400 | `INVALID_FILENAME` | Image path contains `..`, `/`, or `\` |
| 404 | `JOB_NOT_FOUND` | No such job_id (or it was deleted) |
| 404 | `RESULT_NOT_READY` | Job hasn't reached `done` yet |
| 404 | `IMAGE_NOT_FOUND` | Requested image is not in outputs/<id>/images |
| 500 | `INTERNAL_ERROR` | Uncaught exception |
| 500 | `CONTEXT_EXTRACTION_FAILED` | Pass 1 failed after 3 retries |
| 502 | `LLM_API_ERROR` | LLM call failed outright |

### Endpoints

#### `GET /health`

```json
{ "status": "ok", "data_dir": "D:\\pdftomd\\data", "active_jobs": 0 }
```

#### `GET /models`

Only models with a configured key have `enabled: true`.

```json
{ "models": [
  { "id": "claude-haiku-4-5", "display_name": "Claude Haiku 4.5", "provider": "anthropic",
    "is_preview": false, "enabled": true, "estimated_cost_per_pdf_usd": 0.20,
    "notes": "Balanced Korean / stability. Solid vision." },
  { "id": "gemini-2-5-flash", "display_name": "Gemini 2.5 Flash", "provider": "google",
    "is_preview": false, "enabled": true, "estimated_cost_per_pdf_usd": 0.10,
    "notes": "Cheapest. Good Korean support." },
  { "id": "gemini-3-flash", "display_name": "Gemini 3 Flash", "provider": "google",
    "is_preview": false, "enabled": true, "estimated_cost_per_pdf_usd": 0.20,
    "notes": "~2× faster. Strong on multimodal — block code / complex diagrams." },
  { "id": "gpt-5.4-mini", "display_name": "GPT-5.4 mini", "provider": "openai",
    "is_preview": false, "enabled": true, "estimated_cost_per_pdf_usd": 0.45,
    "notes": "Strong vision + reasoning; ~2× faster than GPT-5 mini." }
]}
```

> Note: the `notes` field is currently authored in Korean; the values above are translated for clarity.

#### `POST /jobs` — create a job

`multipart/form-data`:

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | File | ✓ | PDF (UTF-8 filenames with Korean / spaces are accepted) |
| `model` | string | ✓ | model id (one of those returned by `/models`) |

Response `201`:

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
curl -X POST http://localhost:9007/jobs \
  -F "file=@lecture.pdf" \
  -F "model=gpt-5.4-mini"
```

#### `GET /jobs/{job_id}` — poll status

```json
{
  "job_id": "550e...", "status": "processing", "model": "gemini-2-5-flash",
  "total_pages": 28, "processed_pages": 12, "progress_pct": 43,
  "current_step": "analyzing_page", "current_page": 12,
  "started_at": "2026-04-29T05:30:05+00:00", "finished_at": null, "error": null
}
```

`status`: `queued` → `processing` → `done` | `failed`. See [§2.1](#21-the-2-pass-pipeline) for `current_step` values.

#### `GET /jobs/{job_id}/download` — result ZIP

Available only when `status == "done"`. `Content-Disposition: attachment; filename="<original-basename>.zip"`, with RFC 5987 `filename*=utf-8''…` added when the name contains non-ASCII characters.

#### `GET /jobs/{job_id}/content` — just `content.md`

Convenience endpoint for the preview pane. Served as `text/markdown; charset=utf-8`.

#### `GET /jobs/{job_id}/images/{filename}` — single image

Path-traversal protected: any `..`, `/`, or `\` returns `400 INVALID_FILENAME`.

#### `DELETE /jobs/{job_id}` — drop job + disk artifacts

`204 No Content`. Removes both the in-memory metadata and `uploads/{id}` / `outputs/{id}` directories.

## 9. Model comparison

Measured against `backend/tests/golden/deepco_kdc_18/input.pdf` (28-page Korean lecture deck):

| Model | Time | Classification accuracy | Approx. cost / PDF | Notes |
|---|---|---|---|---|
| Claude Haiku 4.5 | ~3 min | 100% (28/28) | $0.20 | Balanced Korean / stability |
| Gemini 2.5 Flash | ~2 min | 100% (28/28) | $0.10 | Lowest cost |
| Gemini 3 Flash | ~1.5 min | 100% (28/28) | $0.20 | ~2× faster, strong on complex diagrams |
| GPT-5 mini | TBD | TBD | $0.30 | Proven GPT-5 vision + reasoning |
| GPT-5.4 mini | TBD | TBD | $0.45 | Strong vision + reasoning, great with diagrams |

> Costs are estimates; actual spend depends on page count, text length, and image resolution. The current default in the UI is **GPT-5.4 mini**.

## 10. Development

### 10.1 Backend tests

```bash
cd backend
python -m pytest -q              # all 100
python -m pytest tests/test_runner.py -v
python -m pytest -m llm_eval     # tests that hit real LLM APIs (manual)
```

Representative test files:

| File | What it covers |
|---|---|
| `test_pdf_io.py` | Validation, rasterization, text extraction |
| `test_models.py` | Pydantic validation (BBox order, image_region/classification consistency) |
| `test_crop.py` | bbox(0–1000) → pixel conversion / PNG saving |
| `test_mosaic.py` | The 6×5 thumbnail mosaic builder |
| `test_packager.py` | content.md assembly / ZIP |
| `test_schemas.py` | Pydantic → Gemini OpenAPI conversion (`$ref` inlining, `nullable`, type uppercasing, stripping unsupported keys) |
| `test_provider_patch.py` | LLM payload patching (bbox clamping, orphan caption stripping, etc.) |
| `test_provider_factory.py` | Enabled flags, model-id routing |
| `test_claude_provider.py` / `test_gemini_provider.py` | SDK call mocking |
| `test_lecture_pass.py` | Pass 1 retry / validation |
| `test_runner.py` | End-to-end (LLM mocked) |
| `test_api.py` | FastAPI TestClient (lifecycle / path traversal / bad model id, etc.) |

### 10.2 Frontend build

```bash
cd frontend
npm run type-check    # tsc --noEmit
npm run lint          # next lint (eslint-config-next)
npm run build         # next build (production build sanity)
```

### 10.3 Golden-set evaluation

```bash
cd backend
python tests/eval_classification.py path/to/output_dir
```

Compares the classifications in your run against `tests/golden/deepco_kdc_18/expected.json`.

### 10.4 Token usage log

Every completed PDF run appends one JSONL record to `<DATA_DIR>/logs/usage.log`. Use it for cost tracking and average-tokens-per-page analysis.

```jsonl
{"ts":"2026-04-29T15:21:30+00:00","pdf":"lecture.pdf","model":"gpt-5.4-mini","input_tokens":12345,"output_tokens":6789,"total_tokens":19134,"pages":28,"ok":true}
{"ts":"2026-04-29T15:30:11+00:00","pdf":"broken.pdf","model":"gemini-3-flash","input_tokens":2400,"output_tokens":0,"total_tokens":2400,"pages":0,"ok":false,"error":"LLMSchemaValidationError: ..."}
```

- Records both successes and failures (`ok: false` plus an `error` field on failure).
- Each adapter accumulates the SDK-reported usage: Anthropic `usage.input_tokens` / `usage.output_tokens`, Google `usage_metadata.{prompt,candidates}_token_count`, OpenAI `usage.{prompt,completion}_tokens`.
- Aggregate quickly with e.g. `jq -s 'group_by(.model) | map({model:.[0].model, total:map(.total_tokens) | add})' usage.log`.
- The CLI also prints `tokens: input=... output=... total=...` to stderr at the end of a run.

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Backend dies with `RuntimeError: No LLM API key configured` | At least one of `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` must be set in `.env`. The `.env` file goes at the project root (the parent of `backend/`) |
| `ModuleNotFoundError: No module named 'google.api_core'` (or any other missing module) | Dependencies are out of sync. Re-run `start_server.bat` — it runs `pip install -e .` every time, so missing packages get installed automatically. Manual: `cd backend && python -m pip install -e .` |
| Missing dependency error after `git pull` | Someone bumped `pyproject.toml` or `package.json`. `start_server.bat` re-runs `pip install -e .` + `npm install` on every launch, so just run it again to sync |
| `/health` reports `data_dir` as `\data` or `D:\data` | Your `.env` has something like `DATA_DIR=/data`, which resolves to the drive root. Use `DATA_DIR=./data` instead — relative paths resolve against the project root |
| Ports 9007 / 9017 already in use | (Win) `Get-NetTCPConnection -LocalPort 9007 -State Listen`, then `Stop-Process -Id <PID>`. (\*nix) `lsof -i :9007`, then `kill <PID>` |
| `MODEL_NOT_AVAILABLE` response | The relevant key is missing from `.env`. Hit `/models` to see which are enabled |
| Job flips to `failed` immediately after upload | Read the backend log. Common: `LLM_API_ERROR` (network / quota), `CONTEXT_EXTRACTION_FAILED` (Pass 1 validation failed 3×) |
| Gemini truncates with `MAX_TOKENS` | Happens occasionally on dense pages. Bump `_MAX_OUTPUT_TOKENS_BY_VARIANT` in `providers/gemini.py` (currently 65,536) |
| Korean / spaces in filename mangled on download | Starlette's `FileResponse` automatically appends RFC 5987 encoding. If something still mangles it, the issue is usually in the downloader (e.g. an old curl) |
| Closed the page mid-run → job appears lost | `BackgroundTasks` keeps running while the server is up. But the queue is **in-memory** — restarting the backend wipes job metadata (the result ZIP on disk survives) |
| Korean console output is mojibake on Windows | Switch to UTF-8: `chcp 65001`, or in PowerShell `[Console]::OutputEncoding = [Text.UTF8Encoding]::new()` |

## 12. Limitations / non-goals

Things this tool **does not** do (intentionally):

- ❌ **Multi-user / authentication** — local single-user. Anyone who knows a `job_id` can fetch the result (UUID v4 makes this practically safe but unsuitable for public deployment)
- ❌ **OCR fallback** — scan-only PDFs without a text layer rely entirely on LLM Vision; quality may suffer
- ❌ **Persistent queue / restart recovery** — in-memory; restarting the server drops in-progress job metadata
- ❌ **Automatic result cleanup** — `RESULT_TTL_SECONDS` is informational only; cleanup is currently manual (`DELETE /jobs/{id}` or wiping the disk)
- ❌ **Docker / cloud deployment** — local-dev only. See [docs/INFRA.md](docs/INFRA.md) if you need it
- ❌ **Mobile / dark mode / i18n / accessibility hardening** — desktop, Korean default
- ⚠️ **PDFs other than lecture slides** *work* but the four-class taxonomy (`cover` / `section_divider` / `content` / `decorative_only`) and the `LectureContext` extracted in Pass 1 are tuned for slides. Papers / reports / manuals will produce lower-quality output. Multi-document-type support is on the roadmap.

## 13. Roadmap

- [x] M0 — Repo skeleton / golden answer / environment check
- [x] M1.a — Single-model 2-pass pipeline with Claude Haiku 4.5 (28-page 100%)
- [x] M1.b — Gemini 2.5 / 3 Flash adapters + Pydantic→OpenAPI schema converter
- [x] M1.c — Pass 1 (LectureContext) live LLM call + retry / validation
- [x] M2 — Single-process FastAPI + BackgroundTasks backend (no Redis / RQ / Docker)
- [x] M3 — Next.js frontend (multi-PDF queue, auto-continuous processing)
- [ ] **M4** — Enforce automatic cleanup of `RESULT_TTL_SECONDS` + better manual E2E workflow
- [ ] Multi-document-type support (auto-detect document kind + branched prompts)
- [ ] Graceful per-page failure handling (one bad page → ZIP with partial results)
- [ ] Optional Docker Compose (only when deployment becomes necessary)
- [ ] English-language slide PDF support
- [ ] Per-slide preview cards in the UI (drag to edit bbox)

Full plan in [docs/ROADMAP.md](docs/ROADMAP.md). All design docs are in [docs/](docs/).

## 14. License

Internal / personal tool. No license declared — please negotiate separately for any external use.

---

### Authors

- Design / implementation: 1-person dev with Claude Code (Anthropic) as a pair
- Golden dataset: Deepco KDC session 18 (28-page Korean lecture deck)
- Issues / questions: GitHub Issues
