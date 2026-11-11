import { RecordResponsibility } from "./record-responsibility";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { ArrowLeft } from "lucide-react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { RecordProgress } from "./record-progress";
import { PlanWorkflowPanel } from "./workflow-panel";
import { DataEvidencePanel } from "./data-regression-panel";
import { PlanActions } from "./plan-actions";
import { PlanPreflight } from "./test-resources-panel";
import { ExecutionForm } from "./execution-form";
import { Badge, Empty, Modal } from "./shared";
import { reasonNames } from "./types";
import type { Context, Execution, Plan, PlanItem } from "./types";

export function PlanDetail({
  base,
  value,
  canWrite,
  context,
  onBack,
  onSaved,
  onCopied,
}: {
  base: string;
  value: Plan;
  canWrite: boolean;
  context: Context;
  onBack: () => void;
  onSaved: () => Promise<unknown>;
  onCopied: (plan: Plan) => void;
}) {
  const { data: plan = value, mutate } = useSWR(`${base}plans/${value.id}/`, (url: string) =>
    qualityApi.read<Plan>(url)
  );
  const [item, setItem] = useState<PlanItem | null>(null);
  const [history, setHistory] = useState<PlanItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [resultFilter, setResultFilter] = useState("all");
  const isAdmin = [...(context.business_roles || []), context.business_role].includes("PLATFORM_ADMIN");
  const visibleItems = plan.items.filter(
    (row) => resultFilter === "all" || (row.latest_execution?.result || "pending") === resultFilter
  );
  const { data: executions } = useSWR(history ? `${base}items/${history.id}/executions/all` : null, () =>
    qualityApi.all<Execution>(`${base}items/${history!.id}/executions/`)
  );
  const saved = async () => {
    await mutate();
    await onSaved();
  };
  const defect = async (execution: Execution) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await qualityApi.write(`${base}executions/${execution.id}/defect/`, {});
      setMessage("缺陷已创建或已关联，可在缺陷管理中处理。");
      await onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-5">
      <button onClick={onBack} className="flex items-center gap-2 text-13 text-secondary">
        <ArrowLeft className="size-4" />
        返回测试计划
      </button>
      <div>
        <p className="mb-2 text-12 text-secondary">
          创建人：{plan.created_by_name || "未记录"}
          {plan.created_at ? " · " + renderNumericDateTime(plan.created_at) : ""}
        </p>
        {plan.code && <p className="text-12 text-accent-primary">{plan.code}</p>}
        <h2 className="text-18 font-semibold">{plan.name}</h2>
        <RecordResponsibility
          context={context}
          kind="测试计划"
          assigneeId={plan.assignee_id}
          authorId={plan.created_by_id}
        />
        <p className="mt-2 text-13 text-secondary">
          被测版本：{plan.build} · 环境：{plan.environment} · 负责人：{plan.assignee_name || "未指定"}
        </p>
        {plan.description && <p className="mt-1 text-13 text-secondary">{plan.description}</p>}
      </div>
      <div className="flex flex-wrap gap-3 rounded border border-subtle bg-layer-1 p-3 text-12">
        <span>共 {plan.summary.total} 条</span>
        <span>通过 {plan.summary.passed}</span>
        <span>失败 {plan.summary.failed}</span>
        <span>阻塞 {plan.summary.blocked}</span>
        <span>无法判定 {plan.summary.inconclusive || 0}</span>
        <span>跳过 {plan.summary.skipped}</span>
        <span>未执行 {plan.summary.pending}</span>
      </div>
      {error && (
        <p role="alert" className="text-danger-primary">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="text-success-primary">
          {message}
        </p>
      )}
      <RecordProgress
        base={base}
        kind="plan"
        id={plan.id}
        projectUrl={base.replace("/api/workspaces/", "/").replace("/quality/", "")}
      />
      {plan.managed && <PlanWorkflowPanel base={base} plan={plan} context={context} onSaved={saved} />}
      {plan.data_regression?.request_snapshot?.approved_verification && (
        <details className="space-y-3 rounded-md border border-subtle p-4 text-13">
          <summary className="cursor-pointer">申请时固定的验证要求</summary>
          <p className="whitespace-pre-wrap">
            测试目标：{plan.data_regression.request_snapshot.test_target || "使用已审核方案的验证要求"}
          </p>
          <p className="whitespace-pre-wrap">
            已审核验证依据：{plan.data_regression.request_snapshot.approved_verification}
          </p>
          <pre className="overflow-auto rounded bg-layer-1 p-3 text-12 break-words whitespace-pre-wrap">
            {JSON.stringify(plan.data_regression.request_snapshot.environment_details, null, 2)}
          </pre>
        </details>
      )}
      <DataEvidencePanel base={base} plan={plan} context={context} onSaved={saved} />
      <PlanPreflight base={base} plan={plan} context={context} onSaved={saved} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-14 font-medium">{plan.status === "completed" ? "本轮测试结果" : "本轮测试用例"}</h3>
        <PlanActions base={base} plan={plan} context={context} onSaved={saved} onCopied={onCopied} />
      </div>
      <div className="flex flex-wrap gap-2" aria-label="计划用例结果筛选">
        {[
          { value: "all", label: "全部", count: plan.summary.total },
          { value: "pending", label: "未执行", count: plan.summary.pending },
          { value: "failed", label: "失败", count: plan.summary.failed },
          { value: "blocked", label: "阻塞", count: plan.summary.blocked },
          { value: "inconclusive", label: "无法判定", count: plan.summary.inconclusive || 0 },
          { value: "passed", label: "通过", count: plan.summary.passed },
          { value: "skipped", label: "跳过", count: plan.summary.skipped },
        ].map((filter) => (
          <button
            key={filter.value}
            type="button"
            aria-pressed={resultFilter === filter.value}
            onClick={() => setResultFilter(filter.value)}
            className={`rounded border px-3 py-1.5 text-12 ${resultFilter === filter.value ? "border-accent-primary text-accent-primary" : "border-subtle text-secondary"}`}
          >
            {filter.label} {filter.count}
          </button>
        ))}
      </div>
      <div className="divide-y divide-subtle rounded-md border border-subtle">
        {!visibleItems.length && <p className="p-4 text-13 text-secondary">当前结果分类没有用例。</p>}
        {visibleItems.map((row, index) => (
          <div key={row.id} className="flex flex-wrap items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <p className="text-13 font-medium">
                <span className="mr-2 text-11 text-tertiary">{index + 1}.</span>
                {row.revision.title} <span className="text-11 text-tertiary">v{row.revision.version}</span>
              </p>
              <p className="mt-1 text-12 text-secondary">
                {row.revision.snapshot.steps.length} 个步骤 · {row.revision.snapshot.module || "未分模块"}
              </p>
            </div>
            <Badge value={row.latest_execution?.result ?? "pending"} />
            <Button variant="neutral-primary" onClick={() => setHistory(row)}>
              历史记录
            </Button>
            {canWrite &&
              (!plan.managed || (plan.status === "running" && (isAdmin || plan.assignee_id === context.user_id))) && (
                <>
                  <Button onClick={() => setItem(row)}>{row.latest_execution ? "再次执行" : "执行用例"}</Button>
                  {row.latest_execution?.result === "failed" && (
                    <Button
                      disabled={busy}
                      variant="neutral-primary"
                      onClick={() => void defect(row.latest_execution!)}
                    >
                      失败提缺陷
                    </Button>
                  )}
                </>
              )}
          </div>
        ))}
      </div>
      {item && <ExecutionForm base={base} plan={plan} item={item} onClose={() => setItem(null)} onSaved={saved} />}
      {history && (
        <Modal title={`执行历史 · ${history.revision.title}`} onClose={() => setHistory(null)}>
          {!executions ? (
            <p role="status">正在加载执行记录…</p>
          ) : !executions.length ? (
            <Empty>尚未执行此用例。</Empty>
          ) : (
            executions.map((e) => (
              <div key={e.id} className="space-y-2 rounded-md border border-subtle p-4">
                <div className="flex items-center justify-between gap-3">
                  <Badge value={e.result} />
                  <span className="text-12 text-secondary">
                    {renderNumericDateTime(e.created_at)} · {e.executor || "成员"}
                  </span>
                </div>
                <p className="text-13 whitespace-pre-wrap">{e.actual_result || "无补充说明"}</p>
                <p className="text-12 whitespace-pre-wrap text-secondary">{e.evidence}</p>
                {e.reason_category && <p className="text-12 text-secondary">原因：{reasonNames[e.reason_category]}</p>}
                {e.next_action && <p className="text-12 whitespace-pre-wrap text-secondary">下一步：{e.next_action}</p>}
                {canWrite && e.result === "failed" && (
                  <Button variant="neutral-primary" disabled={busy} onClick={() => void defect(e)}>
                    关联缺陷
                  </Button>
                )}
              </div>
            ))
          )}
        </Modal>
      )}
    </div>
  );
}
