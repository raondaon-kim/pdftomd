import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "PDF Slide Extractor",
  description: "강의 슬라이드 PDF를 자급자족 마크다운으로 변환합니다.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body>
        <div className="mx-auto flex min-h-screen max-w-3xl flex-col px-6 py-10">
          <header className="mb-10">
            <Link
              href="/"
              className="text-lg font-semibold tracking-tight text-slate-900"
            >
              📄 PDF Slide Extractor
            </Link>
          </header>
          <main className="flex-1">{children}</main>
          <footer className="mt-12 text-xs text-slate-400">
            Local single-user · backend :9007 · frontend :9017
          </footer>
        </div>
      </body>
    </html>
  );
}
