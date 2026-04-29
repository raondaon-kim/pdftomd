# FRONTEND — Next.js 화면 설계

## 1. 기술 스택

| 항목 | 선택 |
|---|---|
| 프레임워크 | Next.js 14+ (App Router) |
| 언어 | TypeScript |
| 스타일링 | Tailwind CSS |
| 상태 관리 | React state + URL params (전역 상태 라이브러리 불필요) |
| HTTP 클라이언트 | fetch (네이티브) |
| 파일 업로드 UX | react-dropzone |

App Router를 쓰지만 SSR/SSG 기능은 거의 안 씀 — 그냥 Vite/CRA였어도 됨. 익숙함과 폴더 구조 명확성 때문에 선택.

## 2. 화면 구성

세 화면만 있음 — 단순 흐름:

```
[/]                  업로드 화면
  │ POST /jobs 성공
  ▼
[/jobs/{id}]         처리 중 화면 (진행률 + 폴링)
  │ status === 'done'
  ▼
[/jobs/{id}/done]    완료 화면 (다운로드 + 미리보기)

또는 (실패):
[/jobs/{id}]         status === 'failed' → 에러 메시지 + 다시 시도
```

라우팅이라기보다 같은 페이지에서 상태 전환에 가까움. 하지만 URL을 분리하면 사용자가 `/jobs/{id}` URL을 북마크해서 페이지를 떠났다 다시 와도 같은 작업을 볼 수 있음.

## 3. 화면별 와이어프레임

### 3.1 `/` — 업로드 화면

```
┌─────────────────────────────────────────────────┐
│                                                 │
│         📄 PDF Slide Extractor                  │
│                                                 │
│   강의 슬라이드 PDF를 마크다운+이미지로 추출    │
│                                                 │
│   ┌───────────────────────────────────────────┐ │
│   │      [드래그 & 드롭 또는 클릭]            │ │
│   │      📁 PDF 파일을 여기에 놓으세요        │ │
│   │      최대 100MB / 100페이지               │ │
│   └───────────────────────────────────────────┘ │
│                                                 │
│   [선택된 파일: deepco_kdc_18.pdf  (5.4MB)]     │
│                                                 │
│   분석 모델                                     │
│   ┌───────────────────────────────────────────┐ │
│   │ ⦿ Gemini 3 Flash       베타  ~$0.20/PDF   │ │
│   │ ○ Claude Haiku 4.5           ~$0.20/PDF   │ │
│   │ ○ Gemini 2.5 Flash           ~$0.10/PDF   │ │
│   └───────────────────────────────────────────┘ │
│                                                 │
│              [ 추출 시작 ]                      │
│                                                 │
└─────────────────────────────────────────────────┘
```

페이지 로드 시 `GET /models`를 호출해서 라디오 버튼 목록을 동적으로 채움. 비활성 모델은 회색 + 호버 안내("`GEMINI_API_KEY` 환경변수가 설정되지 않았습니다").

기본 선택은 사용 가능한 첫 번째 모델 (서버에서 결정한 우선순위 순서대로).

상태:
- 초기 진입: `GET /models` 호출, 드롭존 + 모델 라디오 표시
- 파일 선택됨 + 모델 선택됨: "추출 시작" 버튼 활성
- 검증 실패: 빨간 메시지 ("PDF 파일이 아닙니다", "100MB를 초과합니다" 등)
- 업로드 중: "추출 시작" 버튼이 스피너로 변경
- 성공: `/jobs/{id}`로 이동
- 사용 가능한 모델이 0개: 안내 화면 ("서버에 LLM API 키가 설정되지 않았습니다. 관리자에게 문의하세요.")

### 3.2 `/jobs/{id}` — 처리 중 화면

```
┌─────────────────────────────────────────────────┐
│                                                 │
│   📄 deepco_kdc_18.pdf                          │
│   분석 모델: Gemini 3 Flash (베타)              │
│                                                 │
│   처리 중... 12 / 28 페이지                     │
│                                                 │
│   ┌───────────────────────────────────────────┐ │
│   │ ████████████░░░░░░░░░░░░░░░░░░    43%     │ │
│   └───────────────────────────────────────────┘ │
│                                                 │
│   현재 단계: 페이지 분석 중 (12페이지)          │
│                                                 │
│   처리 시작: 5분 30초 전                        │
│   예상 남은 시간: 약 4분                        │
│                                                 │
│                                                 │
│   [ 작업 취소 ]                                 │
│                                                 │
└─────────────────────────────────────────────────┘
```

폴링:
- 1초마다 `GET /jobs/{id}`
- `status === 'done'` → `/jobs/{id}/done`으로 이동
- `status === 'failed'` → 같은 페이지에 에러 표시

예상 시간: `(elapsed / processed_pages) * (total_pages - processed_pages)` 단순 추정.

### 3.3 `/jobs/{id}/done` — 완료 화면

```
┌─────────────────────────────────────────────────┐
│                                                 │
│   ✅ 추출 완료                                  │
│                                                 │
│   📄 deepco_kdc_18.pdf                          │
│   28 페이지 → 14개 이미지 + 마크다운            │
│   처리 시간: 4분 12초                           │
│                                                 │
│   [ 📥 ZIP 다운로드 (5.2MB) ]                   │
│                                                 │
│   ───────────────────────────────────           │
│   미리보기                                      │
│                                                 │
│   ┌─ 슬라이드 6 ─────────────────────────────┐  │
│   │ 데이터 분석 모델이란?                    │  │
│   │ [이미지 썸네일]                          │  │
│   │ 데이터 분석 모델은 다양한 수치 데이터... │  │
│   └──────────────────────────────────────────┘  │
│                                                 │
│   ┌─ 슬라이드 7 ─────────────────────────────┐  │
│   │ ...                                      │  │
│   └──────────────────────────────────────────┘  │
│                                                 │
│              [ 새 PDF 추출하기 ]                │
│                                                 │
└─────────────────────────────────────────────────┘
```

미리보기는 v1에서 옵셔널 — 시간 부족하면 다운로드 버튼만 두고 v2로 미룸.

## 4. 컴포넌트 트리

```
app/
├── layout.tsx                    # 공통 레이아웃 (헤더, 풋터)
├── page.tsx                      # / 업로드 화면
│   ├── <FileDropzone />
│   ├── <ModelSelector />         # GET /models 결과 라디오
│   └── <UploadButton />
├── jobs/
│   └── [id]/
│       ├── page.tsx              # 처리 중 화면
│       │   ├── <ModelBadge />    # 사용 모델 표시
│       │   ├── <ProgressBar />
│       │   ├── <StatusMessage />
│       │   └── <CancelButton />
│       └── done/
│           └── page.tsx          # 완료 화면
│               ├── <DownloadButton />
│               └── <SlidePreview />
│
components/
├── FileDropzone.tsx
├── ModelSelector.tsx             # 라디오 + 베타 라벨 + 비활성 처리
├── ModelBadge.tsx
├── ProgressBar.tsx
├── StatusMessage.tsx
├── DownloadButton.tsx
├── SlidePreview.tsx              # 슬라이드 카드 1개
└── ErrorBox.tsx
│
lib/
├── api.ts                        # API 호출 래퍼
├── types.ts                      # API 응답 타입
└── usePolling.ts                 # 폴링 커스텀 훅
```

## 5. 주요 코드 스케치

### 5.1 `lib/api.ts`

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000';

export interface ModelInfo {
  id: string;
  display_name: string;
  provider: 'anthropic' | 'google';
  is_preview: boolean;
  enabled: boolean;
  estimated_cost_per_pdf_usd: number;
  notes: string;
}

export async function listModels(): Promise<ModelInfo[]> {
  const res = await fetch(`${API_BASE}/models`);
  if (!res.ok) throw await toApiError(res);
  const data = await res.json();
  return data.models;
}

export async function uploadPdf(
  file: File,
  modelId: string,
): Promise<{ job_id: string; total_pages: number; model: string }> {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('model', modelId);
  const res = await fetch(`${API_BASE}/jobs`, { method: 'POST', body: fd });
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export async function getJob(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`);
  if (!res.ok) throw await toApiError(res);
  return res.json();
}

export function getDownloadUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/download`;
}
```

### 5.2 `lib/usePolling.ts`

```typescript
import { useEffect, useState } from 'react';
import { getJob } from './api';
import type { JobStatusResponse } from './types';

export function useJobPolling(jobId: string, intervalMs = 1000) {
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: NodeJS.Timeout;

    async function tick() {
      try {
        const data = await getJob(jobId);
        if (cancelled) return;
        setJob(data);
        if (data.status === 'done' || data.status === 'failed') return;  // stop polling
        timer = setTimeout(tick, intervalMs);
      } catch (e) {
        if (!cancelled) setError(e as Error);
      }
    }

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, intervalMs]);

  return { job, error };
}
```

### 5.3 `app/jobs/[id]/page.tsx`

```typescript
'use client';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { useJobPolling } from '@/lib/usePolling';
import { ProgressBar } from '@/components/ProgressBar';
import { ErrorBox } from '@/components/ErrorBox';

export default function JobPage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const { job, error } = useJobPolling(params.id);

  useEffect(() => {
    if (job?.status === 'done') {
      router.replace(`/jobs/${params.id}/done`);
    }
  }, [job?.status, params.id, router]);

  if (error) return <ErrorBox message={error.message} />;
  if (!job) return <div>로딩 중...</div>;
  if (job.status === 'failed') return <ErrorBox message={job.error?.message ?? '알 수 없는 오류'} />;

  return (
    <div>
      <h1>처리 중... {job.processed_pages} / {job.total_pages} 페이지</h1>
      <ProgressBar value={job.progress_pct} />
      <p>현재 단계: {stepLabel(job.current_step)}</p>
    </div>
  );
}

function stepLabel(step: string | null): string {
  switch (step) {
    case 'rasterizing': return '페이지 렌더링 중';
    case 'analyzing_page': return '페이지 분석 중';
    case 'cropping': return '이미지 크롭 중';
    case 'packaging': return 'ZIP 생성 중';
    default: return '준비 중';
  }
}
```

## 6. UX 디테일

| 상황 | 처리 |
|---|---|
| 사용자가 처리 중 페이지 닫음 | 작업은 계속 진행. URL 다시 들어오면 폴링 재개 |
| 1시간 후 결과 만료 | "결과가 만료되었습니다" 안내 + 새로 추출 버튼 |
| 다운로드 후 같은 PDF 또 처리 | 항상 새 job_id 발급 (중복 검사 안 함, 단순함) |
| 동시에 다른 PDF 업로드 시도 | 백엔드 큐에 줄 서고, UI는 그냥 진행 (개인용이라 동시 거의 없음) |
| 업로드 중 네트워크 끊김 | fetch 에러 표시, 다시 시도 가능 |

## 7. 환경 변수

```
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

`.env.local`에 두고 docker-compose에서 `API_BASE=http://backend:8000` 식으로 다르게 줄 수 있음.

## 8. 비목표

- 다크모드 (개인용이고 시간 들일 가치 X — Tailwind는 켜놓되 v2)
- 모바일 최적화 (PDF 추출은 데스크톱 작업)
- i18n
- 접근성 강화 (기본 시맨틱 HTML 정도만)
