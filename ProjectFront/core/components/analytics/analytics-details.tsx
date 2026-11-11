// SPDX-License-Identifier: AGPL-3.0-only
import useSWR from "swr";
import { useParams } from "next/navigation";
import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { Modal, Paging } from "@/components/quality/shared";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { useCollectionPagination } from "@/components/quality/use-collection-pagination";

type DetailRow = { id: string; title: string; kind: string; subtitle: string; url: string };
export function AnalyticsDetails({
  title,
  metric,
  filters,
  isPeekView,
  onClose,
}: {
  title: string;
  metric: string;
  filters: Record<string, string>;
  isPeekView?: boolean;
  onClose: () => void;
}) {
  const { workspaceSlug } = useParams();
  const paging = useCollectionPagination(`${workspaceSlug}:${metric}:${JSON.stringify(filters)}`, undefined, 20);
  const project = isPeekView ? filters.project_ids?.split(",")[0] : undefined;
  const base = `/api/workspaces/${workspaceSlug}${project ? `/projects/${project}` : ""}/advance-analytics/`;
  const query = new URLSearchParams({
    ...filters,
    detail: metric,
    tab: metric.endsWith("work_items") ? "work-items" : "overview",
    page: String(paging.page),
    per_page: String(paging.perPage),
  });
  const { data, error, isLoading, mutate } = useSWR(`${base}?${query}`, (url: string) =>
    qualityApi.read<{ count: number; results: DetailRow[] }>(url)
  );
  return (
    <Modal title={title} width="wide" onClose={onClose}>
      {isLoading ? (
        <p role="status" className="py-5 text-13 text-secondary">
          正在读取明细…
        </p>
      ) : error ? (
        <div role="alert" className="space-y-3 text-13">
          <p className="text-danger-primary">{errorMessage(error)}</p>
          <button type="button" className="text-accent-primary" onClick={() => void mutate()}>
            重试
          </button>
        </div>
      ) : data ? (
        <>
          <p className="text-12 text-secondary">共 {data.count} 条</p>
          <ul className="divide-y divide-subtle">
            {data.results.map((row) => (
              <li key={row.id}>
                <Link
                  to={row.url}
                  className="focus-visible:outline-accent-primary flex min-w-0 items-center justify-between gap-3 rounded p-3 text-13 hover:bg-layer-1"
                >
                  <span className="min-w-0">
                    <span className="platform-record-link break-words">{row.title}</span>
                    <span className="mt-1 block text-12 text-secondary">{row.subtitle}</span>
                  </span>
                  <span className="shrink-0 text-12 text-secondary">{row.kind} →</span>
                </Link>
              </li>
            ))}
          </ul>
          {!data.count && (
            <p role="status" className="py-6 text-13 text-secondary">
              此范围没有记录。
            </p>
          )}
          <Paging {...paging.paging} count={data.count} />
        </>
      ) : null}
    </Modal>
  );
}
