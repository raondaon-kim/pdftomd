export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

export function stepLabel(step: string | null): string {
  switch (step) {
    case "validating":
      return "PDF 검증 중";
    case "rasterizing":
      return "페이지 렌더링 중";
    case "extracting_text":
      return "텍스트 추출 중";
    case "extracting_context":
      return "강의 맥락 추출 중";
    case "analyzing_page":
      return "페이지 분석 중";
    case "cropping":
      return "이미지 크롭 중";
    case "packaging":
      return "ZIP 생성 중";
    default:
      return "준비 중";
  }
}

export function elapsedSince(iso: string | null): number {
  if (!iso) return 0;
  const started = new Date(iso).getTime();
  if (Number.isNaN(started)) return 0;
  return Math.max(0, Date.now() - started);
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return "0초";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes <= 0) return `${seconds}초`;
  return `${minutes}분 ${seconds}초`;
}

export function estimateRemaining(
  startedAt: string | null,
  processed: number,
  total: number,
): string | null {
  if (!startedAt || processed <= 0 || total <= 0 || processed >= total) {
    return null;
  }
  const elapsedMs = elapsedSince(startedAt);
  if (elapsedMs <= 0) return null;
  const perPage = elapsedMs / processed;
  const remaining = perPage * (total - processed);
  return formatDuration(remaining);
}
