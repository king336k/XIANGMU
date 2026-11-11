// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass } from "./shared";

type SourceLocation = { page?: number; part?: string; paragraph?: number; source_image?: string };
export type OcrStatus = {
  token: string;
  status: "idle" | "queued" | "running" | "completed" | "failed";
  segments: (SourceLocation & { key: string; text: string })[];
  failures: (SourceLocation & { error: string })[];
  requires_review: boolean;
  reviewed?: boolean;
  error?: string;
};

function location(source: SourceLocation, index: number) {
  if (source.page) return `第${source.page}页`;
  if (source.part) return `${source.part}${source.paragraph ? ` · 第${source.paragraph}段` : ""}`;
  return source.source_image || `图片${index + 1}`;
}

export function DocumentOcrReview<T>({
  base,
  importId,
  initial,
  onPendingChange,
  onApplied,
}: {
  base: string;
  importId: string;
  initial?: OcrStatus;
  onPendingChange: (pending: boolean) => void;
  onApplied: (preview: T) => void;
}) {
  const [status, setStatus] = useState(initial);
  const [texts, setTexts] = useState<Record<string, string>>(() =>
    Object.fromEntries((initial?.segments || []).map((segment) => [segment.key, segment.text]))
  );
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(true);
  const polling = status?.status === "queued" || status?.status === "running";
  const reviewed = status?.reviewed === true && status.requires_review === false;
  const failed = status?.status === "failed" || !!status?.failures.length;
  const endpoint = `${base}document-imports/${importId}/ocr/`;
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (!polling) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await qualityApi.read<OcrStatus>(endpoint);
        if (cancelled) return;
        setStatus(next);
        setTexts(Object.fromEntries(next.segments.map((segment) => [segment.key, segment.text])));
        setConfirmed(false);
        if (next.status === "queued" || next.status === "running") timer = setTimeout(poll, 2000);
      } catch (cause) {
        if (cancelled) return;
        setError(errorMessage(cause));
        setStatus((value) => value && { ...value, status: "failed" });
      }
    };
    timer = setTimeout(poll, 2000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [endpoint, polling, status?.token]);

  const start = async () => {
    onPendingChange(true);
    setBusy(true);
    setError("");
    setConfirmed(false);
    try {
      const next = await qualityApi.write<OcrStatus>(endpoint, {});
      if (!active.current) return;
      setStatus(next);
      setTexts(Object.fromEntries(next.segments.map((segment) => [segment.key, segment.text])));
    } catch (cause) {
      if (active.current) setError(errorMessage(cause));
    } finally {
      if (active.current) setBusy(false);
    }
  };
  const adopt = async () => {
    if (busy || failed || !confirmed || status?.status !== "completed" || !status.segments.length) return;
    setBusy(true);
    setError("");
    try {
      const preview = await qualityApi.write<T>(`${endpoint}review/`, {
        expected_token: status.token,
        confirmed: true,
        segments: status.segments.map((segment) => ({ key: segment.key, text: texts[segment.key] ?? segment.text })),
      });
      if (!active.current) return;
      setStatus({ ...status, reviewed: true, requires_review: false });
      onApplied(preview);
      onPendingChange(false);
    } catch (cause) {
      if (active.current) setError(errorMessage(cause));
    } finally {
      if (active.current) setBusy(false);
    }
  };
  return (
    <section aria-label="图片文字核对" className="min-w-0 space-y-3 rounded-md border border-subtle p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-13 font-medium">图片文字</h3>
        {!reviewed && (
          <Button type="button" size="sm" variant="neutral-primary" disabled={busy || polling} onClick={start}>
            识别图片文字
          </Button>
        )}
      </div>
      {polling && (
        <p role="status" className="text-13 text-secondary">
          {status.status === "queued" ? "等待识别" : "正在识别"}
        </p>
      )}
      {reviewed && (
        <p role="status" className="text-13 text-secondary">
          核对结果已采用，请继续检查导入预览。
        </p>
      )}
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
      {status?.error && (
        <p role="alert" className="text-13 text-danger-primary">
          {status.error}
        </p>
      )}
      {!!status?.failures.length && (
        <ul className="space-y-2 text-12 text-danger-primary">
          {status.failures.map((failure, index) => (
            <li key={`${failure.page || ""}-${failure.part || ""}-${failure.source_image || ""}-${failure.error}`}>
              {location(failure, index)}：{failure.error}
            </li>
          ))}
        </ul>
      )}
      {failed && <p className="text-12 text-secondary">存在未识别的范围，不能采用本次结果。</p>}
      {status?.status === "completed" && !reviewed && !failed && (
        <>
          <p className="text-12 text-secondary">请打开上方原件或图片，对照核对并修正文字。</p>
          <div className="max-h-96 space-y-3 overflow-y-auto">
            {status.segments.map((segment, index) => (
              <details key={segment.key} open={index === 0} className="min-w-0 rounded border border-subtle p-3">
                <summary className="cursor-pointer text-13 font-medium break-words">{location(segment, index)}</summary>
                <div className="mt-3">
                  <Field label={`${location(segment, index)} · 核对文字`}>
                    <textarea
                      className={fieldClass}
                      rows={6}
                      maxLength={100000}
                      disabled={busy}
                      value={texts[segment.key] ?? segment.text}
                      onChange={(event) => {
                        setTexts({ ...texts, [segment.key]: event.target.value });
                        setConfirmed(false);
                      }}
                    />
                  </Field>
                </div>
              </details>
            ))}
          </div>
          {!status.segments.length && (
            <p role="alert" className="text-13 text-danger-primary">
              没有可核对的文字，不能采用。
            </p>
          )}
          <label className="flex items-start gap-2 text-13">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={busy}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            已对照原件核对文字
          </label>
          <Button
            type="button"
            disabled={
              busy ||
              !confirmed ||
              !status.segments.length ||
              status.segments.some((segment) => !texts[segment.key]?.trim())
            }
            onClick={adopt}
          >
            采用核对结果
          </Button>
        </>
      )}
    </section>
  );
}
