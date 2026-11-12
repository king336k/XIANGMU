// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "./api";
import { Badge, Empty, Modal, Paging, fieldClass } from "./shared";
import type { Defect, Execution, Page, Plan, TestCase } from "./types";
import { verificationStatus } from "./verification-types";
import type { VerificationData } from "./verification-types";

export type OverviewSelection = {
  kind: "cases" | "plans" | "executions" | "defects" | "pending" | "manual";
  title: string;
  result?: string;
};
export type OverviewRecord = { kind: "case" | "plan" | "defect"; id: string };
type DetailRow = {
  id: string;
  title: string;
  code?: string;
  result?: string;
  description?: string;
  target?: OverviewRecord;
};

async function allPlans(base: string): Promise<Plan[]> {
  const read = (page: number) =>
    qualityApi.read<Page<Plan>>(`${base}plans/?current_only=true&per_page=100&page=${page}`);
  const first = await read(1);
  const rest = await Promise.all(
    Array.from({ length: Math.max(0, Math.ceil(first.count / 100) - 1) }, (_, index) => read(index + 2))
  );
  return [...first.results, ...rest.flatMap((page) => page.results)];
}

export async function loadOverviewDetails(
  base: string,
  selection: OverviewSelection,
  page: number,
  search: string
): Promise<{ count: number; results: DetailRow[] }> {
  if (selection.kind === "pending") {
    const plans = await allPlans(base);
    const rows = plans
      .flatMap((plan) =>
        plan.items
          .filter((item) => !item.latest_execution)
          .map((item) => ({
            id: item.id,
            title: item.revision.title,
            result: "pending",
            description: `${plan.name} · 用例 v${item.revision.version}`,
            target: { kind: "plan" as const, id: plan.id },
          }))
      )
      .filter(
        (row) => !search || `${row.title} ${row.description}`.toLocaleLowerCase().includes(search.toLocaleLowerCase())
      );
    return { count: rows.length, results: rows.slice((page - 1) * 20, page * 20) };
  }
  const query = new URLSearchParams({ page: String(page), per_page: "20", search });
  if (selection.kind === "plans") query.set("current_only", "true");
  if (selection.kind === "defects") {
    if (selection.result === "closed") query.set("status", "closed");
    else query.set("exclude_status", "closed");
  }
  if (selection.kind === "executions" && selection.result) {
    query.set("current_only", "true");
    query.set("result", selection.result);
  }
  if (selection.kind === "manual") {
    query.set("current_only", "true");
    query.set("mode", "manual");
    if (selection.result) query.set("result", selection.result);
  }
  const endpoint = selection.kind === "manual" ? "verification-results" : selection.kind;
  const data = await qualityApi.read<
    Page<TestCase | Plan | Execution | Defect | (VerificationData & { title: string; code?: string })>
  >(`${base}${endpoint}/?${query}`);
  return {
    count: data.count,
    results: data.results.map((value): DetailRow => {
      if (selection.kind === "cases") {
        const row = value as TestCase;
        return {
          id: row.id,
          code: row.code,
          title: row.title,
          description: `v${row.version} · ${row.module || "未分模块"}`,
          target: { kind: "case", id: row.id },
        };
      }
      if (selection.kind === "plans") {
        const row = value as Plan;
        return {
          id: row.id,
          code: row.code,
          title: row.name,
          result: row.status,
          description: `${row.build} · ${row.environment} · ${row.assignee_name || "未指派"}`,
          target: { kind: "plan", id: row.id },
        };
      }
      if (selection.kind === "executions") {
        const row = value as Execution;
        return {
          id: row.id,
          code: row.code,
          title: row.case_title,
          result: row.result,
          description: `${row.plan_name} · ${row.build} · ${row.actual_result || "未补充实际表现"}`,
          target: row.plan_id ? { kind: "plan", id: row.plan_id } : undefined,
        };
      }
      if (selection.kind === "manual") {
        const row = value as VerificationData & { title: string; code?: string };
        return {
          id: row.defect_id,
          code: row.code,
          title: row.title,
          result: row.current?.manual_results[0]?.result || "pending",
          description: `第 ${row.current?.round_no} 轮 · ${row.current?.fixed_build} · ${verificationStatus[row.current?.status || ""] || ""}`,
          target: { kind: "defect", id: row.defect_id },
        };
      }
      const row = value as Defect;
      return {
        id: row.id,
        code: row.code,
        title: row.title,
        result: row.status,
        description: row.assignee_name || "未指派",
        target: { kind: "defect", id: row.id },
      };
    }),
  };
}

export function QualityOverviewDetails({
  base,
  selection,
  onClose,
  onOpenRecord,
}: {
  base: string;
  selection: OverviewSelection;
  onClose: () => void;
  onOpenRecord?: (record: OverviewRecord) => void;
}) {
  const [page, setPage] = useState(1),
    [search, setSearch] = useState("");
  const { data, error, mutate } = useSWR(
    ["quality-overview-details", base, selection.kind, selection.result, page, search],
    () => loadOverviewDetails(base, selection, page, search)
  );
  return (
    <Modal title={`${selection.title}明细`} width="wide" onClose={onClose}>
      <p className="text-12 text-secondary">关闭明细后返回原概览；查看记录后可返回此明细。</p>
      <input
        type="search"
        aria-label="搜索明细"
        placeholder="搜索名称或编号"
        value={search}
        className={fieldClass}
        onChange={(event) => {
          setSearch(event.target.value);
          setPage(1);
        }}
      />
      {error ? (
        <div role="alert" className="space-y-2 text-13 text-danger-primary">
          <p>{errorMessage(error)}</p>
          <button type="button" className="text-accent-primary" onClick={() => void mutate()}>
            重新加载
          </button>
        </div>
      ) : !data ? (
        <p role="status" className="text-13 text-secondary">
          正在加载明细…
        </p>
      ) : !data.results.length ? (
        <Empty>当前范围暂无记录。</Empty>
      ) : (
        <div className="divide-y divide-subtle rounded border border-subtle">
          {data.results.map((row) => (
            <div key={row.id} className="flex flex-wrap items-start gap-3 p-3 text-13">
              <div className="min-w-0 flex-1">
                <p className="font-medium break-words">
                  {row.code && <span className="mr-2 text-accent-primary">{row.code}</span>}
                  {row.title}
                </p>
                <p className="mt-1 text-12 break-words whitespace-pre-wrap text-secondary">{row.description}</p>
              </div>
              {row.result && <Badge value={row.result} />}
              {row.target && onOpenRecord && (
                <button
                  type="button"
                  onClick={() => onOpenRecord(row.target!)}
                  className="focus-visible:ring-accent-primary rounded text-12 text-accent-primary hover:underline focus-visible:ring-2 focus-visible:outline-none"
                >
                  查看{row.target.kind === "plan" ? "计划" : row.target.kind === "defect" ? "缺陷" : "用例"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      {data && <Paging page={page} count={data.count} perPage={20} onChange={setPage} />}
    </Modal>
  );
}
