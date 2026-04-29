"use client";

import Link from "next/link";
import { getDownloadUrl } from "@/lib/api";
import { formatBytes, stepLabel } from "@/lib/format";
import type { JobStatusResponse } from "@/lib/types";
import { ProgressBar } from "./ProgressBar";

export type QueueItemState =
  | { kind: "pending"; file: File }
  | { kind: "uploading"; file: File }
  | { kind: "running"; file: File; jobId: string; job: JobStatusResponse | null }
  | { kind: "done"; file: File; jobId: string; job: JobStatusResponse }
  | {
      kind: "failed";
      file: File;
      jobId: string | null;
      message: string;
      code?: string;
    };

interface Props {
  index: number;
  total: number;
  item: QueueItemState;
  onRemove?: () => void;
}

export function QueueItem({ index, total, item, onRemove }: Props) {
  return (
    <li className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-medium text-slate-600">
          {index + 1}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <p className="truncate text-sm font-medium text-slate-900">
              📄 {item.file.name}
            </p>
            <span className="shrink-0 text-xs text-slate-500">
              {formatBytes(item.file.size)}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-slate-500">
            {index + 1} / {total} · <StatusLabel item={item} />
          </p>
          <div className="mt-3">
            <Body item={item} />
          </div>
        </div>
        {onRemove && item.kind === "pending" && (
          <button
            type="button"
            onClick={onRemove}
            className="shrink-0 text-xs text-slate-400 hover:text-slate-700"
          >
            제거
          </button>
        )}
      </div>
    </li>
  );
}

function StatusLabel({ item }: { item: QueueItemState }) {
  switch (item.kind) {
    case "pending":
      return <>대기 중</>;
    case "uploading":
      return <>업로드 중...</>;
    case "running":
      return (
        <>
          처리 중 ({stepLabel(item.job?.current_step ?? null)}
          {item.job?.current_page ? `, ${item.job.current_page}p` : ""})
        </>
      );
    case "done":
      return <span className="text-emerald-600">완료</span>;
    case "failed":
      return <span className="text-red-600">실패</span>;
  }
}

function Body({ item }: { item: QueueItemState }) {
  switch (item.kind) {
    case "pending":
      return null;
    case "uploading":
      return <ProgressBar value={0} />;
    case "running": {
      const pct = item.job?.progress_pct ?? 0;
      const processed = item.job?.processed_pages ?? 0;
      const total = item.job?.total_pages ?? 0;
      return (
        <div>
          <ProgressBar value={pct} />
          <p className="mt-1 text-xs text-slate-500">
            {processed} / {total} 페이지
          </p>
        </div>
      );
    }
    case "done":
      return (
        <div className="flex flex-wrap items-center gap-3">
          <a
            href={getDownloadUrl(item.jobId)}
            download
            className="inline-flex items-center justify-center rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-blue-700"
          >
            📥 ZIP 다운로드
          </a>
          <Link
            href={`/jobs/${item.jobId}`}
            className="text-xs text-slate-500 hover:text-slate-800"
          >
            상세 보기
          </Link>
        </div>
      );
    case "failed":
      return (
        <div className="space-y-1">
          <p className="text-sm text-red-700">{item.message}</p>
          {item.code && (
            <p className="font-mono text-xs text-red-500">code: {item.code}</p>
          )}
        </div>
      );
  }
}
