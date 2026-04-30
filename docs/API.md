# API — REST 명세

`http://localhost:9007` 기준 (포트는 `BACKEND_PORT`로 변경 가능). 모든 응답은 JSON.

## 공통

### 에러 응답 형식

```json
{
  "error": {
    "code": "INVALID_PDF",
    "message": "업로드한 파일이 PDF 형식이 아닙니다.",
    "details": null
  }
}
```

### 에러 코드 표

| HTTP | code | 의미 |
|---|---|---|
| 400 | `INVALID_FILE_TYPE` | PDF가 아닌 파일 |
| 400 | `FILE_TOO_LARGE` | 100MB 초과 |
| 400 | `TOO_MANY_PAGES` | 100페이지 초과 |
| 404 | `JOB_NOT_FOUND` | 존재하지 않는 job_id |
| 404 | `RESULT_NOT_READY` | 작업이 아직 끝나지 않음 |
| 409 | `WORKER_BUSY` | 다른 작업 처리 중 (단일 사용자라 사실상 거의 없음) |
| 500 | `INTERNAL_ERROR` | 서버 내부 오류 |
| 500 | `CONTEXT_EXTRACTION_FAILED` | 1패스(강의 맥락 추출) 3회 재시도 후에도 실패 (strict 모드) |
| 502 | `LLM_AUTH_ERROR` | LLM API 인증 실패 (잘못된 키) |
| 502 | `LLM_API_ERROR` | LLM API 호출 실패 (네트워크/서비스 장애) |

---

## 1. POST `/jobs` — 작업 생성 (PDF 업로드)

PDF를 업로드해 처리 작업을 큐에 넣습니다.

### 요청

`multipart/form-data`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `file` | File | ✓ | PDF 파일 (≤ 100MB) |
| `model` | string | ✓ | LLM 모델 ID. `claude-haiku-4-5`, `gemini-2-5-flash`, `gemini-3-flash`, `gpt-5-mini`, `gpt-5.4-mini` 중 하나 |

선택한 모델의 API 키가 환경변수에 없으면 400 `MODEL_NOT_AVAILABLE`. 사용 가능한 모델은 `GET /models`로 사전 조회 가능.

### 응답 (201 Created)

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "total_pages": 28,
  "model": "gpt-5-mini",
  "pdf_filename": "강의자료.pdf",
  "created_at": "2026-04-28T05:30:00Z"
}
```

`pdf_filename`은 사용자가 업로드한 원본 파일명입니다 (디스크상의 stable name인
`input.pdf`가 아니라). usage 로그도 이 이름으로 기록됩니다.

### 예시 (curl)

```bash
curl -X POST http://localhost:9007/jobs \
  -F "file=@deepco_kdc_18.pdf" \
  -F "model=gpt-5-mini"
```

### 새로운 에러 코드

| HTTP | code | 의미 |
|---|---|---|
| 400 | `INVALID_MODEL` | 알 수 없는 모델 ID |
| 400 | `MODEL_NOT_AVAILABLE` | 해당 모델의 API 키가 서버에 설정되지 않음 |

---

## 2. GET `/jobs/{job_id}` — 작업 상태 조회 (폴링)

진행률 폴링용. 프론트가 1초 간격으로 호출.

### 요청

```
GET /jobs/550e8400-e29b-41d4-a716-446655440000
```

### 응답 (200 OK)

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "model": "gpt-5-mini",
  "pdf_filename": "강의자료.pdf",
  "total_pages": 28,
  "processed_pages": 12,
  "progress_pct": 43,
  "current_step": "analyzing_page",
  "current_page": 12,
  "started_at": "2026-04-28T05:30:05Z",
  "finished_at": null,
  "error": null
}
```

### `status` 값

| 값 | 의미 |
|---|---|
| `queued` | 큐에 들어감, 워커가 아직 안 집음 |
| `processing` | 워커가 처리 중 |
| `done` | 완료, 다운로드 가능 |
| `failed` | 실패 |

### `current_step` 값

| 값 | 의미 | 진행률 범위 |
|---|---|---|
| `validating` | PDF 검증 중 | 0~2% |
| `rasterizing` | 페이지 렌더링 중 | 2~3% |
| `extracting_text` | 텍스트 추출 중 | 3~4% |
| `extracting_context` | 1패스: 강의 맥락 추출 중 | 4~5% |
| `analyzing_page` | 2패스: 페이지 분석 중 (가장 오래 걸림) | 5~95% |
| `cropping` | 이미지 크롭 중 | 95~98% |
| `packaging` | ZIP 생성 중 | 98~100% |

### `error` (status=failed일 때)

```json
{
  "code": "LLM_API_ERROR",
  "message": "OpenAI API에서 응답을 받지 못했습니다.",
  "page": 7
}
```

---

## 3. GET `/jobs/{job_id}/download` — 결과 ZIP 다운로드

작업이 끝났을 때만 호출 가능.

### 요청

```
GET /jobs/550e8400-e29b-41d4-a716-446655440000/download
```

### 응답

- `Content-Type: application/zip`
- `Content-Disposition: attachment; filename="result_550e8400.zip"`
- Body: ZIP 파일 바이너리

### 응답 (404)

작업이 끝나지 않았거나 결과 파일이 만료된 경우.

```json
{
  "error": {
    "code": "RESULT_NOT_READY",
    "message": "작업이 아직 완료되지 않았거나 결과가 만료되었습니다."
  }
}
```

---

## 4. GET `/jobs/{job_id}/preview` — 결과 미리보기 (선택, v1)

ZIP을 받기 전에 슬라이드별 결과를 미리 보고 싶을 때.

### 응답 (200 OK)

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "slides": [
    {
      "page": 6,
      "title": "데이터 분석 모델이란?",
      "classification": "content",
      "markdown_body": "데이터 분석 모델은 다양한 수치 데이터를...",
      "image_url": "/jobs/550e.../images/06_데이터분석모델.png",
      "image_caption": "데이터 분석 모델의 역할과 머신러닝 작동원리"
    },
    {
      "page": 8,
      "title": "공공데이터 알아보기",
      "classification": "section_divider",
      "markdown_body": "## 공공데이터 알아보기",
      "image_url": null,
      "image_caption": null
    }
  ]
}
```

---

## 5. GET `/jobs/{job_id}/images/{filename}` — 개별 이미지 조회

미리보기 화면에서 이미지를 표시할 때.

### 응답

- `Content-Type: image/png`
- Body: PNG 바이너리

---

## 6. DELETE `/jobs/{job_id}` — 작업 삭제 (선택)

### 응답

`204 No Content`

---

## 7. GET `/models` — 사용 가능한 LLM 모델 목록

UI 드롭다운을 채우기 위해 호출. 서버에 API 키가 설정된 모델만 `enabled: true`.

### 응답 (200 OK)

```json
{
  "models": [
    {
      "id": "claude-haiku-4-5",
      "display_name": "Claude Haiku 4.5",
      "provider": "anthropic",
      "is_preview": false,
      "enabled": true,
      "estimated_cost_per_pdf_usd": 0.20,
      "notes": "한국어와 안정성 균형. 비전 양호."
    },
    {
      "id": "gemini-2-5-flash",
      "display_name": "Gemini 2.5 Flash",
      "provider": "google",
      "is_preview": false,
      "enabled": true,
      "estimated_cost_per_pdf_usd": 0.10,
      "notes": "가장 저렴. 한국어 양호."
    },
    {
      "id": "gemini-3-flash",
      "display_name": "Gemini 3 Flash",
      "provider": "google",
      "is_preview": false,
      "enabled": true,
      "estimated_cost_per_pdf_usd": 0.20,
      "notes": "속도 약 2배. 멀티모달 이해 강세 — 블록 코드/복잡 다이어그램에 유리."
    },
    {
      "id": "gpt-5-mini",
      "display_name": "GPT-5 mini",
      "provider": "openai",
      "is_preview": false,
      "enabled": true,
      "estimated_cost_per_pdf_usd": 0.30,
      "notes": "GPT-5 시리즈 mini. 비전·추론 안정적, 검증된 멀티모달."
    },
    {
      "id": "gpt-5.4-mini",
      "display_name": "GPT-5.4 mini",
      "provider": "openai",
      "is_preview": false,
      "enabled": true,
      "estimated_cost_per_pdf_usd": 0.45,
      "notes": "비전·추론 모두 강세. GPT-5 mini 대비 약 2배 빠르고 멀티모달 이해 향상."
    }
  ]
}
```

`enabled: false`인 모델은 키가 없어 사용 불가. UI는 비활성 표시 + 호버에 "환경변수 미설정" 안내.

`estimated_cost_per_pdf_usd`는 ~30페이지 PDF 기준 대략적 추정치. 실제 비용은 변동 가능.

---

## 8. GET `/health` — 헬스체크

```json
{
  "status": "ok",
  "available_models": ["claude-haiku-4-5", "gpt-5-mini", "gpt-5.4-mini"]
}
```

`available_models`는 현재 키가 설정된 모델 ID 리스트입니다. Redis/외부 큐가 없는
단일 프로세스 구조라 별도 worker 헬스 필드는 없습니다.

---

## 부록 A. 폴링 전략

- 클라이언트는 `/jobs/{id}` 를 **1초 간격**으로 폴링
- 응답에 변화가 없을 때는 폴링 유지
- `status == "done"` 또는 `status == "failed"`일 때 폴링 중단
- 사용자가 페이지를 이탈해도 작업은 계속 진행 (job_id를 URL/localStorage에 보관)

## 부록 B. CORS

dev 환경 (`CORS_ORIGINS` 기본값):
```
Access-Control-Allow-Origin: http://localhost:9017
Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type
```
