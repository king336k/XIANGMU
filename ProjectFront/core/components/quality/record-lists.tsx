import { reasonNames } from "./types";
import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only

import { Button } from "@plane/ui";
import { RecordLifecycleActions } from "./record-lifecycle-actions";
import { TableHeaderFilter } from "./table-header-filter";
import { Badge } from "./shared";
import { defectDisplayTitle, priorityNames, planStatusNames } from "./types";
import type { TestCase, Plan, Execution, Defect, Context } from "./types";
export function CaseList({
  rows,
  projectUrl,
  canWrite,
  onEdit,
  onCopy,
  selected = [],
  onSelection,
  onHistory,
  onView,
  base,
  onSaved,
  context,
}: {
  rows: TestCase[];
  projectUrl: string;
  canWrite: boolean;
  onEdit: (value: TestCase) => void;
  onCopy: (value: TestCase) => void;
  selected?: TestCase[];
  onSelection?: (rows: TestCase[]) => void;
  onHistory?: (value: TestCase) => void;
  onView?: (value: TestCase) => void;
  base?: string;
  onSaved?: () => Promise<unknown>;
  context?: Context;
}) {
  return (
    <div className="overflow-x-auto rounded-md border border-subtle">
      <table className="w-full min-w-[600px] text-left text-13">
        <thead className="border-b border-subtle bg-layer-1 text-12 text-secondary">
          <tr>
            {onSelection && (
              <th className="w-10 p-3">
                <input
                  type="checkbox"
                  aria-label="选择本页用例"
                  checked={rows.length > 0 && rows.every((row) => selected.some((item) => item.id === row.id))}
                  onChange={(event) => {
                    const ids = new Set(rows.map((row) => row.id));
                    onSelection(
                      event.target.checked
                        ? [...selected.filter((row) => !ids.has(row.id)), ...rows]
                        : selected.filter((row) => !ids.has(row.id))
                    );
                  }}
                />
              </th>
            )}
            <th className="p-3">
              <TableHeaderFilter label="用例名称" kind="cases" context={context} />
            </th>
            <th className="p-3">
              <TableHeaderFilter label="模块" kind="cases" context={context} />
            </th>
            <th className="p-3">
              <TableHeaderFilter label="优先级" kind="cases" context={context} />
            </th>
            <th className="p-3">
              <TableHeaderFilter label="关联工作项" kind="cases" context={context} />
            </th>
            <th className="p-3">
              <TableHeaderFilter label="版本" kind="cases" context={context} />
            </th>
            <th className="p-3">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-subtle">
          {!rows.length && (
            <tr>
              <td colSpan={onSelection ? 7 : 6} className="p-6 text-center text-13 text-secondary" role="status">
                没有匹配记录，可调整表头筛选条件。
              </td>
            </tr>
          )}
          {rows.map((c) => (
            <tr key={c.id} className="hover:bg-layer-1">
              {onSelection && (
                <td className="p-3">
                  <input
                    type="checkbox"
                    aria-label={`选择用例：${c.title}`}
                    checked={selected.some((row) => row.id === c.id)}
                    onChange={(event) =>
                      onSelection(event.target.checked ? [...selected, c] : selected.filter((row) => row.id !== c.id))
                    }
                  />
                </td>
              )}
              <td className="max-w-72 p-3 font-medium">
                <button type="button" className="platform-record-link text-left text-13" onClick={() => onView?.(c)}>
                  {c.code && <span className="font-normal mr-2 text-11 text-secondary">{c.code}</span>}
                  {c.title}
                </button>
                <p className="font-normal mt-1 text-11 text-secondary">
                  {c.steps.length} 个步骤 · 创建人：{c.created_by_name || "未记录"}
                </p>
              </td>
              <td className="p-3 text-secondary">{c.module || "未分模块"}</td>
              <td className="p-3">{priorityNames[c.priority]}</td>
              <td className="max-w-48 p-3">
                {c.requirement_id ? (
                  <Link className="text-accent-primary" to={`${projectUrl}/issues/${c.requirement_id}`}>
                    {c.requirement_title}
                  </Link>
                ) : (
                  <span className="text-tertiary">未关联</span>
                )}
              </td>
              <td className="p-3">v{c.version}</td>
              <td className="p-3">
                <div className="flex items-center gap-1 whitespace-nowrap">
                  <Button
                    variant="neutral-primary"
                    size="sm"
                    className="text-11"
                    onClick={() => {
                      if (canWrite && !c.archived_at && !c.trashed_at) onEdit(c);
                      else onView?.(c);
                    }}
                  >
                    {canWrite && !c.archived_at && !c.trashed_at ? "编辑" : "查看"}
                  </Button>
                  <Button size="sm" variant="neutral-primary" className="text-11" onClick={() => onHistory?.(c)}>
                    历史
                  </Button>
                  {canWrite && !c.trashed_at && (
                    <Button size="sm" variant="neutral-primary" className="text-11" onClick={() => onCopy(c)}>
                      复制
                    </Button>
                  )}
                  {canWrite && base && onSaved && (
                    <span className="ml-1 inline-block align-middle">
                      <RecordLifecycleActions base={base} resource="cases" row={c} onSaved={onSaved} />
                    </span>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PlanList({ rows, onSelect }: { rows: Plan[]; onSelect: (value: Plan) => void }) {
  return (
    <div className="divide-y divide-subtle rounded-md border border-subtle">
      {rows.map((p) => (
        <button
          key={p.id}
          onClick={() => onSelect(p)}
          className="flex w-full flex-wrap items-center gap-4 p-4 text-left hover:bg-layer-1"
        >
          <div className="flex-1">
            <h2 className="text-14 font-medium">
              {p.code && <span className="mr-2 text-11 text-secondary">{p.code}</span>}
              <span className="platform-record-link">{p.name}</span>{" "}
              {p.managed && (
                <span className="ml-2 inline-flex items-center gap-2 text-11 text-secondary">
                  <Badge value={p.status} label={planStatusNames[p.status]} /> 第 {p.round_no} 轮
                </span>
              )}
            </h2>
            <p className="mt-1 text-12 text-secondary">
              {p.build} · {p.environment} · {p.assignee_name || "未指定负责人"}
            </p>
            <p className="mt-1 text-11 text-secondary">创建人：{p.created_by_name || "未记录"}</p>
          </div>
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-12 text-secondary">
            <span>
              {p.summary.executed}/{p.summary.total} 已执行
            </span>
            <Badge variant="plain" value={p.summary.passed ? "passed" : "neutral"} label={`通过 ${p.summary.passed}`} />
            <Badge variant="plain" value={p.summary.failed ? "failed" : "neutral"} label={`失败 ${p.summary.failed}`} />
            <Badge
              variant="plain"
              value={p.summary.inconclusive ? "inconclusive" : "neutral"}
              label={`无法判定 ${p.summary.inconclusive || 0}`}
            />
          </span>
          <span className="text-12 text-accent-primary">
            {p.status === "completed"
              ? "查看本轮结果 →"
              : p.status === "review"
                ? "查看待确认结果 →"
                : p.status === "cancelled"
                  ? "查看历史 →"
                  : "查看 / 处理 →"}
          </span>
        </button>
      ))}
    </div>
  );
}

export function ExecutionList({
  rows,
  canWrite,
  busy,
  onDefect,
}: {
  rows: Execution[];
  canWrite: boolean;
  busy: boolean;
  onDefect: (value: Execution) => Promise<void>;
}) {
  return (
    <div className="divide-y divide-subtle rounded-md border border-subtle">
      {rows.map((e) => (
        <article key={e.id} className="space-y-2 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="flex-1 text-13 font-medium">
              {e.code && <span className="mr-2 text-11 text-secondary">{e.code}</span>}
              {e.case_title} <span className="font-normal text-tertiary">v{e.case_version}</span>
            </h2>
            <Badge value={e.result} />
            {e.result === "failed" && canWrite && (
              <Button variant="neutral-primary" disabled={busy} onClick={() => void onDefect(e)}>
                失败提缺陷
              </Button>
            )}
          </div>
          <p className="text-12 text-secondary">
            {e.plan_name} · {e.build} · {e.environment} · {e.executor || "成员"} · {renderNumericDateTime(e.created_at)}
          </p>
          <p className="text-13 whitespace-pre-wrap">{e.actual_result || "无补充说明"}</p>
          {e.evidence && <p className="text-12 whitespace-pre-wrap text-secondary">证据：{e.evidence}</p>}
          {e.reason_category && <p className="text-12 text-secondary">原因：{reasonNames[e.reason_category]}</p>}
          {e.next_action && <p className="text-12 whitespace-pre-wrap text-secondary">下一步：{e.next_action}</p>}
        </article>
      ))}
    </div>
  );
}

export function DefectList({ rows, onEdit }: { rows: Defect[]; onEdit: (value: Defect) => void }) {
  return (
    <>
      <div className="divide-y divide-subtle rounded-md border border-subtle xl:hidden">
        {rows.map((row) => (
          <article key={row.id} className="min-w-0 space-y-3 p-3">
            <button className="platform-record-link w-full text-left text-13 break-words" onClick={() => onEdit(row)}>
              {row.code && <span className="mr-2 text-11 text-secondary">{row.code}</span>}
              {defectDisplayTitle(row.title)}
            </button>
            <div className="flex flex-wrap items-center gap-3 text-12">
              <Badge value={row.status} />
              <Badge value={row.severity} />
              <span>负责人：{row.assignee_name || "未指派"}</span>
            </div>
            <dl className="grid grid-cols-2 gap-2 text-12 text-secondary">
              <div className="min-w-0">
                <dt>影响版本</dt>
                <dd className="break-words text-primary">{row.affected_build || "未填写"}</dd>
              </div>
              <div className="min-w-0">
                <dt>修复版本</dt>
                <dd className="break-words text-primary">
                  {row.fixed_build || (row.resolution_kind !== "fixed" ? "不适用" : "待修复")}
                </dd>
              </div>
            </dl>
            {row.repair_issue_name && (
              <p className="text-11 break-words text-secondary">修复任务：{row.repair_issue_name}</p>
            )}
          </article>
        ))}
      </div>
      <div className="hidden min-w-0 overflow-x-auto rounded-md border border-subtle xl:block">
        <table className="w-full min-w-[760px] text-left text-13">
          <thead className="border-b border-subtle bg-layer-1 text-12 text-secondary">
            <tr>
              <th className="p-3">
                <TableHeaderFilter label="缺陷标题" kind="defects" />
              </th>
              <th className="p-3">
                <TableHeaderFilter label="严重程度" kind="defects" />
              </th>
              <th className="p-3">
                <TableHeaderFilter label="状态" kind="defects" />
              </th>
              <th className="p-3">
                <TableHeaderFilter label="负责人" kind="defects" />
              </th>
              <th className="p-3">
                <TableHeaderFilter label="影响版本" kind="defects" />
              </th>
              <th className="p-3">
                <TableHeaderFilter label="修复版本" kind="defects" />
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-subtle">
            {rows.map((row) => (
              <tr key={row.id} className="hover:bg-layer-1">
                <td className="max-w-lg p-3">
                  <button className="platform-record-link text-left text-13" onClick={() => onEdit(row)}>
                    {row.code && <span className="mr-2 text-11 text-secondary">{row.code}</span>}
                    {defectDisplayTitle(row.title)}
                  </button>
                  {row.repair_issue_name && (
                    <p className="mt-1 text-11 text-secondary">修复任务：{row.repair_issue_name}</p>
                  )}
                </td>
                <td className="p-3">
                  <Badge value={row.severity} />
                </td>
                <td className="p-3">
                  <Badge value={row.status} />
                </td>
                <td className="p-3">{row.assignee_name || "未指派"}</td>
                <td className="p-3">{row.affected_build || "未填写"}</td>
                <td className="p-3">{row.fixed_build || (row.resolution_kind !== "fixed" ? "不适用" : "待修复")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
