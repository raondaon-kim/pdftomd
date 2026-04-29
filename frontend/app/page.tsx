"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getJob, listModels, uploadPdf } from "@/lib/api";
import { ApiError, type ModelInfo } from "@/lib/types";
import { FileDropzone } from "@/components/FileDropzone";
import { ModelSelector } from "@/components/ModelSelector";
import { ErrorBox } from "@/components/ErrorBox";
import { QueueItem, type QueueItemState } from "@/components/QueueItem";

const MAX_PDF_SIZE_MB = 100;
const POLL_INTERVAL_MS = 1000;

interface QueueEntry {
  id: string; // local-only key
  state: QueueItemState;
}

let _localId = 0;
const nextLocalId = () => `q${++_localId}`;

export default function UploadPage() {
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [running, setRunning] = useState(false);

  // We use refs so the worker loop can read current state without re-creating
  // closures on every render. The worker is a single async function that owns
  // the "active item" lifecycle and self-schedules the next pending entry.
  const queueRef = useRef<QueueEntry[]>([]);
  queueRef.current = queue;
  const cancelledRef = useRef(false);
  const modelRef = useRef<string | null>(null);
  modelRef.current = selectedModel;

  useEffect(() => {
    let cancelled = false;
    listModels()
      .then((data) => {
        if (cancelled) return;
        setModels(data);
        // Prefer GPT-5 mini as the default. Fall back to the first
        // enabled model if it isn't available (key missing).
        const preferred = data.find(
          (m) => m.id === "gpt-5-mini" && m.enabled,
        );
        const firstEnabled = preferred ?? data.find((m) => m.enabled);
        if (firstEnabled) setSelectedModel(firstEnabled.id);
      })
      .catch((err) => {
        if (cancelled) return;
        setModelsError(
          err instanceof Error
            ? err.message
            : "백엔드(/models)를 불러올 수 없습니다.",
        );
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const enabledCount = models?.filter((m) => m.enabled).length ?? 0;

  const updateEntry = useCallback(
    (id: string, patch: (cur: QueueEntry) => QueueItemState) => {
      setQueue((prev) =>
        prev.map((e) => (e.id === id ? { ...e, state: patch(e) } : e)),
      );
    },
    [],
  );

  const onFilesAdded = useCallback((files: File[]) => {
    setQueue((prev) => [
      ...prev,
      ...files.map<QueueEntry>((file) => ({
        id: nextLocalId(),
        state: { kind: "pending", file },
      })),
    ]);
  }, []);

  const removeEntry = useCallback((id: string) => {
    setQueue((prev) => prev.filter((e) => e.id !== id));
  }, []);

  // Process a single queue entry start-to-finish, then return so the caller
  // can pick the next pending one.
  const processOne = useCallback(
    async (entry: QueueEntry) => {
      const modelId = modelRef.current;
      if (!modelId) {
        updateEntry(entry.id, () => ({
          kind: "failed",
          file: entry.state.kind === "pending" ? entry.state.file : entry.state.file,
          jobId: null,
          message: "선택된 모델이 없습니다.",
        }));
        return;
      }

      const file =
        entry.state.kind === "pending" ? entry.state.file : entry.state.file;
      updateEntry(entry.id, () => ({ kind: "uploading", file }));

      let jobId: string;
      try {
        const res = await uploadPdf(file, modelId);
        jobId = res.job_id;
      } catch (err) {
        const msg =
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : String(err);
        const code = err instanceof ApiError ? err.code : undefined;
        updateEntry(entry.id, () => ({
          kind: "failed",
          file,
          jobId: null,
          message: msg,
          code,
        }));
        return;
      }

      updateEntry(entry.id, () => ({
        kind: "running",
        file,
        jobId,
        job: null,
      }));

      // Poll until done/failed. We bail out on cancellation so leaving the
      // page or hitting "stop" doesn't keep ticking.
      while (!cancelledRef.current) {
        try {
          const job = await getJob(jobId);
          if (cancelledRef.current) return;
          if (job.status === "done") {
            updateEntry(entry.id, () => ({
              kind: "done",
              file,
              jobId,
              job,
            }));
            return;
          }
          if (job.status === "failed") {
            updateEntry(entry.id, () => ({
              kind: "failed",
              file,
              jobId,
              message: job.error?.message ?? "작업이 실패했습니다.",
              code: job.error?.code,
            }));
            return;
          }
          updateEntry(entry.id, () => ({
            kind: "running",
            file,
            jobId,
            job,
          }));
        } catch (err) {
          // Transient polling failure: keep the running view, retry next tick.
          if (cancelledRef.current) return;
          // We intentionally don't surface every poll error to the user since
          // the next tick usually recovers. Worst case a /jobs 404 will flip
          // to failed below if the backend genuinely lost the job.
          if (err instanceof ApiError && err.status === 404) {
            updateEntry(entry.id, () => ({
              kind: "failed",
              file,
              jobId,
              message: "작업을 찾을 수 없습니다 (서버 재시작 가능).",
              code: err.code,
            }));
            return;
          }
        }
        await sleep(POLL_INTERVAL_MS);
      }
    },
    [updateEntry],
  );

  const start = useCallback(async () => {
    if (running) return;
    setRunning(true);
    cancelledRef.current = false;
    try {
      // Loop: pick the first pending entry, process it, repeat until none.
      // Reading from queueRef means newly added items during a run get
      // processed too — useful if the user drops more files mid-run.
      while (!cancelledRef.current) {
        const next = queueRef.current.find((e) => e.state.kind === "pending");
        if (!next) break;
        await processOne(next);
      }
    } finally {
      setRunning(false);
    }
  }, [running, processOne]);

  const stop = useCallback(() => {
    cancelledRef.current = true;
  }, []);

  // If new files arrive while a run is already in progress, the worker loop
  // will pick them up on its next iteration — no extra wiring needed.

  const pendingCount = queue.filter((e) => e.state.kind === "pending").length;
  const canStart =
    !running &&
    pendingCount > 0 &&
    !!selectedModel &&
    !!models &&
    models.find((m) => m.id === selectedModel)?.enabled === true;

  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          강의 슬라이드 PDF를 마크다운으로
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          여러 PDF를 등록하면 하나가 끝나는 즉시 다음 작업이 자동으로
          시작됩니다.
        </p>
      </section>

      {modelsError && (
        <ErrorBox
          title="모델 목록을 불러오지 못했습니다"
          message={modelsError}
          onRetry={() => window.location.reload()}
        />
      )}

      {models && enabledCount === 0 && !modelsError && (
        <ErrorBox
          title="사용 가능한 모델이 없습니다"
          message="서버에 LLM API 키(ANTHROPIC_API_KEY 또는 GEMINI_API_KEY)가 설정되지 않았습니다."
        />
      )}

      <section>
        <FileDropzone
          onFilesAdded={onFilesAdded}
          maxSizeMb={MAX_PDF_SIZE_MB}
          disabled={false}
        />
      </section>

      <section>
        <label className="mb-2 block text-sm font-medium text-slate-800">
          분석 모델
        </label>
        {models === null ? (
          <p className="text-sm text-slate-500">모델 목록 불러오는 중...</p>
        ) : (
          <ModelSelector
            models={models}
            selected={selectedModel}
            onSelect={setSelectedModel}
            disabled={running}
          />
        )}
      </section>

      {queue.length > 0 && (
        <section>
          <div className="mb-2 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-slate-800">
              작업 대기열 ({queue.length})
            </h2>
            {queue.some((e) => e.state.kind === "done") && !running && (
              <button
                type="button"
                onClick={() => setQueue((q) => q.filter((e) => e.state.kind !== "done"))}
                className="text-xs text-slate-500 hover:text-slate-800"
              >
                완료 항목 정리
              </button>
            )}
          </div>
          <ul className="space-y-3">
            {queue.map((e, i) => (
              <QueueItem
                key={e.id}
                index={i}
                total={queue.length}
                item={e.state}
                onRemove={
                  e.state.kind === "pending" ? () => removeEntry(e.id) : undefined
                }
              />
            ))}
          </ul>
        </section>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={start}
          disabled={!canStart}
          className="inline-flex flex-1 items-center justify-center rounded-lg bg-blue-600 px-5 py-3 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {running ? "처리 중..." : `추출 시작${pendingCount > 0 ? ` (${pendingCount})` : ""}`}
        </button>
        {running && (
          <button
            type="button"
            onClick={stop}
            className="rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            정지
          </button>
        )}
      </div>
    </div>
  );
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
