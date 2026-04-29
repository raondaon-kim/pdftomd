"use client";

import { useMemo } from "react";
import { getImageUrl } from "@/lib/api";

interface Props {
  jobId: string;
  markdown: string;
}

/**
 * Minimal markdown preview without external deps. We render the markdown as a
 * pre-formatted block but rewrite ``images/<file>.png`` references to absolute
 * URLs and surface them as inline previews above the code so users can see
 * cropped figures alongside the text. This is intentionally lightweight — full
 * markdown rendering is deferred to v2 (would need react-markdown + plugins).
 */
export function MarkdownPreview({ jobId, markdown }: Props) {
  const images = useMemo(() => extractImageRefs(markdown), [markdown]);

  return (
    <div className="space-y-4">
      {images.length > 0 && (
        <details
          className="rounded-lg border border-slate-200 bg-white"
          open
        >
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-slate-700">
            추출된 이미지 ({images.length})
          </summary>
          <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2">
            {images.map((name) => (
              <figure
                key={name}
                className="overflow-hidden rounded-md border border-slate-200"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={getImageUrl(jobId, name)}
                  alt={name}
                  className="h-auto w-full bg-slate-100 object-contain"
                />
                <figcaption className="truncate px-2 py-1 text-xs text-slate-500">
                  {name}
                </figcaption>
              </figure>
            ))}
          </div>
        </details>
      )}

      <pre className="max-h-[60vh] overflow-auto rounded-lg border border-slate-200 bg-white p-4 font-mono text-xs leading-relaxed text-slate-800">
        {markdown}
      </pre>
    </div>
  );
}

function extractImageRefs(markdown: string): string[] {
  // Matches both ![alt](images/foo.png) and HTML <img src="images/foo.png">
  const refs = new Set<string>();
  const mdPattern = /!\[[^\]]*\]\(images\/([^)\s]+)\)/g;
  const htmlPattern = /<img[^>]*src=["']images\/([^"']+)["']/gi;
  for (const m of markdown.matchAll(mdPattern)) refs.add(m[1]);
  for (const m of markdown.matchAll(htmlPattern)) refs.add(m[1]);
  return Array.from(refs);
}
