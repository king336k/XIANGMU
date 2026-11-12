// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { renderNumericDateTime } from "@plane/utils";
import { Modal, Paging } from "./shared";
import { Badge } from "./record-badge";
import { qualityApi, errorMessage } from "./api";
import { defectDisplayTitle, severityNames } from "./types";
import type { Defect, Page } from "./types";

export type DefectStatisticSelection = { title: string; filters?: Record<string, string>; expectedCount?: number };
export function defectStatisticsFilters(params: URLSearchParams) {
  const result = new URLSearchParams(params);
  for (const key of ["page", "per_page", "tab", "panel", "layout", "saved_view", "defect", "create", "case", "plan"])
    result.delete(key);
  return result;
}
const latest = (values: (string | null | undefined)[]) =>
  values.reduce<string | undefined>(
    (selected, value) => (value && (!selected || value > selected) ? value : selected),
    undefined
  );
const earliest = (values: (string | null | undefined)[]) =>
  values.reduce<string | undefined>(
    (selected, value) => (value && (!selected || value < selected) ? value : selected),
    undefined
  );

export function defectStatisticsDetailQuery(
  params: URLSearchParams,
  selection: DefectStatisticSelection,
  page: number
) {
  const query = defectStatisticsFilters(params);
  let empty = false;
  for (const [key, value] of Object.entries(selection.filters || {})) {
    if (["created_after", "created_before"].includes(key)) continue;
    if (key === "exclude_status") {
      if (!query.getAll(key).includes(value)) query.append(key, value);
    } else {
      if (query.has(key) && query.get(key) !== value) empty = true;
      query.set(key, value);
    }
  }
  // Date strings are China calendar days validated by the API; lexical intersections preserve that boundary.
  const after = latest([query.get("created_after"), query.get("start"), selection.filters?.created_after]);
  const before = earliest([query.get("created_before"), query.get("end"), selection.filters?.created_before]);
  query.delete("start");
  query.delete("end");
  if (after) query.set("created_after", after);
  if (before) query.set("created_before", before);
  if (after && before && after > before) empty = true;
  query.set("page", String(page));
  query.set("per_page", "50");
  return { query, empty };
}
export function DefectStatisticsDetails({
  base,
  params,
  selection,
  onClose,
  onOpenDefect,
}: {
  base: string;
  params: URLSearchParams;
  selection: DefectStatisticSelection;
  onClose: () => void;
  onOpenDefect?: (id: string) => void;
}) {
  const [page, setPage] = useState(1);
  const { query, empty } = defectStatisticsDetailQuery(params, selection, page);
  const { data, error, mutate } = useSWR(empty ? null : `${base}defects/?${query}`, (url: string) =>
    qualityApi.read<Page<Defect>>(url)
  );
  const rows = empty ? [] : data?.results;
  const count = empty ? 0 : data?.count;
  return (
    <Modal title={`${selection.title} · 缺陷明细`} width="wide" onClose={onClose}>
      {error ? (
        <div role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
          <button type="button" className="ml-3 text-accent-primary" onClick={() => void mutate()}>
            重试
          </button>
        </div>
      ) : !rows ? (
        <p role="status">正在读取缺陷…</p>
      ) : (
        <>
          <p className="text-12 text-secondary">
            共 {count} 条
            {selection.expectedCount !== undefined && count !== selection.expectedCount
              ? ` · 当前数据已更新，统计时为 ${selection.expectedCount} 条`
              : ""}
          </p>
          <div className="overflow-x-auto rounded-md border border-subtle">
            <table className="w-full text-left text-13">
              <thead>
                <tr className="border-b border-subtle text-secondary">
                  <th className="p-3">编号与标题</th>
                  <th className="p-3">状态</th>
                  <th className="p-3">严重程度</th>
                  <th className="p-3">负责人</th>
                  <th className="p-3">创建时间</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-b border-subtle">
                    <td className="p-3">
                      <button
                        type="button"
                        className="text-left text-accent-primary hover:underline disabled:text-primary"
                        disabled={!onOpenDefect}
                        onClick={() => {
                          onClose();
                          onOpenDefect?.(row.id);
                        }}
                      >
                        <span className="mr-2 text-12 whitespace-nowrap">{row.code}</span>
                        {defectDisplayTitle(row.title)}
                      </button>
                    </td>
                    <td className="p-3">
                      <Badge value={row.status} />
                    </td>
                    <td className="p-3">
                      <Badge value={row.severity} label={severityNames[row.severity]} variant="plain" />
                    </td>
                    <td className="p-3">{row.assignee_name || "未分派"}</td>
                    <td className="p-3 text-12 whitespace-nowrap text-secondary">
                      {row.created_at ? renderNumericDateTime(row.created_at) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!rows.length && <p className="p-4 text-13 text-secondary">当前范围暂无匹配缺陷。</p>}
          </div>
          <Paging page={page} perPage={50} count={count || 0} onChange={setPage} />
        </>
      )}
    </Modal>
  );
}
