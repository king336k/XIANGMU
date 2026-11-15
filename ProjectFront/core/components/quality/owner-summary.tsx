// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect } from "react";
import { useLocation, useSearchParams } from "react-router";
import useSWR from "swr";
import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { qualityApi, errorMessage } from "./api";
import { Modal, Paging, fieldClass } from "./shared";
import { Badge } from "./record-badge";
import {
  ownerKindNames,
  ownerRecordHref,
  ownerStatisticsQuery,
  ownerStatisticsScope,
  ownerStatusColors,
  ownerStatusNames,
} from "./owner-statistics";
import type { OwnerGroup, OwnerMetric, OwnerRecord } from "./owner-statistics";

type OwnerPage = {
  count: number;
  total: number;
  results: OwnerGroup[];
  ownership_basis: string;
  collaborative?: boolean;
};
type RecordPage = { count: number; results: OwnerRecord[] };
export function OwnerSummary({
  endpoint,
  source,
  params,
  metrics,
  onOpenRecord,
  detailsOnly = false,
  compact = false,
}: {
  endpoint: string;
  source: string;
  params: URLSearchParams;
  metrics: readonly OwnerMetric[];
  onOpenRecord?: (row: OwnerRecord) => void;
  detailsOnly?: boolean;
  compact?: boolean;
}) {
  const [route, setRoute] = useSearchParams(),
    location = useLocation();
  const scope = ownerStatisticsScope(endpoint, source, params);
  const scoped = route.get("owner_scope") === scope;
  const metric = compact
    ? metrics[0]
    : metrics.find((item) => item.key === (scoped ? route.get("owner_metric") : null)) || metrics[0];
  const ownerPage = Math.max(1, Number(scoped ? route.get("owner_page") : null) || 1),
    detailPage = Math.max(1, Number(scoped ? route.get("owner_detail_page") : null) || 1);
  const selectedId = scoped ? route.get("owner_id") : null,
    selectedStatus = route.get("owner_status") || undefined;
  const selected = selectedId ? { owner_id: selectedId, status: selectedStatus } : undefined;
  const summaryQuery = ownerStatisticsQuery(params, source, metric.key, ownerPage);
  const detailQuery = ownerStatisticsQuery(params, source, metric.key, detailPage, selected);
  const { data, error, mutate } = useSWR(detailsOnly ? null : `${endpoint}?${summaryQuery}`, (url: string) =>
    qualityApi.read<OwnerPage>(url)
  );
  const {
    data: detail,
    error: detailError,
    mutate: reloadDetail,
  } = useSWR(selected ? `${endpoint}?${detailQuery}` : null, (url: string) => qualityApi.read<RecordPage>(url));
  const update = (values: Record<string, string | null>) => {
    const next = new URLSearchParams(route);
    next.set("owner_scope", scope);
    for (const [key, value] of Object.entries(values)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setRoute(next, { replace: true, preventScrollReset: true });
  };
  const close = () => update({ owner_id: null, owner_status: null, owner_name: null, owner_detail_page: null });
  const show = (row: OwnerGroup, status?: string) =>
    update({ owner_id: row.owner_id, owner_name: row.name, owner_status: status || null, owner_detail_page: "1" });
  const ownerCount = data?.count;
  useEffect(() => {
    if (ownerCount !== undefined && ownerPage > 1 && (ownerPage - 1) * 10 >= ownerCount) {
      const next = new URLSearchParams(route);
      next.set("owner_scope", scope);
      next.set("owner_page", String(Math.max(1, Math.ceil(ownerCount / 10))));
      setRoute(next, { replace: true, preventScrollReset: true });
    }
  }, [ownerCount, ownerPage, route, scope, setRoute]);
  return (
    <section
      aria-label="人员事项统计"
      className={
        detailsOnly ? "" : compact ? "min-w-0 space-y-2" : "min-w-0 space-y-3 rounded-md border border-subtle p-4"
      }
    >
      {!detailsOnly && (
        <>
          {!compact && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-14 font-semibold">人员事项</h2>
              <select
                aria-label="人员统计指标"
                value={metric.key}
                className={`${fieldClass} !w-auto max-w-full`}
                onChange={(event) =>
                  update({
                    owner_metric: event.target.value,
                    owner_page: "1",
                    owner_id: null,
                    owner_status: null,
                    owner_name: null,
                    owner_detail_page: null,
                  })
                }
              >
                {metrics.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
          )}
          {error ? (
            <p role="alert" className="text-13 text-danger-primary">
              {errorMessage(error)}{" "}
              <button type="button" onClick={() => void mutate()} className="text-accent-primary">
                重试
              </button>
            </p>
          ) : !data ? (
            <p role="status" className="text-13 text-secondary">
              正在汇总…
            </p>
          ) : (
            <>
              <p className="text-12 text-secondary">
                共 {data.total} 条{data.collaborative ? " · 多人分别计入" : ""}
              </p>
              {!compact && (
                <details className="text-12 text-secondary">
                  <summary className="cursor-pointer">统计口径</summary>
                  <p className="mt-2">{data.ownership_basis}</p>
                </details>
              )}
              <div className="overflow-x-auto">
                <table className="w-full text-left text-12">
                  <thead>
                    <tr className="border-b border-subtle text-secondary">
                      <th className="p-2 font-medium">姓名</th>
                      <th className="p-2 font-medium">事项数</th>
                      <th className="p-2 font-medium">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.results.map((row) => (
                      <tr key={row.owner_id} className="border-b border-subtle">
                        <td className="p-2">
                          <button
                            type="button"
                            onClick={() => show(row)}
                            className="text-accent-primary hover:underline"
                          >
                            {row.name || "未指派"}
                          </button>
                          {!row.active && row.owner_id !== "unassigned" && (
                            <span className="ml-1 text-tertiary">已离任/停用</span>
                          )}
                        </td>
                        <td className="p-2">
                          <button
                            type="button"
                            onClick={() => show(row)}
                            aria-label={`${row.name} · 全部 ${row.count}条`}
                            className="font-semibold text-accent-primary tabular-nums hover:underline"
                          >
                            {row.count}
                          </button>
                        </td>
                        <td className="p-2">
                          <div className="flex flex-wrap gap-2">
                            {row.statuses?.map((item) => (
                              <button
                                key={item.status}
                                type="button"
                                onClick={() => show(row, item.status)}
                                aria-label={`${row.name} · ${ownerStatusNames[item.status] || item.status} ${item.count}条`}
                                className={`rounded border border-subtle px-2 py-1 tabular-nums hover:bg-layer-1 ${ownerStatusColors[item.status] || "text-secondary"}`}
                              >
                                {ownerStatusNames[item.status] || item.status} {item.count}
                              </button>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!data.count && (
                <p role="status" className="py-3 text-13 text-secondary">
                  暂无事项。
                </p>
              )}
              {data.count > 10 && (
                <Paging
                  page={ownerPage}
                  perPage={10}
                  count={data.count}
                  onChange={(value) => update({ owner_page: String(value) })}
                />
              )}
            </>
          )}
        </>
      )}
      {selected && (
        <Modal
          title={`${route.get("owner_name") || "人员"} · ${metric.label}${selectedStatus ? ` · ${ownerStatusNames[selectedStatus] || selectedStatus}` : ""}`}
          width="wide"
          onClose={close}
        >
          {detailError ? (
            <p role="alert" className="text-13 text-danger-primary">
              {errorMessage(detailError)}{" "}
              <button type="button" onClick={() => void reloadDetail()}>
                重试
              </button>
            </p>
          ) : !detail ? (
            <p role="status">正在读取明细…</p>
          ) : (
            <>
              <p className="text-12 text-secondary">共 {detail.count} 条</p>
              <ul className="divide-y divide-subtle">
                {detail.results.map((row) => (
                  <li key={`${row.kind}:${row.id}`} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-13 break-words">{row.title}</p>
                      <p className="mt-1 text-12 text-secondary">
                        {row.project_name} · {ownerKindNames[row.kind] || "事项"}
                      </p>
                    </div>
                    <Badge value={row.status} label={ownerStatusNames[row.status] || row.status} />
                    {onOpenRecord ? (
                      <button
                        type="button"
                        className="text-12 text-accent-primary hover:underline"
                        onClick={() => onOpenRecord(row)}
                      >
                        查看
                      </button>
                    ) : (
                      ownerRecordHref(row.url, location.pathname + location.search) && (
                        <Link
                          to={ownerRecordHref(row.url, location.pathname + location.search)}
                          state={{ returnTo: location.pathname + location.search }}
                          className="text-12 text-accent-primary hover:underline"
                        >
                          查看
                        </Link>
                      )
                    )}
                  </li>
                ))}
              </ul>
              {!detail.count && <p className="py-3 text-13 text-secondary">暂无事项。</p>}
              <Paging
                page={detailPage}
                perPage={20}
                count={detail.count}
                onChange={(value) => update({ owner_detail_page: String(value) })}
              />
            </>
          )}
        </Modal>
      )}
    </section>
  );
}
