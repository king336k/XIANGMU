import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

type Props = {
  label: string;
  page: number;
  pageCount: number;
  from: number;
  to: number;
  total: number;
  initialCount: number;
  expanded: boolean;
  busy: boolean;
  onPage: (page: number) => Promise<void>;
  onExpand: (expanded: boolean) => Promise<void>;
};
export function KanbanColumnPagination({
  label,
  page,
  pageCount,
  from,
  to,
  total,
  initialCount,
  expanded,
  busy,
  onPage,
  onExpand,
}: Props) {
  const [jump, setJump] = useState("");
  useEffect(() => setJump(""), [page]);
  const buttonClass =
    "inline-flex size-6 items-center justify-center rounded border border-subtle text-secondary hover:bg-layer-1 disabled:opacity-40";
  return (
    <nav aria-label={`${label}栏分页`} className="mt-2 space-y-2 border-t border-subtle px-1 py-2 text-11">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-secondary">
          {from}–{to} / {total} 条
        </span>
        {initialCount < Math.min(total, 20) && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void onExpand(!expanded)}
            className="text-accent-primary hover:underline disabled:opacity-50"
          >
            {expanded ? `收起为${initialCount}条` : `展开为${Math.min(initialCount * 2, 20, total)}条`}
          </button>
        )}
      </div>
      {pageCount > 1 && (
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <button
            type="button"
            className={buttonClass}
            disabled={busy || page <= 1}
            aria-label="上一页"
            onClick={() => void onPage(page - 1)}
          >
            <ChevronLeft aria-hidden="true" className="size-3.5" />
          </button>
          <span className="min-w-10 text-center text-secondary tabular-nums">
            {page} / {pageCount}
          </span>
          <button
            type="button"
            className={buttonClass}
            disabled={busy || page >= pageCount}
            aria-label="下一页"
            onClick={() => void onPage(page + 1)}
          >
            <ChevronRight aria-hidden="true" className="size-3.5" />
          </button>
          <form
            className="ml-1 flex items-center gap-1"
            onSubmit={(event) => {
              event.preventDefault();
              if (Number(jump) > 0 && Number(jump) <= pageCount) void onPage(Number(jump));
            }}
          >
            <input
              type="number"
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
              disabled={busy || !jump || Number(jump) < 1 || Number(jump) > pageCount}
              className="rounded px-1 py-1 text-secondary hover:text-primary disabled:opacity-40"
            >
              跳转
            </button>
          </form>
        </div>
      )}
    </nav>
  );
}
