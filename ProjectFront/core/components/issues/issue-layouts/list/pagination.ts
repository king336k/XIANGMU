import { boardPageWindow } from "../kanban/arrangement";

export const LIST_PAGE_SIZES = [10, 20, 50] as const;

export function normalizeListPageSize(value: unknown, grouped: boolean): number {
  return typeof value === "number" && (LIST_PAGE_SIZES as readonly number[]).includes(value)
    ? value
    : grouped
      ? 10
      : 20;
}

export function listPageSizeKey(userId: string, path: string, storeType: string, groupBy?: string | null) {
  return `list-page-size:${[userId, path, storeType, groupBy || "none"].map(encodeURIComponent).join(":")}`;
}

export function listPageWindow(ids: string[], total: number, grouped: boolean, page: number, pageSize?: number) {
  return boardPageWindow(ids, total, normalizeListPageSize(pageSize, grouped), false, page);
}

type ListSnapshot = { ids: string[]; total: number; hasMore: boolean };

/** Cursor APIs require filling intervening batches, but only for the requested group/page. */
export async function loadListPage(
  requestedPage: number,
  grouped: boolean,
  snapshot: () => ListSnapshot,
  loadMore: () => Promise<unknown>,
  pageSize?: number
): Promise<ReturnType<typeof listPageWindow>> {
  const data = snapshot();
  const window = listPageWindow(data.ids, data.total, grouped, requestedPage, pageSize);
  if (!window.needsFetch) return window;
  if (!data.hasMore) throw new Error("加载未完成，请重试");
  const loaded = data.ids.length;
  await loadMore();
  if (snapshot().ids.length <= loaded) throw new Error("加载未完成，请重试");
  return loadListPage(requestedPage, grouped, snapshot, loadMore, pageSize);
}
