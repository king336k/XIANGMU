import { BOARD_INITIAL_COUNTS, boardInitialCount } from "./arrangement";
import { useBoardArrangement } from "./use-arrangement";
import type { BoardLayout } from "./arrangement";

export function KanbanArrangementControl({ groupBy }: { groupBy?: string | null }) {
  const { layout, order, initialCounts, update } = useBoardArrangement(groupBy);
  return (
    <div className="space-y-2 py-3">
      <label className="flex items-center justify-between gap-3 text-12">
        <span className="font-medium text-secondary">看板排列</span>
        <select
          aria-label="看板排列"
          value={layout}
          onChange={(event) => update({ layout: event.target.value as BoardLayout, rowStarts: [] })}
          className="rounded border border-subtle bg-surface-1 px-2 py-1 text-12 text-primary"
        >
          <option value="horizontal">横向并列</option>
          <option value="two-columns">每行两栏</option>
          <option value="single-column">上下单列</option>
          <option value="custom-rows">自由排列</option>
        </select>
      </label>
      <label className="flex items-center justify-between gap-3 text-12">
        <span className="font-medium text-secondary">每栏默认条数</span>
        <select
          aria-label="每栏默认条数"
          value={boardInitialCount({ layout, initialCounts })}
          onChange={(event) => update({ initialCounts: { ...initialCounts, [layout]: Number(event.target.value) } })}
          className="rounded border border-subtle bg-surface-1 px-2 py-1 text-12 text-primary"
        >
          {BOARD_INITIAL_COUNTS.map((count) => (
            <option key={count} value={count}>
              {count} 条
            </option>
          ))}
        </select>
      </label>
      {order.length > 0 && (
        <button
          type="button"
          className="text-11 text-accent-primary hover:underline"
          onClick={() => update({ order: [] })}
        >
          恢复默认栏顺序
        </button>
      )}
    </div>
  );
}
