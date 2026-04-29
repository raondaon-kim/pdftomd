# INFRA — 인프라 / 배포

## 1. docker-compose.yml

```yaml
version: '3.9'

services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - REDIS_URL=redis://redis:6379/0
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
      - GEMINI_API_KEY=${GEMINI_API_KEY:-}
      - DATA_DIR=/data
      - MAX_PDF_SIZE_MB=100
      - MAX_PDF_PAGES=100
      - RESULT_TTL_SECONDS=3600
      - CORS_ORIGINS=http://localhost:3000
    volumes:
      - data:/data
    depends_on:
      redis:
        condition: service_healthy
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 3s
      retries: 5

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      - REDIS_URL=redis://redis:6379/0
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
      - GEMINI_API_KEY=${GEMINI_API_KEY:-}
      - DATA_DIR=/data
    volumes:
      - data:/data
    depends_on:
      redis:
        condition: service_healthy
    command: rq worker pdf-jobs --url redis://redis:6379/0

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_BASE=http://localhost:8000
    depends_on:
      - backend

  cleaner:
    # 1시간 지난 결과 파일 정리 — 단순 cron
    build:
      context: ./backend
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      - DATA_DIR=/data
      - RESULT_TTL_SECONDS=3600
    volumes:
      - data:/data
    command: python -m app.tools.cleaner --interval 600
    # 10분마다 한 번씩 만료 파일 청소

volumes:
  redis_data:
  data:
```

## 2. backend/Dockerfile

```dockerfile
FROM python:3.11-slim

# poppler-utils for pdftoppm, pdfinfo, pdftotext
# fonts for rendering Korean PDFs correctly
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    fonts-noto-cjk \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy app code
COPY app ./app

# Default command (overridden in docker-compose for worker)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 3. frontend/Dockerfile

```dockerfile
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
EXPOSE 3000
CMD ["npm", "start"]
```

## 4. 환경 변수

### 4.1 `.env.example`

```bash
# LLM API 키 — 사용할 모델의 키만 채우면 됨 (최소 1개 필요)
# 키가 없는 모델은 UI에서 비활성화됨
ANTHROPIC_API_KEY=sk-ant-...      # Claude Haiku 4.5
GEMINI_API_KEY=AIza...            # Gemini 2.5 Flash, Gemini 3 Flash

# 선택 (기본값 있음)
MAX_PDF_SIZE_MB=100
MAX_PDF_PAGES=100
RESULT_TTL_SECONDS=3600
RENDER_DPI=150
```

### 4.2 변수 명세

| 변수 | 기본 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | - | Claude 모델용. 없으면 Claude 비활성 |
| `GEMINI_API_KEY` | - | Gemini 2.5/3 모델용. 없으면 Gemini 비활성 |
| (둘 다 없으면) | - | 서버 부팅 실패 — 최소 1개 필수 |
| `REDIS_URL` | `redis://redis:6379/0` | Redis 연결 URL |
| `DATA_DIR` | `/data` | 업로드/결과 저장 루트 |
| `MAX_PDF_SIZE_MB` | `100` | 업로드 PDF 최대 크기 |
| `MAX_PDF_PAGES` | `100` | 처리할 최대 페이지 수 |
| `RESULT_TTL_SECONDS` | `3600` | 결과 보존 시간 |
| `RENDER_DPI` | `150` | 페이지 렌더링 DPI |
| `CORS_ORIGINS` | `http://localhost:3000` | CORS 허용 도메인 (콤마 구분) |

### 4.3 부팅 시 키 검증

서버 시작 시 `Settings`가 환경변수를 읽어 사용 가능한 모델을 결정:

```python
class Settings(BaseSettings):
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None

    @property
    def available_models(self) -> list[str]:
        models = []
        if self.anthropic_api_key:
            models.append("claude-haiku-4-5")
        if self.gemini_api_key:
            models.extend(["gemini-2-5-flash", "gemini-3-flash"])
        return models

    def validate_at_startup(self):
        if not self.available_models:
            raise RuntimeError(
                "사용 가능한 LLM 모델이 없습니다. "
                "ANTHROPIC_API_KEY 또는 GEMINI_API_KEY를 설정하세요."
            )
```

## 5. 실행 방법

```bash
# 1. .env 작성
cp .env.example .env
# ANTHROPIC_API_KEY 또는 GEMINI_API_KEY 중 최소 1개 채우기

# 2. 빌드 + 실행
docker-compose up --build -d

# 3. 로그 확인
docker-compose logs -f backend worker

# 4. 접속
# http://localhost:3000

# 5. 종료
docker-compose down

# 6. 데이터까지 다 지우기
docker-compose down -v
```

## 6. 정리(cleanup) 작업

`/data` 가 무한 누적되지 않도록 `cleaner` 서비스가 주기적으로 정리:

```python
# backend/app/tools/cleaner.py
import os, time, shutil
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
TTL = int(os.environ.get("RESULT_TTL_SECONDS", 3600))
INTERVAL = int(os.environ.get("CLEANUP_INTERVAL", 600))

def cleanup_once():
    cutoff = time.time() - TTL
    for sub in [DATA_DIR / "uploads", DATA_DIR / "outputs"]:
        if not sub.exists():
            continue
        for entry in sub.iterdir():
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                print(f"removed: {entry}")

if __name__ == "__main__":
    while True:
        cleanup_once()
        time.sleep(INTERVAL)
```

## 7. 리소스 권장 사양

개인 PC에서 실행하는 기준:

| 컴포넌트 | RAM | CPU |
|---|---|---|
| redis | 50MB | 0.1 core |
| backend | 200MB | 0.2 core |
| worker | 1~2GB (PDF 처리 시) | 0.5~1 core |
| frontend | 200MB (런타임) | 0.1 core |
| **합계 (러시 시)** | **~3GB** | **~2 cores** |

대형 PDF(100 페이지 + 고해상도) 처리 시 worker 메모리가 일시적으로 늘 수 있음.

## 8. 외부 의존성

| 의존 | 종류 | 장애 시 영향 |
|---|---|---|
| Anthropic API | 외부 (Claude 모델 사용 시) | Claude 모델 작업 멈춤. Gemini는 영향 없음 |
| Google Gemini API | 외부 (Gemini 모델 사용 시) | Gemini 모델 작업 멈춤. Claude는 영향 없음 |
| Docker | 런타임 | 실행 불가 |
| Redis | 내부 | 큐 동작 안 함 (재시작 시 복구) |
| Internet | 필수 | LLM 호출 불가 |

## 9. 로그 / 관찰

개인용이라 거창한 모니터링은 없음:

- 로그는 stdout (docker logs로 봄)
- 워커는 페이지 단위로 로그:
  ```
  [job=550e...] page 12/28 — analyzing
  [job=550e...] page 12/28 — done (classification=content, bbox=...)
  [job=550e...] page 13/28 — analyzing
  ```
- API 호출 비용 로그 (선택): `[job=550e...] llm_cost_usd=0.018`

## 10. 향후 클라우드 이전 시 변경점

(참고용. v1엔 안 함.)

| 컴포넌트 | 로컬 | 클라우드 시 |
|---|---|---|
| 파일 저장 | 도커 볼륨 | S3 / R2 |
| Redis | 컨테이너 | Upstash / ElastiCache |
| Worker | docker-compose | ECS / Cloud Run / Fly.io |
| Frontend | 컨테이너 | Vercel / Cloudflare Pages |
| Backend | 컨테이너 | Fly.io / Railway / ECS |
| Secret | `.env` | AWS Secrets Manager / Doppler |
