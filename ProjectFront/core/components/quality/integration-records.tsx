import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { fieldClass, Paging } from "./shared";
import { useCollectionPagination } from "./use-collection-pagination";
import type { Page } from "./types";

export type IntegrationMapping = {
  id: string;
  source_instance: string;
  active: boolean;
  external_project_id?: number;
  external_user_id?: number;
  name?: string;
  task_id?: number;
  session_id?: string;
  package_id?: string;
  authority_configured?: boolean;
};
export function IntegrationRecords({
  base,
  kind,
  title,
  canManage,
  revision,
  onToggle,
}: {
  base: string;
  kind: "project" | "identity" | "binding";
  title: string;
  canManage: boolean;
  revision?: unknown;
  onToggle: (kind: string, row: IntegrationMapping) => Promise<void>;
}) {
  const [search, setSearch] = useState("");
  const pagination = useCollectionPagination(`${base}:${kind}:${search}`, undefined, 20);
  const query = new URLSearchParams(pagination.query);
  query.set("kind", kind);
  if (search) query.set("search", search);
  const { data, error, isLoading, mutate } = useSWR(
    [`${base}integrations/?${query}`, revision],
    ([url]: [string, unknown]) => qualityApi.read<Page<IntegrationMapping>>(url)
  );
  return (
    <section className="space-y-3" aria-label={title}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-14 font-medium">
          {title}
          {data && <span className="font-normal ml-2 text-12 text-secondary">{data.count}</span>}
        </h3>
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          aria-label={`搜索${title}`}
          placeholder={kind === "binding" ? "任务、Session或数据包编号" : "名称、来源或编号"}
          maxLength={160}
          className={`${fieldClass} max-w-xs`}
        />
      </div>
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error)}
          <button type="button" className="ml-2 text-accent-primary" onClick={() => void mutate()}>
            重试
          </button>
        </p>
      )}
      {isLoading && (
        <p role="status" className="text-12 text-secondary">
          正在读取…
        </p>
      )}
      {data?.results.map((row) => (
        <div
          key={row.id}
          className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded border border-subtle p-3 text-12"
        >
          <div className="min-w-0 flex-1 break-words">
            <p>
              {row.name ||
                (kind === "project"
                  ? "数据管理平台项目"
                  : kind === "identity"
                    ? `账号 ${row.external_user_id}`
                    : `任务 ${row.task_id}`)}
              {row.external_project_id ? ` · 项目编号 ${row.external_project_id}` : ""} · {row.source_instance}
            </p>
            {row.session_id && <p className="mt-1 break-all text-secondary">Session：{row.session_id}</p>}
            {row.package_id && <p className="mt-1 break-all text-secondary">数据包：{row.package_id}</p>}
            <p className="mt-1 text-secondary">
              {row.active ? "关联有效" : "已停用"}
              {row.authority_configured !== undefined
                ? ` · 核验连接${row.authority_configured ? "已设置" : "未设置"}`
                : ""}
            </p>
          </div>
          {canManage && (
            <Button
              variant="neutral-primary"
              onClick={async () => {
                await onToggle(kind, row);
                await mutate();
              }}
            >
              {row.active ? "停用关联" : "恢复关联"}
            </Button>
          )}
        </div>
      ))}
      {data && !data.count && <p className="text-12 text-secondary">{search ? "没有匹配记录" : "尚未配置"}</p>}
      {data && <Paging {...pagination.paging} count={data.count} />}
    </section>
  );
}
