"use client";

import { useCallback } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";

interface Props {
  onFilesAdded: (files: File[]) => void;
  maxSizeMb: number;
  disabled?: boolean;
}

export function FileDropzone({ onFilesAdded, maxSizeMb, disabled }: Props) {
  const maxSize = maxSizeMb * 1024 * 1024;

  const onDrop = useCallback(
    (accepted: File[]) => {
      if (accepted.length > 0) onFilesAdded(accepted);
    },
    [onFilesAdded],
  );

  const { getRootProps, getInputProps, isDragActive, fileRejections } =
    useDropzone({
      onDrop,
      multiple: true,
      maxSize,
      accept: { "application/pdf": [".pdf"] },
      disabled,
    });

  const rejectionMsg = formatRejection(fileRejections, maxSizeMb);

  return (
    <div>
      <div
        {...getRootProps()}
        className={[
          "flex h-40 cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 text-center transition",
          isDragActive
            ? "border-blue-500 bg-blue-50"
            : "border-slate-300 bg-white hover:border-slate-400",
          disabled ? "pointer-events-none opacity-60" : "",
        ].join(" ")}
      >
        <input {...getInputProps()} />
        <p className="text-sm font-medium text-slate-700">
          {isDragActive
            ? "여기에 놓으세요"
            : "📁 PDF 파일을 드래그하거나 클릭해서 선택 (여러 개 가능)"}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          파일당 최대 {maxSizeMb}MB · 100페이지
        </p>
      </div>

      {rejectionMsg && (
        <p className="mt-2 text-sm text-red-600">{rejectionMsg}</p>
      )}
    </div>
  );
}

function formatRejection(
  rejections: readonly FileRejection[],
  maxSizeMb: number,
): string | null {
  if (rejections.length === 0) return null;
  const rejection = rejections[0];
  const err = rejection.errors[0];
  const name = rejection.file.name;
  if (err.code === "file-too-large") {
    return `${name}: 파일이 너무 큽니다 (최대 ${maxSizeMb}MB)`;
  }
  if (err.code === "file-invalid-type") {
    return `${name}: PDF 파일만 업로드할 수 있습니다`;
  }
  return `${name}: ${err.message}`;
}
