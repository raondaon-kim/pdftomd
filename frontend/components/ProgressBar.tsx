interface Props {
  value: number;
  failed?: boolean;
}

export function ProgressBar({ value, failed }: Props) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div className="w-full">
      <div className="h-3 w-full overflow-hidden rounded-full bg-slate-200">
        <div
          className={[
            "h-full transition-[width] duration-300",
            failed ? "bg-red-500" : "bg-blue-500",
          ].join(" ")}
          style={{ width: `${clamped}%` }}
        />
      </div>
      <div className="mt-1 text-right text-xs font-medium text-slate-600">
        {clamped}%
      </div>
    </div>
  );
}
