// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "./api";
import { fieldClass, Paging } from "./shared";
import type { Page } from "./types";
import { useCollectionPagination } from "./use-collection-pagination";

type Props<T extends { id: string; code?: string }> = {
  url: string;
  name: string;
  placeholder: string;
  getLabel: (row: T) => string;
  isAllowed?: (row: T) => boolean;
  defaultValue?: string;
  defaultLabel?: string;
  required?: boolean;
  searchLabel?: string;
};
export function PagedRecordSelect<T extends { id: string; code?: string }>({
  url,
  name,
  placeholder,
  getLabel,
  isAllowed,
  defaultValue = "",
  defaultLabel = "已选记录",
  required = true,
  searchLabel,
}: Props<T>) {
  const [search, setSearch] = useState("");
  const [selection, setSelection] = useState<{ url: string; id: string; label: string } | undefined>(
    defaultValue ? { url, id: defaultValue, label: defaultLabel } : undefined
  );
  const selected = selection?.url === url ? selection : undefined;
  const pagination = useCollectionPagination(`${url}:${search}`);
  const query = new URLSearchParams(pagination.query);
  if (search) query.set("search", search);
  const { data, error } = useSWR(`${url}${url.includes("?") ? "&" : "?"}${query}`, (path: string) =>
    qualityApi.read<Page<T>>(path)
  );
  const rows = data?.results.filter((row) => !isAllowed || isAllowed(row)) ?? [];
  return (
    <div className="space-y-2">
      <input
        type="search"
        aria-label={searchLabel || `搜索${placeholder}`}
        placeholder="搜索编号或标题"
        value={search}
        maxLength={160}
        onChange={(event) => setSearch(event.target.value)}
        className={fieldClass}
      />
      <select
        required={required}
        name={name}
        value={selected?.id ?? ""}
        onChange={(event) => {
          const row = rows.find((item) => item.id === event.target.value);
          setSelection(
            row ? { url, id: row.id, label: [row.code, getLabel(row)].filter(Boolean).join(" · ") } : undefined
          );
        }}
        className={fieldClass}
      >
        <option value="">{placeholder}</option>
        {selected && !rows.some((row) => row.id === selected.id) && (
          <option value={selected.id}>{selected.label}（已选）</option>
        )}
        {rows.map((row) => (
          <option key={row.id} value={row.id}>
            {[row.code, getLabel(row)].filter(Boolean).join(" · ")}
          </option>
        ))}
      </select>
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {data && <Paging {...pagination.paging} count={data.count} />}
    </div>
  );
}
