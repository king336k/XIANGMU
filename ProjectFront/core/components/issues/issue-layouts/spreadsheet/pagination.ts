import { boardPageWindow } from "../kanban/arrangement";

export const SPREADSHEET_PAGE_SIZES = [20, 50, 100] as const;

export function spreadsheetPageWindow(ids: string[], total: number, size: number, page: number) {
  const perPage = (SPREADSHEET_PAGE_SIZES as readonly number[]).includes(size) ? size : 20;
  return boardPageWindow(ids, total, perPage, false, page);
}

export async function loadSpreadsheetPage(
  page: number,
  size: number,
  snapshot: () => { ids: string[]; total: number; hasMore: boolean },
  loadMore: () => Promise<unknown>
): Promise<ReturnType<typeof spreadsheetPageWindow>> {
  const data = snapshot();
  const window = spreadsheetPageWindow(data.ids, data.total, size, page);
  if (!window.needsFetch) return window;
  if (!data.hasMore) throw new Error("加载未完成，请重试");
  const loaded = data.ids.length;
  await loadMore();
  if (snapshot().ids.length <= loaded) throw new Error("加载未完成，请重试");
  return loadSpreadsheetPage(page, size, snapshot, loadMore);
}
