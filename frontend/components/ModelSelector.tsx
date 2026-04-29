"use client";

import type { ModelInfo } from "@/lib/types";

interface Props {
  models: ModelInfo[];
  selected: string | null;
  onSelect: (id: string) => void;
  disabled?: boolean;
}

export function ModelSelector({ models, selected, onSelect, disabled }: Props) {
  if (models.length === 0) {
    return (
      <p className="text-sm text-slate-500">사용 가능한 모델이 없습니다.</p>
    );
  }

  return (
    <ul className="divide-y divide-slate-200 overflow-hidden rounded-xl border border-slate-200 bg-white">
      {models.map((m) => {
        const checked = selected === m.id;
        const inactive = !m.enabled;
        return (
          <li key={m.id}>
            <label
              className={[
                "flex cursor-pointer items-start gap-3 px-4 py-3",
                inactive ? "cursor-not-allowed opacity-50" : "hover:bg-slate-50",
                checked && !inactive ? "bg-blue-50" : "",
              ].join(" ")}
              title={
                inactive ? "API 키가 서버에 설정되지 않았습니다" : undefined
              }
            >
              <input
                type="radio"
                name="model"
                value={m.id}
                checked={checked}
                disabled={disabled || inactive}
                onChange={() => onSelect(m.id)}
                className="mt-1"
              />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-900">
                    {m.display_name}
                  </span>
                  {m.is_preview && (
                    <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800">
                      베타
                    </span>
                  )}
                  {inactive && (
                    <span className="rounded bg-slate-200 px-1.5 py-0.5 text-xs text-slate-700">
                      비활성
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-xs text-slate-500">{m.notes}</p>
              </div>
            </label>
          </li>
        );
      })}
    </ul>
  );
}
