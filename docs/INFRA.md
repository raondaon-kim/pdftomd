# INFRA — 실행 / 배포

이 도구는 **로컬 단일 프로세스**로 실행됩니다. Docker, Redis, RQ 등 외부 인프라는
사용하지 않습니다. 백그라운드 작업은 FastAPI `BackgroundTasks`로 처리하며 작업
상태는 프로세스 메모리(`InMemoryJobStore`)에만 보관합니다(서버 재시작 시 휘발).

## 1. 실행 방식

### 1.1 Windows 더블클릭 (권장)

```
start_server.bat   # backend(uvicorn) + frontend(next dev) 동시 실행
stop_server.bat    # 두 프로세스 정리
```

`start_server.bat`이 매 실행마다 하는 일:
1. `python -m venv backend/.venv` (없으면 생성)
2. `pip install -e backend` (의존성 항상 동기화 — 패키지가 추가돼도 재설치 자동)
3. `npm install` (frontend, lockfile 변경 시만 실제 설치)
4. backend는 `BACKEND_PORT`(기본 9007), frontend는 `FRONTEND_PORT`(기본 9017)

### 1.2 수동 실행

```bash
# backend
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -e .
python -m app.main                                # uvicorn 진입

# frontend (다른 터미널)
cd frontend
npm install
npm run dev
```

### 1.3 CLI (서버 없이)

```bash
cd backend
python -m app.cli path/to/lecture.pdf -o ./out --model gpt-5-mini
python -m app.cli --list-models
```

## 2. 환경 변수

### 2.1 `.env.example`

```bash
# LLM API 키 — 사용할 모델의 키만 채우면 됨 (최소 1개 필요).
# 키가 없는 모델은 /models 응답에서 enabled=false로 표시되어 UI에서 비활성화됨.
ANTHROPIC_API_KEY=          # Claude Haiku 4.5
GEMINI_API_KEY=             # Gemini 2.5 Flash, Gemini 3 Flash
OPENAI_API_KEY=             # GPT-5 mini, GPT-5.4 mini

# 선택 (기본값 있음)
DATA_DIR=./data             # 업로드/결과/로그 루트 (프로젝트 루트 기준 상대경로 OK)
MAX_PDF_SIZE_MB=100
MAX_PDF_PAGES=100
RESULT_TTL_SECONDS=3600
RENDER_DPI=150
BACKEND_PORT=9007
FRONTEND_PORT=9017
CORS_ORIGINS=http://localhost:9017
```

### 2.2 변수 명세

| 변수 | 기본 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | - | Claude Haiku 4.5 활성화 |
| `GEMINI_API_KEY` | - | Gemini 2.5/3 Flash 활성화 |
| `OPENAI_API_KEY` | - | GPT-5 mini / GPT-5.4 mini 활성화 |
| (셋 다 없으면) | - | `validate_at_startup`에서 `RuntimeError` |
| `DATA_DIR` | `<project_root>/data` | 상대경로는 프로젝트 루트 기준으로 해석 |
| `MAX_PDF_SIZE_MB` | `100` | 업로드 PDF 최대 크기 |
| `MAX_PDF_PAGES` | `100` | 처리할 최대 페이지 수 |
| `RESULT_TTL_SECONDS` | `3600` | 결과 보존 시간 (정리 작업 미구현, 수동) |
| `RENDER_DPI` | `150` | 페이지 렌더링 DPI |
| `BACKEND_PORT` | `9007` | uvicorn 포트 |
| `FRONTEND_PORT` | `9017` | Next.js dev 서버 포트 |
| `CORS_ORIGINS` | `http://localhost:9017` | CORS 허용 도메인(콤마 구분) |

### 2.3 부팅 시 키 검증

`Settings.validate_at_startup`이 부팅 시 한 번 호출됩니다
(`backend/app/core/config.py`):

```python
def validate_at_startup(self) -> None:
    if not (self.anthropic_api_key or self.gemini_api_key or self.openai_api_key):
        raise RuntimeError(
            "No LLM API key configured. "
            "Set ANTHROPIC_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY in environment / .env."
        )
```

키가 있는 모델만 `GET /models` 응답에서 `enabled: true`로 표시되며, UI는 키 없는
모델을 회색 처리합니다. CLI는 `--model`을 생략하면 `enabled: true`인 첫 모델을
자동 선택합니다.

## 3. 디스크 레이아웃

```
<DATA_DIR>/
├── uploads/
│   └── {job_id}/input.pdf          # 사용자 업로드 PDF (안정적인 on-disk 이름)
├── outputs/
│   └── {job_id}/
│       ├── pages/                   # 임시 렌더링 PNG (작업 직후 삭제)
│       ├── images/                  # 최종 크롭 이미지
│       ├── content.md
│       └── result.zip
└── logs/
    └── usage.log                    # JSONL 누적 로그 (DATA_MODEL.md §3 참조)
```

`DATA_DIR`이 상대경로(`./data` 등)면 프로세스 작업 디렉토리가 아닌
**프로젝트 루트**(즉 `backend/` 의 부모) 기준으로 해석됩니다 — `python -m app.main`을
어느 위치에서 띄워도 같은 데이터 디렉토리를 봅니다.

## 4. 리소스 권장 사양

개인 PC에서 단일 사용자로 실행하는 기준:

| 컴포넌트 | RAM | CPU |
|---|---|---|
| backend (uvicorn) | 200~400MB 평상시 / 1~2GB 처리 중 | 0.5~1 core |
| frontend (next dev) | 200~400MB | 0.1~0.3 core |
| **합계** | **~3GB** | **~2 cores** |

## 5. 외부 의존성

| 의존 | 종류 | 장애 시 영향 |
|---|---|---|
| Anthropic API | 외부 (Claude 모델 사용 시) | Claude 모델 작업 멈춤. Gemini/OpenAI 영향 없음 |
| Google Gemini API | 외부 (Gemini 모델 사용 시) | Gemini 모델 작업 멈춤. 다른 vendor 영향 없음 |
| OpenAI API | 외부 (GPT 모델 사용 시) | GPT 모델 작업 멈춤. 다른 vendor 영향 없음 |
| poppler-utils (`pdfinfo`, `pdftoppm`, `pdftotext`) | 시스템 바이너리 | PDF I/O 자체가 동작하지 않음 — `chocolatey` 또는 `apt` 등으로 설치 |
| 한글 폰트(`fonts-noto-cjk` 등) | 시스템 | 페이지 렌더링 시 한글 깨짐 |
| Internet | 필수 | LLM 호출 불가 |

## 6. 로그 / 관찰

- **uvicorn stdout**: 일반 HTTP 로그 + 파이프라인 진행 로그
  ```
  INFO:     pipeline: job 550e... page 12/28 — analyzing
  INFO:     pipeline: job 550e... page 12/28 — done (classification=content)
  ```
- **사용량 로그**: 작업 1건당 1줄, `<DATA_DIR>/logs/usage.log` JSONL
  ```json
  {"ts": "...", "job_id": "550e...", "pdf": "강의자료.pdf",
   "model": "gpt-5.4-mini", "input_tokens": 169349, "output_tokens": 11412,
   "total_tokens": 180761, "pages": 28,
   "input_cost_usd": 0.127012, "output_cost_usd": 0.051354,
   "total_cost_usd": 0.178366, "ok": true}
  ```
  (스키마와 jq 집계 예시는 [DATA_MODEL.md §3](DATA_MODEL.md) 참조)

## 7. 정리(cleanup)

`DATA_DIR/uploads/{job_id}` / `outputs/{job_id}` 는 자동 삭제되지 않습니다.
필요 시 OS 작업 스케줄러로 `RESULT_TTL_SECONDS`를 참고해 수동 정리하세요.

```powershell
# Windows 예: 1시간 지난 디렉토리 삭제
Get-ChildItem .\data\outputs -Directory |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-1) } |
    Remove-Item -Recurse -Force
```

## 8. 향후 클라우드 이전 시 변경점

(참고용. v1엔 안 함.)

| 컴포넌트 | 로컬 | 클라우드 시 |
|---|---|---|
| 작업 상태 | `InMemoryJobStore` (단일 프로세스) | Redis / Postgres |
| 백그라운드 처리 | `BackgroundTasks` | RQ / Celery / Cloud Tasks |
| 파일 저장 | 로컬 디스크 | S3 / R2 |
| Frontend | `next dev` | Vercel / Cloudflare Pages |
| Backend | `uvicorn` | Fly.io / Railway / ECS |
| Secret | `.env` | AWS Secrets Manager / Doppler |
