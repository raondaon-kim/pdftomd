interface Props {
  title?: string;
  message: string;
  code?: string;
  onRetry?: () => void;
  retryLabel?: string;
}

export function ErrorBox({
  title = "오류가 발생했습니다",
  message,
  code,
  onRetry,
  retryLabel = "다시 시도",
}: Props) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 p-4">
      <div className="flex items-start gap-3">
        <span aria-hidden className="text-red-600">
          ⚠️
        </span>
        <div className="flex-1">
          <p className="text-sm font-medium text-red-900">{title}</p>
          <p className="mt-1 text-sm text-red-800">{message}</p>
          {code && (
            <p className="mt-1 font-mono text-xs text-red-600">code: {code}</p>
          )}
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="mt-3 rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-100"
            >
              {retryLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
