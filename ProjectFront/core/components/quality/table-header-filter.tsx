// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { useSearchParams } from "react-router";
import { Filter } from "lucide-react";
import { Popover } from "@plane/propel/popover";
import { fieldClass } from "./shared";
import { priorityNames, statusNames, planStatusNames, resultNames, severityNames } from "./types";
import type { Context } from "./types";
import { PagedRecordSelect } from "./paged-record-select";
const requirementStatuses = {
  draft: "待完善",
  review: "待审核",
  approved: "已确认",
  completed: "验收完成",
  cancelled: "已取消",
  archived: "已归档",
};
export function TableHeaderFilter({ label, kind, context }: { label: string; kind: string; context?: Context }) {
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState(false);
  const definition: Record<string, string> = {
    用例名称: "search",
    "标题 / 编号": "search",
    编号: "code",
    标题: "search",
    需求: "search",
    缺陷标题: "search",
    计划名称: "search",
    名称: "search",
    模块: "module",
    优先级: "priority",
    严重程度: "severity",
    状态: "status",
    负责人: "assignee_id",
    执行人: "created_by_id",
    影响版本: "build",
    被测版本: "build",
    目标版本: "build",
    测试环境: "environment",
    环境: "environment",
    修复版本: "fixed_build",
    关联需求: "requirement_id",
    关联工作项: "requirement_id",
    创建时间: "date",
    执行时间: "date",
    日期: "date",
    结果: "result",
  };
  if (kind === "cases") definition["版本"] = "version";
  if (kind === "executions") {
    definition["版本"] = "build";
    definition["状态"] = "result";
    definition["实际结果"] = "search";
  }
  if (kind === "suites") definition["状态"] = "published";
  const key = definition[label];
  const choices =
    key === "priority"
      ? priorityNames
      : key === "published"
        ? { true: "可用于计划", false: "草稿" }
        : key === "severity"
          ? severityNames
          : key === "result"
            ? resultNames
            : key === "status"
              ? kind === "requirements"
                ? requirementStatuses
                : kind === "plans"
                  ? planStatusNames
                  : kind === "releases"
                    ? { draft: "待检查", admitted: "检查通过" }
                    : kind === "defects"
                      ? statusNames
                      : undefined
              : key === "assignee_id" || key === "created_by_id"
                ? Object.fromEntries([
                    ["me", "我"],
                    ...(key === "assignee_id" ? [["unassigned", "未指派"]] : []),
                    ...(context?.members.map((row) => [row.id, row.name]) || []),
                  ])
                : key === "requirement_id" && context && !context.work_item_options_url
                  ? Object.fromEntries(context.issues.map((row) => [row.id, row.name]))
                  : undefined;
  if (!key || (key === "status" && !choices)) return <>{label}</>;
  const active = key === "date" ? params.has("created_after") || params.has("created_before") : !!params.get(key);
  const apply = (form: FormData | null) => {
    const next = new URLSearchParams(params);
    const keys = key === "date" ? ["created_after", "created_before"] : [key];
    for (const field of keys) {
      const value = form ? String(form.get(field) || "").trim() : "";
      if (value) next.set(field, value);
      else next.delete(field);
    }
    next.delete("page");
    next.delete("saved_view");
    setParams(next);
    setOpen(false);
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Button
        aria-label={`筛选${label}${active ? "，已应用" : ""}`}
        className={`inline-flex items-center gap-1 text-left whitespace-nowrap ${active ? "text-accent-primary" : "hover:text-primary"}`}
      >
        {label}
        <Filter className="size-3" />
        {active && <span className="size-1 rounded-full bg-accent-primary" />}
      </Popover.Button>
      <Popover.Panel
        side="bottom"
        align="start"
        className="shadow-lg z-50 w-64 rounded-md border border-subtle bg-surface-1 p-3"
      >
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            apply(new FormData(event.currentTarget));
          }}
        >
          <p className="text-13 font-medium">筛选{label}</p>
          {key === "date" ? (
            <div className="space-y-2">
              <label className="block space-y-1 text-12 text-secondary">
                开始日期
                <input
                  aria-label="筛选开始日期"
                  name="created_after"
                  type="date"
                  className={fieldClass}
                  defaultValue={params.get("created_after") || ""}
                />
              </label>
              <label className="block space-y-1 text-12 text-secondary">
                结束日期
                <input
                  aria-label="筛选结束日期"
                  name="created_before"
                  type="date"
                  className={fieldClass}
                  defaultValue={params.get("created_before") || ""}
                />
              </label>
            </div>
          ) : key === "requirement_id" && context?.work_item_options_url ? (
            <PagedRecordSelect<{ id: string; name: string; code?: string }>
              url={context.work_item_options_url}
              name={key}
              placeholder="全部"
              searchLabel="搜索关联工作项"
              required={false}
              defaultValue={params.get(key) || ""}
              defaultLabel={context.issues.find((row) => row.id === params.get(key))?.name || "已选择的工作项"}
              getLabel={(row) => row.name}
            />
          ) : choices ? (
            <select aria-label={`选择${label}`} name={key} className={fieldClass} defaultValue={params.get(key) || ""}>
              <option value="">全部</option>
              {Object.entries(choices).map(([value, title]) => (
                <option key={value} value={value}>
                  {String(title)}
                </option>
              ))}
            </select>
          ) : (
            <input
              aria-label={`筛选${label}条件`}
              name={key}
              type={key === "version" ? "number" : "search"}
              min={key === "version" ? 1 : undefined}
              maxLength={255}
              className={fieldClass}
              defaultValue={params.get(key) || ""}
              placeholder={key === "version" ? "填写版本数字，如 2" : `输入${label}`}
            />
          )}
          <div className="flex justify-end gap-2 text-12">
            <button
              type="button"
              onClick={() => apply(null)}
              className="rounded border border-subtle px-3 py-1.5 text-secondary"
            >
              清除
            </button>
            <button type="submit" className="rounded bg-accent-primary px-3 py-1.5 text-on-color">
              应用
            </button>
          </div>
        </form>
      </Popover.Panel>
    </Popover>
  );
}
