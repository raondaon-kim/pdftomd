import type { ModelInfo } from "@/lib/types";

interface Props {
  modelId: string;
  models?: ModelInfo[] | null;
}

export function ModelBadge({ modelId, models }: Props) {
  const info = models?.find((m) => m.id === modelId);
  const display = info?.display_name ?? modelId;
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
      <span aria-hidden>🤖</span>
      {display}
      {info?.is_preview && (
        <span className="rounded bg-amber-100 px-1 text-amber-800">베타</span>
      )}
    </span>
  );
}
