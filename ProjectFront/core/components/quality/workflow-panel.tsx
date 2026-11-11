import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { planStatusNames, can } from "./types";
import type { Context, Plan } from "./types";

export function PlanWorkflowPanel({
  base,
  plan,
  context,
  onSaved,
}: {
  base: string;
  plan: Plan;
  context: Context;
  onSaved: () => Promise<unknown>;
}) {
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isAdmin = [...(context.business_roles || []), context.business_role].includes("PLATFORM_ADMIN");
  const labels: Record<string, string> = {
    assign: "分派负责人",
    claim: "认领并开始",
    pause: "暂停测试",
    resume: "恢复测试",
    submit: "提交测试结果",
    approve: "确认测试结果",
    return: "退回复测",
    cancel: "取消计划",
  };
  const commands: string[] = [];
  if (
    can(context, "execute") &&
    ["pending", "ready", "returned"].includes(plan.status) &&
    (isAdmin || !plan.assignee_id || plan.assignee_id === context.user_id)
  )
    commands.push("claim");
  if (can(context, "manage_test_plan") && ["pending", "ready", "returned"].includes(plan.status))
    commands.push("assign");
  if ((isAdmin || context.user_id === plan.assignee_id) && can(context, "execute")) {
    if (plan.status === "running") commands.push("pause", "submit");
    if (plan.status === "paused") commands.push("resume");
  }
  if (can(context, "manage_test") && plan.status === "review") {
    if (!plan.summary.inconclusive) commands.push("approve");
    commands.push("return");
  }
  if (can(context, "manage_test_plan") && !["completed", "cancelled", "failed"].includes(plan.status))
    commands.push("cancel");
  const primary = commands.find((verb) => ["approve", "resume", "claim", "assign", "submit"].includes(verb));
  const instruction = (
    {
      pending: "由测试安排人员分派负责人，再开始本轮测试。",
      ready: "已安排负责人，等待测试员认领。",
      returned: "经理已退回复测，本轮需要重新记录结果。",
      running: "逐条执行并如实记录结果，全部记录后再提交经理确认。",
      paused: "测试已暂停，由当前负责人恢复后继续执行。",
      review: "测试员已提交本轮结果，等待项目经理核对并确认或退回。",
      completed: "经理已确认本轮结果。失败和阻塞仍保留，发布检查会单独核对。",
      cancelled: "计划已取消，已有执行记录仍保留。",
      failed: "回归未通过，已返回技术负责人修复；本轮结果保留。",
    } as Record<string, string>
  )[plan.status];
  const perform = async (verb: string, data: object = {}) => {
    await qualityApi.write(`${base}plans/${plan.id}/workflow/`, {
      action: verb,
      expected_version: plan.workflow_version,
      ...data,
    });
    await onSaved();
  };
  const click = async (verb: string) => {
    if (["assign", "return", "cancel", "approve"].includes(verb)) {
      setAction(verb);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await perform(verb);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="space-y-3 rounded-md border border-subtle bg-layer-1 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-13 font-medium">
          {planStatusNames[plan.status]} · 第 {plan.round_no} 轮测试
        </h3>
        <div className="flex flex-wrap gap-2">
          {commands.map((verb) => (
            <Button
              key={verb}
              variant={verb === primary ? "primary" : "neutral-primary"}
              disabled={busy}
              onClick={() => void click(verb)}
            >
              {labels[verb]}
            </Button>
          ))}
        </div>
      </div>
      {plan.summary.inconclusive > 0 && (
        <p className="text-12 text-warning-primary">本轮有无法判定结果，需退回补采或处理环境后重新验证。</p>
      )}
      {commands.length === 0 && <p className="text-12 text-secondary">{instruction}</p>}
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
      <details className="text-12">
        <summary className="cursor-pointer text-secondary">流程记录（{plan.workflow_events.length}）</summary>
        <ol className="mt-3 space-y-2">
          {plan.workflow_events.map((e) => (
            <li key={e.id}>
              {renderNumericDateTime(e.created_at)} · {e.actor || "成员"} · {planStatusNames[e.previous_status]} →{" "}
              {planStatusNames[e.status]} · 第{e.round_no}轮{" "}
              {e.note && <p className="mt-1 whitespace-pre-wrap text-secondary">{e.note}</p>}
            </li>
          ))}
        </ol>
      </details>
      {action && (
        <Modal
          title={labels[action]}
          onClose={() => setAction(null)}
          onSubmit={async (form) => {
            await perform(action, {
              ...(action === "assign" ? { assignee_id: form.get("assignee_id") } : {}),
              comment: form.get("comment") || "",
            });
          }}
        >
          {action === "assign" && (
            <Field label="测试负责人 *">
              <select required name="assignee_id" defaultValue={plan.assignee_id ?? ""} className={fieldClass}>
                <option value="">请选择负责人</option>
                {context.members
                  .filter(
                    (m) =>
                      !context.business_roles_enabled ||
                      (m.business_roles || [m.business_role]).some(
                        (role) => typeof role === "string" && ["PLATFORM_ADMIN", "REGRESSION_TESTER"].includes(role)
                      )
                  )
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
              </select>
            </Field>
          )}
          <Field
            label={
              action === "assign" ? "分派说明" : action === "approve" ? "结果确认意见（非全部通过时必填）" : "原因 *"
            }
          >
            <textarea
              name="comment"
              required={
                action === "return" ||
                action === "cancel" ||
                (action === "approve" && plan.summary.passed !== plan.summary.total)
              }
              rows={3}
              maxLength={4000}
              className={fieldClass}
            />
          </Field>
        </Modal>
      )}
    </section>
  );
}
