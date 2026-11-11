import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useIssuesStore, useIssueStoreType } from "@/hooks/use-issue-layout-store";
import { useUser } from "@/hooks/store/user";
import { useIssuesActions } from "@/hooks/use-issues-actions";
import { loadSpreadsheetPage, spreadsheetPageWindow, SPREADSHEET_PAGE_SIZES } from "./pagination";

export function useSpreadsheetPagination(ids: string[], orderBy: unknown, totalCount?: number) {
  const { issues, issuesFilter } = useIssuesStore();
  const storeType = useIssueStoreType();
  const { fetchNextIssues } = useIssuesActions(storeType);
  const path = usePathname();
  const { data: user } = useUser();
  const storageKey = `spreadsheet-page-size:${user?.id || "anonymous"}:${path}:${storeType}`;
  const readSize = () => {
    try {
      const size = Number(JSON.parse(localStorage.getItem(storageKey) || "null"));
      return (SPREADSHEET_PAGE_SIZES as readonly number[]).includes(size) ? size : 20;
    } catch {
      return 20;
    }
  };
  const scope = JSON.stringify([storageKey, issuesFilter?.appliedFilters, orderBy]);
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const mounted = useRef(true);
  const requesting = useRef(false);
  const retryPage = useRef(1);
  const [state, setState] = useState({ scope, storageKey, page: 1, size: readSize() });
  const pageSize = state.storageKey === storageKey ? state.size : readSize();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const total = totalCount ?? issues.getGroupIssueCount(undefined, undefined, false) ?? ids.length;
  const pageWindow = spreadsheetPageWindow(ids, total, pageSize, state.scope === scope ? state.page : 1);
  const changePage = async (page: number) => {
    if (requesting.current || issues.getIssueLoader()) return;
    requesting.current = true;
    retryPage.current = page;
    setBusy(true);
    setError(false);
    const isCurrent = () => mounted.current && scopeRef.current === scope;
    try {
      const result = await loadSpreadsheetPage(
        page,
        pageSize,
        () => {
          const currentIds = issues.getIssueIds(undefined) ?? ids;
          const count = issues.getGroupIssueCount(undefined, undefined, false) ?? currentIds.length;
          const next = issues.getPaginationData(undefined, undefined)?.nextPageResults;
          return { ids: currentIds, total: count, hasMore: next === undefined ? currentIds.length < count : !!next };
        },
        () => {
          if (!isCurrent()) throw new Error("分页范围已变更");
          // Await the canonical action; some workspace wrappers are fire-and-forget callbacks.
          return fetchNextIssues(undefined);
        }
      );
      if (isCurrent()) setState({ scope, storageKey, page: result.page, size: pageSize });
    } catch {
      if (isCurrent()) setError(true);
    } finally {
      requesting.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  return {
    ...pageWindow,
    total,
    busy: busy || !!issues.getIssueLoader(),
    error,
    onPage: changePage,
    onRetry: () => changePage(retryPage.current),
    onPageSizeChange: (size: number) => {
      if (requesting.current || !(SPREADSHEET_PAGE_SIZES as readonly number[]).includes(size)) return;
      try {
        localStorage.setItem(storageKey, JSON.stringify(size));
      } catch {
        /* Keep the current session usable. */
      }
      setState({ scope, storageKey, page: 1, size });
      setError(false);
    },
    selectionScope: JSON.stringify([scope, pageSize, pageWindow.page]),
  };
}
