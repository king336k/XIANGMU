// SPDX-License-Identifier: AGPL-3.0-only
import { useMemo, useState } from "react";
import { Download, Minus, Plus, RotateCcw, Search } from "lucide-react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Modal, fieldClass } from "./shared";
import { LogContent } from "./log-content";

type Preview = { id: string; name: string; image?: string; text?: string };
export function AttachmentViewer({ base, preview, onClose }: { base: string; preview: Preview; onClose: () => void }) {
  const [zoom, setZoom] = useState(100),
    [wrap, setWrap] = useState(false),
    [format, setFormat] = useState(/\.json$/i.test(preview.name));
  const [query, setQuery] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const content = useMemo(() => {
    if (!format || preview.text === undefined) return preview.text || "";
    try {
      return JSON.stringify(JSON.parse(preview.text), null, 2);
    } catch {
      return preview.text;
    }
  }, [format, preview.text]);
  const lines = useMemo(() => content.split("\n"), [content]);
  const matches = useMemo(
    () =>
      query
        ? lines.reduce<number[]>((found, line, index) => {
            if (line.toLowerCase().includes(query.toLowerCase())) found.push(index + 1);
            return found;
          }, [])
        : [],
    [lines, query]
  );
  const [match, setMatch] = useState(0);
  const scrollToMatch = (index: number) => {
    if (!matches.length) return;
    const current = (index + matches.length) % matches.length;
    setMatch(current);
    document.getElementById("quality-log-scroll")?.scrollTo({ top: (matches[current] - 1) * 24, behavior: "smooth" });
  };
  const download = async () => {
    setBusy(true);
    setError("");
    try {
      await qualityApi.download(`${base}files/${preview.id}/download/`, preview.name.split("/").pop() || preview.name);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={preview.name} onClose={onClose}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-subtle pb-3">
        {preview.image ? (
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="neutral-primary"
              aria-label="缩小图片"
              disabled={zoom <= 25}
              onClick={() => setZoom(Math.max(25, zoom - 25))}
            >
              <Minus className="size-4" />
            </Button>
            <span className="min-w-12 text-center text-12">{zoom}%</span>
            <Button
              type="button"
              variant="neutral-primary"
              aria-label="放大图片"
              disabled={zoom >= 300}
              onClick={() => setZoom(Math.min(300, zoom + 25))}
            >
              <Plus className="size-4" />
            </Button>
            <Button type="button" variant="neutral-primary" onClick={() => setZoom(100)}>
              <RotateCcw className="mr-1 size-3" />
              适应视图
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3 text-12">
            <span>完整文件 · {lines.length.toLocaleString()} 行</span>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={wrap} onChange={(e) => setWrap(e.target.checked)} />
              自动换行
            </label>
            {/\.json$/i.test(preview.name) && (
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={format} onChange={(e) => setFormat(e.target.checked)} />
                格式化 JSON
              </label>
            )}
          </div>
        )}
        <Button type="button" variant="neutral-primary" disabled={busy} onClick={() => void download()}>
          <Download className="mr-1 size-3" />
          下载原文件
        </Button>
      </div>
      {!preview.image && (
        <div className="flex flex-wrap items-center gap-2">
          <Search className="size-4 text-secondary" />
          <input
            className={`${fieldClass} min-w-32 flex-1`}
            type="search"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setMatch(0);
            }}
            placeholder="搜索日志内容…"
            aria-label="搜索日志内容"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                scrollToMatch(query ? match : 0);
              }
            }}
          />
          <span className="text-12 text-secondary">{query ? `${matches.length} 处匹配` : "支持上下、左右滚动"}</span>
          {matches.length > 0 && (
            <Button type="button" variant="neutral-primary" onClick={() => scrollToMatch(match + 1)}>
              下一处
            </Button>
          )}
        </div>
      )}
      {preview.image ? (
        <div className="max-h-[65vh] overflow-auto rounded-md bg-layer-1 p-3">
          <img
            src={preview.image}
            alt={preview.name}
            style={{ width: `${zoom}%`, maxWidth: "none" }}
            className="mx-auto h-auto"
          />
        </div>
      ) : (
        <div
          id="quality-log-scroll"
          tabIndex={0}
          aria-label="完整文件内容，可滚动"
          className="max-h-[60vh] overflow-auto rounded-md border border-subtle bg-layer-1 p-3"
        >
          <LogContent text={content} wrap={wrap} />
        </div>
      )}
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
    </Modal>
  );
}
