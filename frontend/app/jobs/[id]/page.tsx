"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  deleteJob,
  getDownloadUrl,
  getJobContent,
  listModels,
} from "@/lib/api";
import { useJobPolling } from "@/lib/usePolling";
import {
  elapsedSince,
  estimateRemaining,
  formatDuration,
  stepLabel,
} from "@/lib/format";
import { ApiError, type ModelInfo } from "@/lib/types";
import { ProgressBar } from "@/components/ProgressBar";
import { ErrorBox } from "@/components/ErrorBox";
import { ModelBadge } from "@/components/ModelBadge";
import { DownloadButton } from "@/components/DownloadButton";
import { MarkdownPreview } from "@/components/MarkdownPreview";

export default function JobPage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const { job, error } = useJobPolling(params.id);
  const [now, setNow] = useState<number>(() => Date.now());
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    listModels()
      .then(setModels)
      .catch(() => setModels(null));
  }, []);

  // Pull content.md once the job finishes — used for the inline preview.
  useEffect(() => {
    if (job?.status !== "done") return;
    let cancelled = false;
    getJobContent(params.id)
      .then((md) => {
        if (!cancelled) setMarkdown(md);
      })
      .catch(() => {
        if (!cancelled) setMarkdown(null);
      });
    return () => {
      cancelled = true;
    };
  }, [job?.status, params.id]);

  if (error instanceof ApiError && error.status === 404) {
    return (
      <ErrorBox
        title="작업을 찾을 수 없습니다"
        message="만료되었거나 삭제된 작업입니다."
        code={error.code}
        onRetry={() => router.push("/")}
        retryLabel="홈으로"
      />
    );
  }

  if (!job) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">
        작업 상태를 불러오는 중...
      </div>
    );
  }

  if (job.status === "failed") {
    return (
      <ErrorBox
        title="작업이 실패했습니다"
        message={job.error?.message ?? "원인을 확인할 수 없는 오류입니다."}
        code={job.error?.code}
        onRetry={() => router.push("/")}
        retryLabel="홈으로"
      />
    );
  }

  if (job.status === "done") {
    return (
      <div className="space-y-6">
        <header className="space-y-2">
          <div className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-slate-900">
            <span aria-hidden>✅</span> 추출 완료
          </div>
          <ModelBadge modelId={job.model} models={models} />
        </header>

        <section className="rounded-xl border border-slate-200 bg-white p-5">
          <p className="text-sm text-slate-600">{job.total_pages} 페이지</p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <DownloadButton href={getDownloadUrl(job.job_id)} />
            <Link
              href="/"
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
            >
              홈으로
            </Link>
            <button
              type="button"
              onClick={async () => {
                if (!confirm("이 작업과 결과 파일을 삭제할까요?")) return;
                setDeleting(true);
                try {
                  await deleteJob(job.job_id);
                  router.push("/");
                } catch (e) {
                  setDeleting(false);
                  alert(
                    `삭제 실패: ${
                      e instanceof Error ? e.message : String(e)
                    }`,
                  );
                }
              }}
              disabled={deleting}
              className="ml-auto text-xs text-slate-500 hover:text-red-600 disabled:opacity-60"
            >
              {deleting ? "삭제 중..." : "결과 삭제"}
            </button>
          </div>
        </section>

        {markdown !== null && (
          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-slate-800">미리보기</h2>
            <MarkdownPreview jobId={job.job_id} markdown={markdown} />
          </section>
        )}
      </div>
    );
  }

  // status: queued | processing — show progress.
  const elapsed = job.started_at
    ? Math.max(0, now - new Date(job.started_at).getTime())
    : elapsedSince(job.started_at);
  const eta = estimateRemaining(
    job.started_at,
    job.processed_pages,
    job.total_pages,
  );

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">
          처리 중...
        </h1>
        <ModelBadge modelId={job.model} models={models} />
      </header>

      <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
        <div className="flex items-baseline justify-between">
          <span className="text-sm text-slate-600">
            {job.processed_pages} / {job.total_pages} 페이지
          </span>
          <span className="text-xs text-slate-500">
            현재 단계: {stepLabel(job.current_step)}
            {job.current_page ? ` (${job.current_page}p)` : ""}
          </span>
        </div>
        <ProgressBar value={job.progress_pct} />
        <div className="grid grid-cols-2 gap-3 pt-2 text-xs text-slate-500">
          <div>처리 시간: {formatDuration(elapsed)}</div>
          <div className="text-right">
            {eta ? `남은 시간: 약 ${eta}` : "남은 시간 계산 중..."}
          </div>
        </div>
      </section>

      {error && !(error instanceof ApiError && error.status === 404) && (
        <p className="text-xs text-amber-700">
          폴링 중 일시적인 네트워크 오류: {error.message} (자동 재시도)
        </p>
      )}

      <Link
        href="/"
        className="inline-block text-sm text-slate-500 hover:text-slate-800"
      >
        ← 홈으로
      </Link>
    </div>
  );
}
