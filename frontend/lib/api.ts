import {
  ApiError,
  type CreateJobResponse,
  type JobStatusResponse,
  type ListModelsResponse,
  type ModelInfo,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:9007";

async function toApiError(res: Response): Promise<ApiError> {
  let code = "HTTP_ERROR";
  let message = `HTTP ${res.status}`;
  let details: unknown = undefined;
  try {
    const body = await res.json();
    if (body?.error?.code) code = body.error.code;
    if (body?.error?.message) message = body.error.message;
    if (body?.error?.details !== undefined) details = body.error.details;
  } catch {
    // body wasn't JSON; keep defaults
  }
  return new ApiError(res.status, code, message, details);
}

export async function listModels(): Promise<ModelInfo[]> {
  const res = await fetch(`${API_BASE}/models`, { cache: "no-store" });
  if (!res.ok) throw await toApiError(res);
  const data = (await res.json()) as ListModelsResponse;
  return data.models;
}

export async function uploadPdf(
  file: File,
  modelId: string,
): Promise<CreateJobResponse> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("model", modelId);
  const res = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as CreateJobResponse;
}

export async function getJob(jobId: string): Promise<JobStatusResponse> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`, { cache: "no-store" });
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as JobStatusResponse;
}

export async function getJobContent(jobId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/content`, {
    cache: "no-store",
  });
  if (!res.ok) throw await toApiError(res);
  return res.text();
}

export async function deleteJob(jobId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw await toApiError(res);
}

export function getDownloadUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/download`;
}

export function getImageUrl(jobId: string, filename: string): string {
  return `${API_BASE}/jobs/${jobId}/images/${encodeURIComponent(filename)}`;
}
