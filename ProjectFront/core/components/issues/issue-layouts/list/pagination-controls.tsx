import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { LIST_PAGE_SIZES } from "./pagination";

type Props = {
  label: string;
  page: number;
  pageCount: number;
  from: number;
  to: number;
  total: number;
  busy: boolean;
  error: boolean;
  onPage: (page: number) => Promise<void>;
  onRetry: () => Promise<void>;
  pageSize?: number;
  onPageSizeChange?: (size: number) => void;
};
export function ListPagination({
  label,
  page,
  pageCount,
  from,
  to,
  total,
  busy,
  error,
  onPage,
  onRetry,
  pageSize = 10,
  onPageSizeChange,
}: Props) {
  const [jump, setJump] = useState("");
  useEffect(() => setJump(""), [page]);
  const requested = Number(jump);
  const validJump = Number.isInteger(requested) && requested >= 1 && requested <= pageCount;
  const buttonClass =
    "inline-flex h-6 items-center justify-center gap-1 rounded border border-subtle px-1.5 text-secondary hover:bg-layer-1 disabled:opacity-40";
  return (
    <nav
      aria-label={`${label}列表分页`}
      className="flex min-h-9 flex-wrap items-center justify-end gap-2 border-t border-subtle px-3 py-1.5 text-11"
    >
      <span className="mr-auto text-secondary tabular-nums">
        {from}–{to} / {total} 条
      </span>
      {busy && (
        <span role="status" className="text-tertiary">
          加载中…
        </span>
      )}
      {error && (
        <span role="alert" className="text-danger-primary">
          加载失败，当前页已保留。
          <button type="button" disabled={busy} onClick={() => void onRetry()} className="ml-1 underline">
            重试
          </button>
        </span>
      )}
      {onPageSizeChange && (
        <label className="flex items-center gap-1 text-secondary">
          每页
          <select
            aria-label="列表每页条数"
            title="适用于当前列表的所有分组"
            value={pageSize}
            disabled={busy}
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
            className="h-6 rounded border border-subtle bg-surface-1 px-1 text-11 text-primary"
          >
            {LIST_PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size} 条
              </option>
            ))}
          </select>
        </label>
      )}
      {pageCount > 1 && (
        <>
          <button
            type="button"
            aria-label="上一页"
            className={buttonClass}
            disabled={busy || page <= 1}
            onClick={() => void onPage(page - 1)}
          >
            <ChevronLeft aria-hidden="true" className="size-3" />
          </button>
          <span className="text-secondary tabular-nums">
            第 {page} / {pageCount} 页
          </span>
          <button
            type="button"
            aria-label="下一页"
            className={buttonClass}
            disabled={busy || page >= pageCount}
            onClick={() => void onPage(page + 1)}
          >
            <ChevronRight aria-hidden="true" className="size-3" />
          </button>
          <form
            className="flex items-center gap-1"
            onSubmit={(event) => {
              event.preventDefault();
              if (validJump) void onPage(requested);
            }}
          >
            <input
              type="number"
              step={1}
              min={1}
              max={pageCount}
              value={jump}
              onChange={(event) => setJump(event.target.value)}
              aria-label="跳转页码"
              placeholder="页码"
              disabled={busy}
              className="h-6 w-12 rounded border border-subtle bg-surface-1 px-1 text-center text-11 text-primary"
            />
            <button
              type="submit"
              disabled={busy || !validJump}
              className="px-1 text-secondary hover:text-primary disabled:opacity-40"
            >
              跳转
            </button>
          </form>
        </>
      )}
    </nav>
  );
}
