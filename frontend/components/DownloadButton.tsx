interface Props {
  href: string;
  filename?: string;
  label?: string;
}

export function DownloadButton({
  href,
  filename,
  label = "📥 ZIP 다운로드",
}: Props) {
  return (
    <a
      href={href}
      download={filename}
      className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2"
    >
      {label}
    </a>
  );
}
