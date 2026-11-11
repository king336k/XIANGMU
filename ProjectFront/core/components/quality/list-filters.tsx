// SPDX-License-Identifier: AGPL-3.0-only
import { resolutionNames } from "./defect-disposition";
import { SavedViewControls } from "./saved-view-controls";
import { Button } from "@plane/ui";
import { useState } from "react";
import { ListFilter, X } from "lucide-react";
import { Popover } from "@plane/propel/popover";
import { fieldClass } from "./shared";
import { statusNames, severityNames, priorityNames, planStatusNames } from "./types";
import type { Context } from "./types";

type Options = Record<string, string>;
const statuses: Record<string, Options> = {
  defects: statusNames,
  plans: planStatusNames,
  requirements: {
    draft: "待完善",
    review: "待审核",
    approved: "已确认",
    completed: "验收完成",
    cancelled: "已取消",
    archived: "已归档",
  },
  releases: { draft: "待检查", admitted: "检查已通过" },
  articles: { draft: "草稿", review: "待审核", published: "已发布", offline: "已下线" },
};
export function ListFilters({
  kind,
  context,
  params,
  onApply,
  compact = false,
}: {
  kind: string;
  context: Context;
  params: URLSearchParams;
  onApply: (params: URLSearchParams) => void;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const navigationKeys = ["tab", "panel", "layout", "plan", "defect", "requirement", "q", "per_page"];
  const filterKeys = [...params.keys()].filter(
    (key) => ![...navigationKeys, "page", "saved_view"].includes(key) && Boolean(params.get(key)?.trim())
  );
  const clear = () => {
    const next = new URLSearchParams();
    for (const key of navigationKeys) if (params.has(key)) next.set(key, params.get(key)!);
    onApply(next);
    setOpen(false);
  };
  const select = (name: string, label: string, options: Options) => (
    <label className="flex min-w-32 flex-col gap-1 text-12 text-secondary">
      {label}
      <select aria-label={label} name={name} defaultValue={params.get(name) || ""} className={fieldClass}>
        <option value="">全部</option>
        {Object.entries(options).map(([key, text]) => (
          <option key={key} value={key}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
  const input = (name: string, label: string, type = "text") => (
    <label className="flex min-w-32 flex-1 flex-col gap-1 text-12 text-secondary">
      {label}
      <input
        aria-label={label}
        type={type}
        name={name}
        defaultValue={params.get(name) || ""}
        className={fieldClass}
        maxLength={255}
      />
    </label>
  );
  const form = (
    <form
      key={params.toString()}
      className={compact ? "min-w-0" : "mb-4"}
      aria-label="列表筛选"
      onSubmit={(event) => {
        event.preventDefault();
        const next = new URLSearchParams(params);
        for (const [key, value] of new FormData(event.currentTarget).entries()) {
          if (String(value).trim()) next.set(key, String(value).trim());
          else next.delete(key);
        }
        const bucket = next.get("record_scope");
        if (bucket) {
          next.delete("record_scope");
          next.delete("archived");
          next.delete("deleted");
          if (bucket === "archived") next.set("archived", "true");
          else if (bucket === "deleted") next.set("deleted", "true");
        }
        next.delete("page");
        next.delete("saved_view");
        onApply(next);
        setOpen(false);
      }}
    >
      <div className={compact ? "grid grid-cols-1 items-end gap-3 sm:grid-cols-2" : "flex flex-wrap items-end gap-3"}>
        <label
          className={`flex max-w-full flex-col gap-1 text-12 text-secondary ${compact ? "sm:col-span-2" : "w-72"}`}
        >
          关键词
          <input
            type="search"
            aria-label="关键词"
            name="search"
            placeholder="搜索编号或标题…"
            defaultValue={params.get("search") || ""}
            maxLength={255}
            className={fieldClass}
          />
        </label>
        {!["requirements", "conversations"].includes(kind) && input("code", "编号")}
        {statuses[kind] && select("status", "状态", statuses[kind])}
        {kind === "executions" &&
          select("result", "执行结果", {
            passed: "通过",
            failed: "失败",
            blocked: "阻塞",
            inconclusive: "无法判定",
            skipped: "跳过",
          })}
        {["cases", "suites", "requirements"].includes(kind) ? (
          <label className="flex flex-col gap-1 text-12 text-secondary">
            显示范围
            <select
              name="record_scope"
              className={fieldClass}
              defaultValue={
                params.get("deleted") === "true" ? "deleted" : params.get("archived") === "true" ? "archived" : "normal"
              }
            >
              <option value="normal">正常记录</option>
              {kind !== "requirements" && <option value="archived">已归档</option>}
              <option value="deleted">回收站</option>
            </select>
          </label>
        ) : (
          ["plans", "defects"].includes(kind) && select("archived", "显示范围", { false: "正常记录", true: "已归档" })
        )}
        {kind === "suites" && select("published", "用例集状态", { true: "可用于计划", false: "草稿" })}
        {!compact && (
          <Button type="submit" variant="neutral-primary">
            筛选
          </Button>
        )}
        {!compact && filterKeys.length > 0 && (
          <Button type="button" variant="neutral-primary" aria-label="清除全部筛选" onClick={clear}>
            清除筛选（{filterKeys.length}）
          </Button>
        )}
      </div>
      <details className="mt-2 text-12 text-secondary" open={compact ? true : undefined}>
        <summary className="w-fit cursor-pointer py-1">更多筛选条件</summary>
        <div
          className={
            compact
              ? "mt-2 grid grid-cols-1 items-end gap-3 sm:grid-cols-2"
              : "mt-2 flex flex-wrap items-end gap-3 rounded-md border border-subtle p-3"
          }
        >
          {kind !== "defects" &&
            select("view", "快捷视图", {
              created_by_me: "由我创建",
              ...(kind === "plans" ? { assigned_to_me: "指派给我", unassigned: "未指派" } : {}),
            })}
          {kind === "defects" && (
            <>
              {select("severity", "严重程度", severityNames)}
              {select("resolution_kind", "处理分类", resolutionNames)}
            </>
          )}
          {["cases", "requirements"].includes(kind) &&
            select(
              "priority",
              "优先级",
              kind === "requirements" ? { urgent: "紧急", ...priorityNames, none: "未设置" } : priorityNames
            )}
          {["defects", "plans"].includes(kind) &&
            select("assignee_id", "负责人", {
              me: "我",
              unassigned: "未指派",
              ...Object.fromEntries(context.members.map((member) => [member.id, member.name])),
            })}
          {kind === "cases" && input("module", "所属模块")}
          {["defects", "plans", "executions", "releases", "requirements"].includes(kind) &&
            input("build", kind === "defects" ? "影响版本" : "目标/被测版本")}
          {["plans", "executions"].includes(kind) && input("environment", "测试环境")}
          {kind === "defects" && (
            <>
              {input("source_system", "来源系统（如 DAQ）")}
              {input("device", "设备")}
              {input("task_id", "采集任务编号")}
            </>
          )}
          {input("created_after", "创建开始日期", "date")}
          {input("created_before", "创建结束日期", "date")}
          {select("ordering", "排序", { "-created_at": "最近创建优先", created_at: "最早创建优先" })}
          {!compact && <Button type="submit">应用条件</Button>}
        </div>
      </details>
      {compact && (
        <div className="sticky bottom-0 mt-4 flex justify-between gap-2 border-t border-subtle bg-surface-1 pt-3">
          <Button type="button" variant="neutral-primary" aria-label="清除全部筛选" onClick={clear}>
            清除筛选
          </Button>
          <Button type="submit">应用筛选</Button>
        </div>
      )}
    </form>
  );
  if (compact)
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <Popover.Button
          aria-label={filterKeys.length ? `筛选，已应用${filterKeys.length}项条件` : "筛选"}
          className={`flex shrink-0 items-center gap-2 rounded-md border px-3 py-1.5 text-12 whitespace-nowrap ${filterKeys.length ? "border-accent-subtle-1 bg-accent-subtle text-accent-primary" : "border-subtle text-secondary hover:bg-layer-1"}`}
        >
          <ListFilter className="size-3.5" />
          筛选
          {filterKeys.length > 0 && <span className="rounded bg-accent-subtle px-1.5">{filterKeys.length}</span>}
        </Popover.Button>
        <Popover.Panel
          align="end"
          side="bottom"
          aria-label="筛选条件"
          className="shadow-lg z-50 max-h-[min(75vh,40rem)] w-[min(32rem,calc(100vw-2rem))] overflow-y-auto rounded-md border border-subtle bg-surface-1 p-4"
        >
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-14 font-medium">筛选条件</h2>
            <button
              type="button"
              aria-label="关闭筛选"
              onClick={() => setOpen(false)}
              className="rounded p-1 hover:bg-layer-1"
            >
              <X className="size-4" />
            </button>
          </div>
          {form}
        </Popover.Panel>
      </Popover>
    );
  return (
    <>
      {!["requirements", "defects", "cases", "plans", "executions", "suites", "releases"].includes(kind) && (
        <SavedViewControls kind={kind} params={params} onApply={onApply} />
      )}
      {form}
    </>
  );
}
