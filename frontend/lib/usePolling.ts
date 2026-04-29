"use client";

import { useEffect, useRef, useState } from "react";
import { getJob } from "./api";
import { ApiError, type JobStatusResponse } from "./types";

export interface UseJobPollingResult {
  job: JobStatusResponse | null;
  error: ApiError | Error | null;
}

/**
 * Polls GET /jobs/{id} on a fixed interval. Stops once the job reaches a
 * terminal status (done|failed) or the component unmounts. Errors are kept
 * on the result object — callers decide whether to render or retry.
 */
export function useJobPolling(
  jobId: string,
  intervalMs = 1000,
): UseJobPollingResult {
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      try {
        const data = await getJob(jobId);
        if (cancelledRef.current) return;
        setJob(data);
        setError(null);
        if (data.status === "done" || data.status === "failed") return;
        timer = setTimeout(tick, intervalMs);
      } catch (e) {
        if (cancelledRef.current) return;
        setError(e instanceof Error ? e : new Error(String(e)));
        // Keep retrying on transient errors so brief network blips don't break
        // the UI. Caller can inspect `error` while we keep polling.
        timer = setTimeout(tick, intervalMs);
      }
    };

    void tick();
    return () => {
      cancelledRef.current = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, intervalMs]);

  return { job, error };
}
