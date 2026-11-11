// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useState } from "react";

export function useCollectionPagination<T>(scope: string, collection?: T[], initialSize = 50) {
  const [state, setState] = useState({ scope, page: 1, perPage: initialSize });
  useEffect(() => {
    setState((current) => (current.scope === scope ? current : { ...current, scope, page: 1 }));
  }, [scope]);
  const perPage = state.perPage;
  const requestedPage = state.scope === scope ? state.page : 1;
  const page = collection
    ? Math.min(requestedPage, Math.max(1, Math.ceil(collection.length / perPage)))
    : requestedPage;
  const onChange = (next: number) => setState({ scope, perPage, page: Math.max(1, Math.floor(next)) });
  const onPageSizeChange = (size: number) => {
    if ([20, 25, 50, 100].includes(size)) setState({ scope, perPage: size, page: 1 });
  };
  return {
    page,
    perPage,
    query: new URLSearchParams({ page: String(page), per_page: String(perPage) }).toString(),
    rows: collection?.slice((page - 1) * perPage, page * perPage) ?? [],
    paging: { page, perPage, count: collection?.length ?? 0, onChange, onPageSizeChange },
  };
}
