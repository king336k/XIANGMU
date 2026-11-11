// SPDX-License-Identifier: AGPL-3.0-only
import useSWR from "swr";
import { useSearchParams } from "react-router";
import { qualityApi, errorMessage } from "./api";
import { AssetsPanel } from "./assets-panel";
import type { Release } from "./assets-panel";
import { ListFilters } from "./list-filters";
import { normalizedPageParams, pageSize } from "./pagination";
import { Paging } from "./shared";
import type { Context, Page } from "./types";

export function VersionAcceptancePanel({ base, context }: { base: string; context: Context }) {
  const [params, setParams] = useSearchParams();
  const query = normalizedPageParams(params);
  query.delete("tab");
  query.delete("display");
  query.delete("version");
  const { data, error, mutate } = useSWR(`${base}releases/?${query}`, (url: string) =>
    qualityApi.read<Page<Release>>(url)
  );
  const applyFilters = (filters: URLSearchParams) => {
    const next = new URLSearchParams(filters);
    next.set("tab", "acceptance");
    for (const key of ["version", "display"]) {
      if (params.has(key)) next.set(key, params.get(key)!);
    }
    setParams(next);
  };
  const update = (values: { page?: number; per_page?: number }) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) next.set(key, String(value));
    setParams(next);
  };
  return (
    <main className="min-h-0 flex-1 space-y-4 overflow-auto p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-16 font-semibold">发布验收</h2>
        <ListFilters compact kind="releases" context={context} params={query} onApply={applyFilters} />
      </div>
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {!data && !error && (
        <p role="status" className="text-13 text-secondary">
          正在读取发布验收…
        </p>
      )}
      {data && (
        <>
          <AssetsPanel
            base={base}
            kind="releases"
            rows={data.results}
            context={context}
            onSaved={async () => {
              await mutate();
            }}
          />
          <Paging
            page={Number(query.get("page"))}
            count={data.count}
            perPage={pageSize(params)}
            onChange={(page) => update({ page })}
            onPageSizeChange={(per_page) => update({ per_page, page: 1 })}
          />
        </>
      )}
    </main>
  );
}
