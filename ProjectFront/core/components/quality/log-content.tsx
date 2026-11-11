// SPDX-License-Identifier: AGPL-3.0-only
export function LogContent({ text, wrap = false }: { text: string; wrap?: boolean }) {
  const lineCount = text.split("\n").length;
  return (
    <div className="font-mono flex min-w-0 text-12 leading-6">
      {!wrap && (
        <pre
          aria-hidden="true"
          className="sticky left-0 mr-3 shrink-0 border-r border-subtle bg-layer-1 pr-3 text-right text-placeholder select-none"
        >
          {Array.from({ length: lineCount }, (_, index) => index + 1).join("\n")}
        </pre>
      )}
      <pre className={`min-w-0 flex-1 text-primary ${wrap ? "break-words whitespace-pre-wrap" : "whitespace-pre"}`}>
        <code>{text}</code>
      </pre>
    </div>
  );
}
