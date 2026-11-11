import { sourceRoleLabel, sourceStatusLabel } from "./source-labels";
import { useCollectionPagination } from "./use-collection-pagination";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Modal, Paging } from "./shared";
import type { Page } from "./types";

type Catalog = {
  id: string;
  source_instance: string;
  source_project: { name: string; status: string };
  synced_at: string;
  task_count: number;
  members: { userId: number; displayName: string; active: boolean; userRole: string }[];
  tasks: {
    id: string;
    external_id: number;
    name: string;
    source_status: string;
    active: boolean;
    issue_id: string | null;
    issue_state: string;
  }[];
};
type Source = { id: string; source_instance: string; active: boolean; external_project_id?: number; name?: string };

export function CatalogPanel({
  base,
  sources,
  onSynced,
  canImport,
}: {
  base: string;
  sources: Source[];
  onSynced: () => Promise<unknown>;
  canImport: boolean;
}) {
  const { mutate: invalidate } = useSWRConfig();
  const { data, error, mutate } = useSWR(`${base}integrations/catalog/`, (url: string) =>
    qualityApi.read<{ results: Catalog[] }>(url)
  );
  const catalogPagination = useCollectionPagination(`${base}:catalogs`, data?.results);
  const sourcePagination = useCollectionPagination(
    `${base}:catalog-sources`,
    sources.filter((source) => source.active),
    20
  );
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [selection, setSelection] = useState<{ source: string; project?: number; full: boolean }>(),
    [pendingTask, setPendingTask] = useState<Catalog["tasks"][number]>();
  const synchronize = async () => {
    if (!selection) return;
    const result = await qualityApi.write<{ task_changes: number; revoked_identities: number }>(
      `${base}integrations/catalog/`,
      {
        source_instance: selection.source,
        ...(selection.project ? { external_project_id: selection.project } : {}),
        full: selection.full,
      }
    );
    setMessage(`目录同步完成：更新${result.task_changes}条任务，撤销${result.revoked_identities}项已失效的外部身份。`);
    await mutate();
    await onSynced();
  };
  return (
    <section className="space-y-3 border-t border-subtle pt-5">
      <h3 className="text-14 font-medium">来源项目与任务目录</h3>
      <p className="text-12 text-secondary">可将来源任务转为工作项，状态在本平台维护。来源停用后，对应授权随之失效。</p>
      {(message || error) && (
        <p role="status" className="text-13">
          {message || errorMessage(error)}
        </p>
      )}
      {sourcePagination.rows.map((source) => (
        <div key={source.id} className="flex flex-wrap items-center gap-2 text-12">
          <span>
            {source.name || "数据管理平台项目"} · 编号 {source.external_project_id}
          </span>
          <Button
            variant="neutral-primary"
            disabled={busy}
            onClick={() =>
              setSelection({ source: source.source_instance, project: source.external_project_id, full: false })
            }
          >
            增量同步目录
          </Button>
          <Button
            variant="neutral-primary"
            disabled={busy}
            onClick={() =>
              setSelection({ source: source.source_instance, project: source.external_project_id, full: true })
            }
          >
            完整核对目录
          </Button>
        </div>
      ))}
      {sourcePagination.paging.count > 20 && <Paging {...sourcePagination.paging} />}
      {!data?.results.length && (
        <p className="text-12 text-secondary">尚无同步快照；先配置数据平台连接和项目映射，再同步。</p>
      )}
      {catalogPagination.rows.map((catalog) => (
        <div key={catalog.id} className="space-y-3 rounded border border-subtle p-3">
          <p className="text-13 font-medium">
            {catalog.source_project.name} · {catalog.source_instance} · 来源状态{" "}
            {catalog.source_project.status ? sourceStatusLabel(catalog.source_project.status) : "未提供"}
          </p>
          <p className="text-12 text-secondary">
            最近同步：{renderNumericDateTime(catalog.synced_at)} · {catalog.task_count}条来源任务
            {catalog.task_count > catalog.tasks.length && `，当前显示前${catalog.tasks.length}条`}
          </p>
          <CatalogTasks base={base} catalog={catalog} canImport={canImport} onImport={setPendingTask} />
          <details className="text-12 text-secondary">
            <summary className="cursor-pointer">来源成员（{catalog.members.length}）</summary>
            <p className="mt-2">按来源账号编号关联成员，项目权限由管理员设置。</p>
            {catalog.members.map((member) => (
              <p key={member.userId} className="mt-1">
                #{member.userId} {member.displayName} · {sourceRoleLabel(member.userRole)} ·{" "}
                {member.active ? "来源有效" : "来源已停用"}
              </p>
            ))}
          </details>
        </div>
      ))}
      {selection && (
        <Modal
          title={selection.full ? "完整核对来源目录" : "同步来源目录"}
          submitLabel="开始同步"
          onClose={() => setSelection(undefined)}
          onSubmit={async () => {
            setBusy(true);
            try {
              await synchronize();
            } finally {
              setBusy(false);
            }
          }}
        >
          <p className="text-13">
            将读取 {selection.source}{" "}
            的权威项目、任务和完整成员目录。已停用或不再属于该项目的外部身份会被停用；平台账号与本地任务内容保留。
            {selection.full ? "完整核对还会将来源已移除的任务标为失效。" : "任务使用最近完整快照的增量游标。"}
          </p>
        </Modal>
      )}
      {pendingTask && (
        <Modal
          title="转为平台工作项"
          submitLabel="创建工作项"
          onClose={() => setPendingTask(undefined)}
          onSubmit={async () => {
            await qualityApi.write(`${base}integrations/catalog/tasks/${pendingTask.id}/import/`, {});
            await mutate();
            await invalidate((key) => typeof key === "string" && key.startsWith(`${base}integrations/catalog/`));
          }}
        >
          <p className="text-13">
            将「{pendingTask.name}
            」创建为当前项目工作项，保留来源关系；重复操作不会重复创建。
          </p>
        </Modal>
      )}
      {data && <Paging {...catalogPagination.paging} />}
    </section>
  );
}

function CatalogTasks({
  base,
  catalog,
  canImport,
  onImport,
}: {
  base: string;
  catalog: Catalog;
  canImport: boolean;
  onImport: (task: Catalog["tasks"][number]) => void;
}) {
  const [search, setSearch] = useState(""),
    [query, setQuery] = useState("");
  const taskPagination = useCollectionPagination(`${base}:${catalog.id}:${query}`);
  const { data, error } = useSWR(
    `${base}integrations/catalog/${catalog.id}/tasks/?${taskPagination.query}&search=${encodeURIComponent(query)}`,
    (url: string) => qualityApi.read<Page<Catalog["tasks"][number]>>(url)
  );
  return (
    <section className="space-y-2">
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(search);
          taskPagination.paging.onChange(1);
        }}
      >
        <input
          aria-label="搜索来源任务"
          placeholder="搜索来源任务"
          value={search}
          maxLength={255}
          onChange={(event) => setSearch(event.target.value)}
          className="rounded border border-subtle bg-surface-1 px-3 py-2 text-12"
        />
        <Button type="submit" variant="neutral-primary">
          搜索
        </Button>
      </form>
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      <div className="max-h-96 overflow-auto">
        <table className="w-full text-left text-12">
          <thead>
            <tr className="border-b border-subtle">
              <th className="p-2">来源任务</th>
              <th className="p-2">来源状态</th>
              <th className="p-2">工作项</th>
            </tr>
          </thead>
          <tbody>
            {data?.results.map((task) => (
              <tr key={task.id} className="border-b border-subtle">
                <td className="p-2">
                  #{task.external_id} {task.name}
                </td>
                <td className="p-2">{task.active ? task.source_status || "有效" : "已失效"}</td>
                <td className="p-2">
                  {task.issue_id ? (
                    task.issue_state === "active" ? (
                      <a
                        className="text-accent-primary"
                        href={`${base.split("/quality/")[0].replace(/^\/api\/workspaces/, "")}/issues/${task.issue_id}/`}
                      >
                        打开工作项
                      </a>
                    ) : (
                      <span>
                        历史工作项{{ deleted: "已移除", archived: "已归档", moved: "已移动" }[task.issue_state]}
                        ，请先核对或恢复
                      </span>
                    )
                  ) : canImport ? (
                    <Button variant="neutral-primary" disabled={!task.active} onClick={() => onImport(task)}>
                      转为工作项
                    </Button>
                  ) : (
                    <span>由项目经理安排</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && <Paging {...taskPagination.paging} count={data.count} />}
    </section>
  );
}
