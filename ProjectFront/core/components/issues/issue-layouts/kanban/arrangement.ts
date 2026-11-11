export type BoardLayout = "horizontal" | "two-columns" | "single-column" | "custom-rows";
export type BoardArrangement = {
  layout: BoardLayout;
  order: string[];
  rowStarts?: string[];
  initialCounts?: Partial<Record<BoardLayout, number>>;
};
export const BOARD_INITIAL_COUNTS = [5, 8, 10, 15, 20] as const;

export function normalizeBoardArrangement(value: unknown): BoardArrangement {
  const data = value && typeof value === "object" ? (value as Partial<BoardArrangement>) : {};
  const initialCounts = Object.fromEntries(
    ["horizontal", "two-columns", "single-column", "custom-rows"].flatMap((layout) => {
      const count = data.initialCounts?.[layout as BoardLayout];
      return typeof count === "number" && (BOARD_INITIAL_COUNTS as readonly number[]).includes(count)
        ? [[layout, count]]
        : [];
    })
  );
  return {
    ...(Object.keys(initialCounts).length ? { initialCounts } : {}),
    ...(Array.isArray(data.rowStarts)
      ? { rowStarts: [...new Set(data.rowStarts.filter((id): id is string => typeof id === "string"))] }
      : {}),
    layout:
      data.layout === "two-columns" || data.layout === "single-column" || data.layout === "custom-rows"
        ? data.layout
        : "horizontal",
    order: Array.isArray(data.order)
      ? [...new Set(data.order.filter((id): id is string => typeof id === "string"))]
      : [],
  };
}
export function boardArrangementKey(userId: string, path: string, groupBy: string) {
  return `project-board:${encodeURIComponent(userId)}:${encodeURIComponent(path)}:${encodeURIComponent(groupBy)}`;
}
export function orderedBoardGroups<T extends { id: string }>(groups: T[], order: string[]): T[] {
  const byId = new Map(groups.map((group) => [group.id, group]));
  const ids = [...new Set([...order, ...groups.map((group) => group.id)])];
  return ids.flatMap((id) => {
    const group = byId.get(id);
    return group ? [group] : [];
  });
}
export function moveBoardGroup(ids: string[], source: string, target: string): string[] {
  const from = ids.indexOf(source),
    to = ids.indexOf(target);
  if (from < 0 || to < 0 || from === to) return [...ids];
  const next = [...ids];
  next.splice(from, 1);
  next.splice(to, 0, source);
  return next;
}
export function canDropBoardGroup(data: Record<string, unknown>, key: string, target: string): boolean {
  return (
    data.type === "KANBAN_COLUMN" &&
    data.boardKey === key &&
    typeof data.columnId === "string" &&
    data.columnId !== target
  );
}
export function boardLoadState(loaded: number, total: number, next: boolean | undefined) {
  return { loaded, total, hasMore: next === undefined ? loaded < total : next };
}

export function boardInitialCount(value: Partial<BoardArrangement>): number {
  const layout = value.layout || "horizontal";
  const preferred = value.initialCounts?.[layout];
  if (preferred && (BOARD_INITIAL_COUNTS as readonly number[]).includes(preferred)) return preferred;
  return 5;
}
export function boardCardWindow(ids: string[], total: number, initial: number, expanded: number) {
  const limit = Math.max(1, initial) + Math.max(0, expanded);
  const visibleIds = ids.slice(0, limit);
  return {
    visibleIds,
    remaining: Math.max(0, total - visibleIds.length),
    needsFetch: visibleIds.length < Math.min(total, limit),
  };
}

export function boardPageWindow(
  ids: string[],
  total: number,
  initial: number,
  expanded: boolean,
  requestedPage: number
) {
  const pageSize = expanded ? Math.min(initial * 2, 20) : initial;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(pageCount, Math.max(1, Number.isFinite(requestedPage) ? Math.trunc(requestedPage) : 1));
  const offset = (page - 1) * pageSize;
  const window = boardCardWindow(ids.slice(offset), Math.max(0, total - offset), pageSize, 0);
  return {
    visibleIds: window.visibleIds,
    needsFetch: window.needsFetch,
    page,
    pageCount,
    pageSize,
    from: total ? offset + 1 : 0,
    to: Math.min(total, offset + window.visibleIds.length),
  };
}

export type BoardDropPlacement = "before" | "after" | "above" | "below";
export function insertBoardGroup(ids: string[], source: string, target: string, placement: "before" | "after") {
  if (source === target || !ids.includes(source) || !ids.includes(target)) return [...ids];
  const next = ids.filter((id) => id !== source);
  next.splice(next.indexOf(target) + (placement === "after" ? 1 : 0), 0, source);
  return next;
}
export function boardRows(ids: string[], rowStarts: string[]): string[][] {
  const rows: string[][] = [];
  for (const id of ids) {
    if (!rows.length || rowStarts.includes(id)) rows.push([]);
    rows[rows.length - 1].push(id);
  }
  return rows;
}
export function boardLayoutRows(ids: string[], layout: BoardLayout, rowStarts: string[] = []) {
  if (layout === "custom-rows") return boardRows(ids, rowStarts);
  const size = layout === "two-columns" ? 2 : layout === "single-column" ? 1 : Math.max(1, ids.length);
  return Array.from({ length: Math.ceil(ids.length / size) }, (_, index) =>
    ids.slice(index * size, (index + 1) * size)
  );
}
export function placeBoardGroup(
  ids: string[],
  rowStarts: string[],
  source: string,
  target: string,
  placement: BoardDropPlacement,
  layout: BoardLayout
): Partial<BoardArrangement> & { order: string[]; rowStarts: string[]; layout: BoardLayout } {
  const rows = boardLayoutRows(ids, layout, rowStarts);
  const rowIndex = rows.findIndex((row) => row.includes(target));
  if (!ids.includes(source) || rowIndex < 0) return { layout, order: ids, rowStarts };
  if ((placement === "before" || placement === "after") && layout === "horizontal")
    return { layout, order: insertBoardGroup(ids, source, target, placement), rowStarts: [] };
  if ((placement === "before" || placement === "after") && source === target) return { layout, order: ids, rowStarts };
  const next = rows.map((row) => row.filter((id) => id !== source));
  if (placement === "above" || placement === "below")
    next.splice(rowIndex + (placement === "below" ? 1 : 0), 0, [source]);
  else next[rowIndex].splice(next[rowIndex].indexOf(target) + (placement === "after" ? 1 : 0), 0, source);
  const valid = next.filter((row) => row.length);
  return { layout: "custom-rows", order: valid.flat(), rowStarts: valid.slice(1).map((row) => row[0]) };
}
export function boardDropPlacement(
  start: { x: number; y: number },
  pointer: { x: number; y: number },
  target: { left: number; top: number; width: number; height: number }
): BoardDropPlacement {
  const dx = pointer.x - start.x,
    dy = pointer.y - start.y;
  if (Math.abs(dy) > 65 && Math.abs(dy) > Math.abs(dx) * 0.75) return dy > 0 ? "below" : "above";
  return pointer.x < target.left + target.width / 2 ? "before" : "after";
}

export function kanbanGroupingPatch(groupBy: string | null | undefined) {
  return groupBy ? undefined : { group_by: "state" as const, sub_group_by: null };
}
