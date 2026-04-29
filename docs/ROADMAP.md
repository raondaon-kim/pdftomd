# ROADMAP — 개발 마일스톤

총 5개 마일스톤. 각 마일스톤은 **그 자체로 끝까지 동작**하도록 구성 — 중간에 멈춰도 무언가는 사용 가능.

## M0. 사전 준비 (반나절)

- [ ] 저장소 초기화 (`pdf-slide-extractor/`)
- [ ] `docs/` 폴더에 본 설계 문서 커밋
- [ ] Anthropic API 키 발급 + `.env` 작성
- [ ] 골든 데이터셋 정답(`expected.json`) 작성 — 딥코 KDC 18회차 28페이지
- [ ] 로컬 개발 환경 점검 (Docker, Python 3.11, Node 20)

**산출물**: 빈 저장소 + 설계 문서 + API 키 준비

---

## M1. 코어 파이프라인 (CLI로 동작)

웹 UI 없이 **명령줄로 PDF → ZIP 변환이 끝까지 되는 상태**. 다중 모델 지원 + 2-pass 구조라 작업이 많음 — M1을 세 단계로 나눔.

### M1.a — PDF I/O + 단일 모델 2패스 (1패스 없이)

먼저 1개 모델(Claude Haiku)로만 2패스를 동작시킴. 1패스는 dummy로 채움. 흐름이 끝까지 도는 게 목표.

- [ ] `backend/` 패키지 골격 (pyproject.toml, app/__init__.py, core/config.py)
- [ ] `pipeline/pdf_io.py`: pdftoppm·pdfplumber 래퍼
- [ ] `models/page_analysis.py`, `models/lecture_context.py` Pydantic 모델
- [ ] `pipeline/prompts.py`: 시스템 프롬프트 텍스트 (1패스/2패스용)
- [ ] `pipeline/providers/base.py`: `LLMProvider` Protocol + LLMError 계열
- [ ] `pipeline/providers/claude.py`: Claude Haiku 4.5 어댑터 (Tool Use)
- [ ] `pipeline/providers/__init__.py`: `make_provider`
- [ ] `pipeline/crop.py`: bbox 정규화 → PIL crop
- [ ] `pipeline/packager.py`: PageAnalysis[] → content.md → result.zip
- [ ] `pipeline/runner.py`: 위를 묶는 메인 함수 (1패스는 dummy LectureContext, provider는 인자로 받음)
- [ ] `app/cli.py`: `python -m app.cli input.pdf -o ./out --model claude-haiku-4-5`
- [ ] 단위 테스트 (pdf_io, crop, packager, providers/claude with 모킹)

**중간 검증**: 딥코 PDF + Claude Haiku로 28페이지가 끝까지 처리되고 ZIP 나오는지.

### M1.b — Gemini 어댑터 추가

같은 인터페이스에서 Gemini 2.5/3을 지원. responseSchema 변환·thinking_level 등 모델별 차이 흡수.

- [ ] `pipeline/providers/schemas.py`: Pydantic → Gemini responseSchema 변환 헬퍼
- [ ] `pipeline/providers/gemini.py`: GeminiProvider (variant: 2-5/3 공용)
- [ ] `pipeline/providers/registry.py`: 모델 ID ↔ display_name ↔ is_preview 매핑
- [ ] `pipeline/providers/__init__.py`: `list_available_providers` 추가
- [ ] CLI에 `--model gemini-2-5-flash`, `--model gemini-3-flash` 지원
- [ ] 단위 테스트: Gemini 어댑터 모킹, schema 변환 검증
- [ ] 같은 PDF를 3개 모델로 돌려 결과 비교 (정성 평가)

**중간 검증**: 3개 모델 모두 같은 PDF에서 ZIP이 나오고, 결과가 합리적인지.

### M1.c — 1패스 추가 (강의 맥락 추출)

- [ ] `pipeline/mosaic.py`: 썸네일 모자이크 생성 (PIL)
  - 페이지 그리드 배치, 셀에 페이지 번호 라벨, 8000px 한도 검사
  - 50페이지 초과 시 균등 샘플링
- [ ] 각 provider에 `call_lecture_context` 메서드 추가
  - LectureContext 검증 (page 범위, 중복 검사)
  - 재시도 3회 (지수 백오프)
  - 실패 시 strict하게 예외 발생
- [ ] `pipeline/prompts.py`에 시스템 프롬프트 템플릿 + 동적 조립 함수
- [ ] `pipeline/runner.py`: dummy LectureContext → 진짜 1패스 호출로 교체
- [ ] `pipeline/packager.py`: content.md 헤더에 강의 메타 + 사용 모델 추가
- [ ] 통합 테스트 (LLM 모킹: 1패스·2패스 + 모델 3종)
- [ ] 골든 데이터셋 비교 평가 (모델별 분류 정확도·환각률 측정)
- [ ] 통합 테스트 (LLM 모킹: 1패스·2패스 둘 다)
- [ ] 골든 데이터셋 비교 평가 (수동 정답과 비교)

### 검증

```bash
python -m app.cli tests/golden/deepco_kdc_18.pdf -o /tmp/out
ls /tmp/out
# content.md, images/, result.zip 모두 존재
head -30 /tmp/out/content.md
# 강의 제목, 요약, 핵심 용어가 헤더에 들어가 있어야 함
```

**완료 기준**:
- 골든 PDF에서 14개 본문 페이지가 분류·추출됨
- content.md 헤더에 강의 요약·핵심 용어 등장
- 마크다운 에디터로 열었을 때 이미지 참조 깨지지 않음
- LLM 평가 테스트에서 분류 정확도 ≥ 90%
- p.24-25(블록 코드) 처리에서 맥락 주입 후 환각이 줄었는지 정성 평가

**예상 기간**: M1.a 2일 + M1.b 2~3일 = **4~5일**

---

## M2. 백엔드 API (작업 큐 + 폴링)

CLI를 웹 API로 감싸기.

### 작업

- [ ] `app/main.py`: FastAPI 앱 + CORS
- [ ] `core/queue.py`: Redis + RQ 큐
- [ ] `api/jobs.py`: POST /jobs, GET /jobs/:id, GET /jobs/:id/download
- [ ] `pipeline/runner.py`에 진행률 콜백 연결 (Redis hset)
- [ ] `tools/cleaner.py`: TTL 기반 청소 스크립트
- [ ] API 테스트 (TestClient)
- [ ] backend Dockerfile + 부분적인 docker-compose (backend + redis + worker)

### 검증

```bash
docker-compose up backend worker redis

curl -X POST http://localhost:8000/jobs -F "file=@tests/golden/deepco_kdc_18.pdf"
# {"job_id": "...", "status": "queued", "total_pages": 28}

watch -n 1 'curl -s http://localhost:8000/jobs/<id>'
# 진행률이 0% → 100%로 변하는 게 보임

curl http://localhost:8000/jobs/<id>/download -o result.zip
unzip -l result.zip
```

**완료 기준**:
- API로 업로드 → 폴링 → 다운로드 끝까지 됨
- 워커가 죽었다 살아나도 큐에서 작업 재개됨
- 1시간 후 결과 자동 삭제 확인

**예상 기간**: 2~3일

---

## M3. 프론트엔드 (Next.js)

사용자에게 보이는 부분.

### 작업

- [ ] `frontend/` 골격 (Next.js 14 + Tailwind + TypeScript)
- [ ] `app/page.tsx`: 업로드 화면
- [ ] `app/jobs/[id]/page.tsx`: 진행 화면 + 폴링 훅
- [ ] `app/jobs/[id]/done/page.tsx`: 완료 + 다운로드
- [ ] 컴포넌트: FileDropzone, ProgressBar, ErrorBox, DownloadButton
- [ ] `lib/api.ts`, `lib/usePolling.ts`
- [ ] frontend Dockerfile

### 검증

수동 E2E 체크리스트 (TESTING.md §7) 통과.

**완료 기준**:
- 비개발자가 처음 봐도 PDF 업로드부터 다운로드까지 막힘 없이 가능
- 업로드 검증 에러가 명확히 표시됨
- 처리 중 페이지를 새로고침해도 진행률 유지

**예상 기간**: 2일

---

## M4. 통합 + 배포

전체를 docker-compose 한 방으로.

### 작업

- [ ] 최종 `docker-compose.yml`
- [ ] `.env.example` + README의 실행 가이드
- [ ] 헬스체크 엔드포인트
- [ ] 로그 포맷 통일
- [ ] 비용 로그 (페이지당 LLM 비용)
- [ ] README 작성 (설치/실행/문제 해결)

### 검증

```bash
git clone <repo>
cd pdf-slide-extractor
cp .env.example .env
# ANTHROPIC_API_KEY 채우기
docker-compose up --build
# http://localhost:3000 접속, 끝까지 동작
```

**완료 기준**:
- README 따라하면 새 머신에서 5분 안에 띄움
- 한 사이클이 메모리 누수 없이 돈다 (3~4번 연속 실행 후 docker stats 확인)

**예상 기간**: 1~2일

---

## M5. 폴리싱 & 회귀

### 작업

- [ ] 골든 데이터셋 추가 (다른 형식 슬라이드 PDF 1~2개)
- [ ] 프롬프트 튜닝: 평가 결과 분석 → 시스템 프롬프트 보강
- [ ] 결과 미리보기 (옵션) — `/jobs/:id/done`에서 슬라이드별 카드
- [ ] 페이지 처리 실패 시 부분 결과로라도 ZIP 생성 (graceful degradation)
- [ ] CI 워크플로우 (GitHub Actions)

**완료 기준**: 본인 외 다른 사람이 사용해도 큰 문제 없음.

**예상 기간**: 2~3일 (개선이라 무한정 늘어날 수 있음)

---

## 전체 일정 요약

| 마일스톤 | 기간 | 누적 |
|---|---|---|
| M0. 사전 준비 | 0.5일 | 0.5일 |
| M1.a 2패스 파이프라인 | 2일 | 2.5일 |
| M1.b 1패스 추가 | 2~3일 | 5~5.5일 |
| M2. 백엔드 API | 2~3일 | 7~8.5일 |
| M3. 프론트엔드 | 2일 | 9~10.5일 |
| M4. 통합 + 배포 | 1~2일 | 10.5~12.5일 |
| M5. 폴리싱 | 2~3일 | 12.5~15.5일 |
| **합계** | | **~2.5주** |

풀타임 기준. 사이드 프로젝트면 2~3배 늘어남.

## 우선순위 의사결정 가이드

시간이 부족할 때 자르는 순서:

1. **M5 폴리싱** — 일단 기본은 동작하니까
2. **M3의 미리보기 기능** — 다운로드 버튼만 있어도 도구 목적은 달성
3. **M4의 비용 로그** — 본인이 API 콘솔에서 봐도 됨

자르면 안 되는 것:

- M1의 골든 데이터 검증 (이거 없으면 LLM 출력이 좋은지 알 수 없음)
- M2의 청소 스크립트 (디스크 무한 증가)
- M4의 README (3개월 뒤 본인이 못 띄움)

## 위험 / 미정

| 위험 | 가능성 | 영향 | 대응 |
|---|---|---|---|
| LLM 분류 정확도 90% 미달 | 중 | 도구 가치 하락 | 골든 셋 확장 + 프롬프트 다중 시도 |
| **1패스 실패율이 높음** (strict 모드) | 중 | 작업 자주 실패 | 재시도 3회·입력 크기 제한 + M1.b에서 안정성 우선 검증 |
| **맥락 주입이 환각을 오히려 악화** | 중 | 데이터 오염 | M1.b 완료 후 정성 평가에서 환각률 측정 → 프롬프트 보강 |
| 1패스 모자이크 토큰 한도 초과 | 낮 | 큰 PDF 처리 불가 | 페이지 샘플링·cols 조정 fallback 구현 |
| Claude API 비용 폭증 | 낮 | 사용 제한 | 페이지당 비용 로그 + max_tokens 제한 |
| 한국어 폰트 렌더링 오류 | 중 | 이미지 품질 저하 | Dockerfile에 fonts-noto-cjk 명시 |
| pdftoppm OOM | 낮 | 워커 죽음 | DPI 150 고정, 큰 PDF 거부 |
| 사용자가 100MB 이상 업로드 시도 | 중 | 거부 메시지 보고 끝 | 명확한 에러 메시지 |
