// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { X, ChevronLeft, ChevronRight } from "lucide-react";
import { PAGE_SIZES, pageNumbers } from "./pagination";
import { createPortal } from "react-dom";
import { Button } from "@plane/ui";
import { errorMessage } from "./api";
export { Badge } from "./record-badge";

export const fieldClass =
  "w-full rounded-md border border-subtle bg-surface-1 px-3 py-2 text-13 text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary";
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5 text-13 font-medium text-secondary">
      {label}
      {children}
    </label>
  );
}
export function Modal({
  title,
  children,
  onClose,
  onSubmit,
  submitLabel = "保存",
  width = "standard",
  presentation = "dialog",
  breadcrumb,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  onSubmit?: (data: FormData) => Promise<void>;
  submitLabel?: string;
  width?: "standard" | "wide" | "compact";
  presentation?: "dialog" | "page";
  breadcrumb?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (!onSubmit || busy) return;
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      await onSubmit(data);
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return createPortal(
    <dialog
      ref={ref}
      onCancel={(e) => {
        if (e.target !== e.currentTarget) return;
        if (busy) e.preventDefault();
        else onClose();
      }}
      aria-labelledby={titleId}
      className={
        presentation === "page"
          ? "record-detail-modal defect-page"
          : `record-detail-modal shadow-lg m-auto max-h-[90vh] w-[calc(100%-2rem)] ${width === "wide" ? "max-w-5xl" : width === "compact" ? "max-w-md" : "max-w-3xl"} overflow-y-auto rounded-lg border border-subtle bg-surface-1 p-0 text-primary backdrop:bg-black/40`
      }
    >
      {presentation === "page" ? (
        <>
          <header className="defect-page-topbar">
            <span className="defect-page-brand">
              TransEngram <span>项目管理平台</span>
            </span>
            <span className="defect-page-breadcrumb">
              {breadcrumb || "项目"}
              <span aria-hidden="true">/</span>缺陷
            </span>
          </header>
          <div className="defect-page-navigation">
            <button type="button" onClick={onClose}>
              <ChevronLeft aria-hidden="true" className="size-4" />
              返回缺陷列表
            </button>
          </div>
          <h2 id={titleId} className="sr-only">
            {title}
          </h2>
        </>
      ) : (
        <div className="sticky top-0 z-10 flex min-w-0 items-center justify-between gap-3 border-b border-subtle bg-surface-1 px-4 py-4 sm:px-6">
          <h2 id={titleId} className="min-w-0 text-16 font-semibold break-words">
            {title}
          </h2>
          <button className="shrink-0" disabled={busy} aria-label="关闭弹窗" onClick={onClose}>
            <X className="size-5" />
          </button>
        </div>
      )}
      <form onSubmit={submit} className={presentation === "page" ? "defect-page-card" : undefined}>
        <div
          className={
            presentation === "page"
              ? "record-detail-body defect-page-content"
              : "record-detail-body min-w-0 space-y-5 p-4 sm:p-6"
          }
        >
          {children}
          {error && (
            <p
              role="alert"
              className="rounded-md border border-danger-subtle bg-danger-subtle p-3 text-13 text-danger-primary"
            >
              {error}
            </p>
          )}
        </div>
        {presentation !== "page" && (
          <div className="sticky bottom-0 z-10 flex flex-wrap justify-end gap-3 border-t border-subtle bg-surface-1 px-4 py-4 sm:px-6">
            <Button variant="neutral-primary" disabled={busy} onClick={onClose}>
              {onSubmit ? "取消" : "关闭"}
            </Button>
            {onSubmit && (
              <Button type="submit" disabled={busy}>
                {busy ? "正在保存…" : submitLabel}
              </Button>
            )}
          </div>
        )}
      </form>
    </dialog>,
    document.body
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return (
    <div
      role="status"
      className="flex min-h-56 items-center justify-center rounded-md border border-dashed border-subtle p-8 text-center text-13 text-secondary"
    >
      {children}
    </div>
  );
}
export function Paging({
  page,
  count,
  onChange,
  perPage = 50,
  onPageSizeChange,
  pageSizes = PAGE_SIZES,
}: {
  page: number;
  count: number;
  onChange: (page: number) => void;
  perPage?: number;
  onPageSizeChange?: (size: number) => void;
  pageSizes?: readonly number[];
}) {
  const total = Math.max(1, Math.ceil(count / perPage));
  const visiblePages = pageNumbers(page, total);
  const [jump, setJump] = useState("");
  const go = (value: number) => onChange(Math.min(total, Math.max(1, Math.floor(value))));
  const buttonClass =
    "grid size-7 place-items-center rounded text-12 text-secondary hover:bg-layer-1 disabled:opacity-30";
  return (
    <nav
      aria-label="分页"
      className="flex flex-wrap items-center justify-between gap-3 border-t border-subtle py-3 text-12 text-secondary"
    >
      <span>
        共 {count.toLocaleString()} 条
        {count > 0 ? ` · ${(page - 1) * perPage + 1}–${Math.min(page * perPage, count)}` : ""}
      </span>
      <div className="flex flex-wrap items-center justify-end gap-1.5">
        {onPageSizeChange && (
          <select
            aria-label="每页条数"
            value={perPage}
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
            className="mr-2 h-7 rounded border border-subtle bg-surface-1 px-2 text-12"
          >
            {pageSizes.map((size) => (
              <option key={size} value={size}>
                {size} 条/页
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          title="上一页"
          aria-label="上一页"
          className={buttonClass}
          disabled={page <= 1}
          onClick={() => go(page - 1)}
        >
          <ChevronLeft className="size-3.5" />
        </button>
        {visiblePages.map((value) =>
          typeof value === "string" ? (
            <span key={value} className="px-1">
              …
            </span>
          ) : (
            <button
              key={value}
              type="button"
              aria-label={`第 ${value} 页`}
              aria-current={page === value ? "page" : undefined}
              onClick={() => go(value)}
              className={`${buttonClass} ${page === value ? "bg-accent-subtle font-medium text-accent-primary" : ""}`}
            >
              {value}
            </button>
          )
        )}
        <button
          type="button"
          title="下一页"
          aria-label="下一页"
          className={buttonClass}
          disabled={page >= total}
          onClick={() => go(page + 1)}
        >
          <ChevronRight className="size-3.5" />
        </button>
        <label className="ml-2 flex items-center gap-1">
          跳至
          <input
            aria-label="跳转页码"
            type="number"
            min={1}
            max={total}
            value={jump}
            onChange={(event) => setJump(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                if (jump) go(Number(jump));
              }
            }}
            className="h-7 w-14 rounded border border-subtle bg-surface-1 px-2 text-center text-12"
          />
          页
        </label>
        <button
          type="button"
          disabled={!jump || !Number.isFinite(Number(jump))}
          className="rounded px-2 py-1 text-12 hover:bg-layer-1 disabled:opacity-30"
          onClick={() => {
            if (jump) go(Number(jump));
          }}
        >
          跳转
        </button>
      </div>
    </nav>
  );
}
