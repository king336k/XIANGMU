// SPDX-License-Identifier: AGPL-3.0-only
import { Badge } from "./record-badge";
import { can, statusNames, planStatusNames, defectDisplayTitle } from "./types";
import type { Context } from "./types";
import type { VersionDetail } from "./version-types";
export type LinkedRecordKind = "requirement" | "issue" | "plan" | "defect";
export type LinkedRecordMode = "details" | "edit" | "workflow" | "delete" | "archive";
const requirementNames: Record<string, string> = {
  draft: "待完善",
  review: "待审核",
  approved: "已确认",
  completed: "验收完成",
  cancelled: "已取消",
  archived: "已归档",
};
const actionClass =
  "rounded border border-subtle px-2 py-1 text-11 font-medium whitespace-nowrap text-secondary hover:bg-layer-1 focus-visible:outline-2 focus-visible:outline-accent-primary";
export function VersionRecords({
  version,
  context,
  writable,
  finished,
  onOpen,
  onCreate,
  onLinkTask,
}: {
  version: VersionDetail;
  context: Context;
  writable: boolean;
  finished?: boolean;
  onOpen: (kind: LinkedRecordKind, id: string, mode: LinkedRecordMode) => void;
  onCreate: (kind: Exclude<LinkedRecordKind, "issue">) => void;
  onLinkTask: () => void;
}) {
  const groups = [
    {
      title: "需求",
      rows: version.requirements,
      kind: "requirement" as const,
      create: "新建需求",
      allowed: can(context, "knowledge_write"),
    },
    { title: "开发任务", rows: version.tasks, kind: "issue" as const, create: "关联任务", allowed: writable },
    {
      title: "测试计划",
      rows: version.plans,
      kind: "plan" as const,
      create: "新建计划",
      allowed: can(context, "manage_test"),
    },
    {
      title: "缺陷",
      rows: version.defects,
      kind: "defect" as const,
      create: "提交缺陷",
      allowed: can(context, "report"),
    },
  ];
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {groups.map((group) => (
        <section
          key={group.kind}
          aria-label={`版本${group.title}`}
          className="min-w-0 rounded-md border border-subtle p-4"
        >
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-14 font-medium">
              {group.title}
              <span className="ml-2 text-12 text-secondary">{group.rows.length}</span>
            </h3>
            {group.allowed && !finished && (
              <button
                type="button"
                className={`${actionClass} disabled:opacity-50`}
                disabled={group.kind === "issue" && version.automation_enabled}
                title={
                  group.kind === "issue" && version.automation_enabled ? "先切换为跟踪模式，再调整关联任务" : undefined
                }
                onClick={() => (group.kind === "issue" ? onLinkTask() : onCreate(group.kind))}
              >
                {group.create}
              </button>
            )}
          </div>
          <div className="max-h-72 space-y-2 overflow-y-auto">
            {group.rows.map((row) => (
              <div key={row.id} className="space-y-2 rounded border border-subtle p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <button
                    type="button"
                    className="platform-record-link min-w-0 flex-1 text-left text-13 break-words"
                    onClick={(event) => {
                      event.stopPropagation();
                      onOpen(group.kind, row.id, "details");
                    }}
                  >
                    {row.code && <span className="mr-2 text-11 text-secondary">{row.code}</span>}
                    {group.kind === "defect" ? defectDisplayTitle(row.name) : row.name}
                  </button>
                  {group.kind === "requirement" && can(context, "knowledge_write") ? (
                    <button
                      type="button"
                      aria-label={`更新需求状态：${row.name}`}
                      onClick={() => onOpen(group.kind, row.id, "workflow")}
                    >
                      <Badge value={row.status} label={requirementNames[row.status]} />
                    </button>
                  ) : (
                    <Badge
                      value={row.status}
                      label={
                        group.kind === "requirement"
                          ? requirementNames[row.status]
                          : group.kind === "plan"
                            ? planStatusNames[row.status]
                            : statusNames[row.status] || row.status
                      }
                    />
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={actionClass}
                    onClick={(event) => {
                      event.stopPropagation();
                      onOpen(group.kind, row.id, "details");
                    }}
                  >
                    {group.kind === "issue" ? "查看 / 编辑" : "查看 / 处理"}
                  </button>
                  {group.kind === "requirement" &&
                    can(context, "knowledge_write") &&
                    ["draft", "approved"].includes(row.status) && (
                      <button
                        type="button"
                        aria-label={`编辑需求：${row.name}`}
                        className={actionClass}
                        onClick={() => onOpen(group.kind, row.id, "edit")}
                      >
                        编辑需求
                      </button>
                    )}
                  {group.kind === "plan" &&
                    can(context, "manage_test") &&
                    ["pending", "ready"].includes(row.status) && (
                      <button type="button" className={actionClass} onClick={() => onOpen(group.kind, row.id, "edit")}>
                        编辑计划
                      </button>
                    )}
                  {group.kind === "defect" && can(context, "manage_defect") && row.status !== "closed" && (
                    <button type="button" className={actionClass} onClick={() => onOpen(group.kind, row.id, "edit")}>
                      编辑缺陷
                    </button>
                  )}
                  {group.kind === "requirement" &&
                    context.is_manager &&
                    ["draft", "cancelled"].includes(row.status) && (
                      <button
                        type="button"
                        className={actionClass}
                        onClick={() => onOpen(group.kind, row.id, "delete")}
                      >
                        删除
                      </button>
                    )}
                  {context.is_manager &&
                    ((group.kind === "requirement" && ["completed", "cancelled"].includes(row.status)) ||
                      (group.kind === "plan" && ["completed", "cancelled"].includes(row.status)) ||
                      (group.kind === "defect" && row.status === "closed")) && (
                      <button
                        type="button"
                        className={actionClass}
                        onClick={() => onOpen(group.kind, row.id, "archive")}
                      >
                        归档
                      </button>
                    )}
                  {group.kind === "defect" && can(context, "manage_defect") && (
                    <button
                      type="button"
                      className={actionClass}
                      onClick={() => onOpen(group.kind, row.id, "workflow")}
                    >
                      {row.status === "closed" ? "重开缺陷" : "更新状态"}
                    </button>
                  )}
                </div>
              </div>
            ))}
            {!group.rows.length && <p className="py-3 text-12 text-tertiary">暂无关联记录。</p>}
          </div>
        </section>
      ))}
    </div>
  );
}
