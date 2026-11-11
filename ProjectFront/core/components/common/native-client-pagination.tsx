import { useState } from "react";
import { usePathname } from "next/navigation";
import { Paging } from "@/components/quality/shared";

export const NATIVE_PAGE_SIZES = [20, 50, 100] as const;

export function nativePageWindow<T>(items: readonly T[], requestedPage: number, requestedSize: number) {
  const perPage = (NATIVE_PAGE_SIZES as readonly number[]).includes(requestedSize) ? requestedSize : 20;
  const count = items.length;
  const pages = Math.max(1, Math.ceil(count / perPage));
  const page = Math.min(pages, Math.max(1, Number.isFinite(requestedPage) ? Math.trunc(requestedPage) : 1));
  return { items: items.slice((page - 1) * perPage, page * perPage), page, perPage, count };
}

/** Call after the existing search/filter/sort; scope changes reset the current page only. */
export function useNativeClientPagination<T>(items: readonly T[] | null | undefined, scope: string) {
  const path = usePathname();
  const scopeKey = JSON.stringify([path, scope]);
  const [state, setState] = useState({ scope: scopeKey, page: 1, perPage: 20 });
  const window = nativePageWindow(items ?? [], state.scope === scopeKey ? state.page : 1, state.perPage);
  return {
    ...window,
    onChange: (page: number) => setState({ scope: scopeKey, page, perPage: window.perPage }),
    onPageSizeChange: (perPage: number) => setState({ scope: scopeKey, page: 1, perPage }),
    pageSizes: NATIVE_PAGE_SIZES,
  };
}

export function NativeClientPagination({
  label,
  pagination,
}: {
  label: string;
  pagination: ReturnType<typeof useNativeClientPagination>;
}) {
  if (!pagination.count) return null;
  return (
    <div aria-label={`${label}分页`} className="w-full shrink-0">
      <Paging {...pagination} />
    </div>
  );
}
