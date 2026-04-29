export interface ModelInfo {
  id: string;
  display_name: string;
  provider: "anthropic" | "google";
  is_preview: boolean;
  enabled: boolean;
  estimated_cost_per_pdf_usd: number;
  notes: string;
}

export interface ListModelsResponse {
  models: ModelInfo[];
}

export interface CreateJobResponse {
  job_id: string;
  status: string;
  total_pages: number;
  model: string;
  created_at: string;
}

export type JobStatus = "queued" | "processing" | "done" | "failed";

export type JobStep =
  | "validating"
  | "rasterizing"
  | "extracting_text"
  | "extracting_context"
  | "analyzing_page"
  | "cropping"
  | "packaging"
  | null;

export interface JobError {
  code: string;
  message: string;
  page?: number | null;
}

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  model: string;
  total_pages: number;
  processed_pages: number;
  progress_pct: number;
  current_step: JobStep;
  current_page: number | null;
  started_at: string | null;
  finished_at: string | null;
  error: JobError | null;
}

export class ApiError extends Error {
  code: string;
  status: number;
  details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}
