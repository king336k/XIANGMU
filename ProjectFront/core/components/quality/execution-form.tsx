import { v4 as uuidv4 } from "uuid";
// SPDX-License-Identifier: AGPL-3.0-only
import { useMemo, useState } from "react";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { reasonNames, resultNames } from "./types";
import type { Plan, PlanItem, Result } from "./types";

export function ExecutionForm({
  base,
  plan,
  item,
  onClose,
  onSaved,
  requireEvidence = false,
  initialStepIndex,
  initialResult,
  initialExecution,
}: {
  requireEvidence?: boolean;
  initialStepIndex?: number;
  initialResult?: string;
  initialExecution?: import("./types").Execution | null;
  base: string;
  plan: Pick<Plan, "name" | "build" | "environment">;
  item: Pick<PlanItem, "id"> & {
    revision: Pick<PlanItem["revision"], "title" | "version"> & {
      snapshot: Pick<PlanItem["revision"]["snapshot"], "steps"> &
        Partial<Pick<PlanItem["revision"]["snapshot"], "preconditions">>;
    };
  };
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const stepRows = useMemo(
    () => item.revision.snapshot.steps.map((step) => ({ step, key: uuidv4() })),
    [item.revision.snapshot.steps]
  );
  const [result, setResult] = useState<Result>((initialResult || initialExecution?.result || "passed") as Result);
  const [requestId] = useState(() => uuidv4());
  const [steps, setSteps] = useState(
    item.revision.snapshot.steps.map((_, index) => ({
      result: (index === initialStepIndex
        ? initialResult || "passed"
        : initialExecution?.step_results[index]?.result || "passed") as Result,
      actual: initialExecution?.step_results[index]?.actual || "",
    }))
  );
  const needsReason = result === "inconclusive" || steps.some((step) => step.result === "inconclusive");
  return (
    <Modal
      title={`执行用例 · ${item.revision.title} · v${item.revision.version}`}
      onClose={onClose}
      submitLabel="提交执行结果"
      onSubmit={async (form) => {
        await qualityApi.write(`${base}items/${item.id}/executions/`, {
          request_id: requestId,
          result,
          reason_category: needsReason ? form.get("reason_category") : "",
          next_action: needsReason ? form.get("next_action") : "",
          actual_result: form.get("actual_result"),
          evidence: form.get("evidence"),
          step_results: steps,
        });
        await onSaved();
      }}
    >
      <div className="rounded-md bg-layer-1 p-3 text-13">
        <p>
          {plan.name} · {plan.build} · {plan.environment}
        </p>
        <p className="mt-2 text-secondary">前置条件：{item.revision.snapshot.preconditions || "无"}</p>
      </div>
      <div className="space-y-3">
        {stepRows.map(({ step, key }, index) => (
          <div key={key} className="space-y-3 rounded-md border border-subtle p-4">
            <p className="text-13 font-medium">
              {index + 1}. {step.action}
            </p>
            <p className="text-12 whitespace-pre-wrap text-secondary">预期：{step.expected}</p>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label={`步骤 ${index + 1} 结果`}>
                <select
                  className={fieldClass}
                  value={steps[index].result}
                  onChange={(e) =>
                    setSteps(steps.map((s, i) => (i === index ? { ...s, result: e.target.value as Result } : s)))
                  }
                >
                  {Object.entries(resultNames)
                    .filter(([k]) => k !== "pending")
                    .map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                </select>
              </Field>
              <div className="sm:col-span-2">
                <Field label={`步骤 ${index + 1} 实际表现`}>
                  <input
                    className={fieldClass}
                    required={requireEvidence}
                    value={steps[index].actual}
                    onChange={(e) =>
                      setSteps(steps.map((s, i) => (i === index ? { result: s.result, actual: e.target.value } : s)))
                    }
                  />
                </Field>
              </div>
            </div>
          </div>
        ))}
      </div>
      <Field label="整体结果 *">
        <select
          required
          name="result"
          className={fieldClass}
          value={result}
          onChange={(event) => setResult(event.target.value as Result)}
        >
          {Object.entries(resultNames)
            .filter(([k]) => k !== "pending")
            .map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
        </select>
      </Field>
      {needsReason && (
        <div className="space-y-3 rounded-md border border-warning-subtle bg-warning-subtle p-3">
          <p className="text-12 text-warning-primary">无法判定需要补充验证，不能作为通过或修复失败处理。</p>
          <Field label="无法判定原因 *">
            <select name="reason_category" required className={fieldClass} defaultValue="">
              <option value="" disabled>
                请选择原因
              </option>
              {Object.entries(reasonNames).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="下一步 *">
            <textarea
              name="next_action"
              required
              maxLength={4000}
              rows={2}
              className={fieldClass}
              placeholder="说明补采范围、环境处理和再次验证安排"
            />
          </Field>
        </div>
      )}
      <Field label={needsReason ? "实际结果 / 无法判定说明 *" : "实际结果 / 问题说明"}>
        <textarea
          name="actual_result"
          defaultValue={initialExecution?.actual_result || ""}
          required={needsReason || requireEvidence}
          rows={3}
          className={fieldClass}
          placeholder="失败时请写清实际表现，提交缺陷时会自动带入"
        />
      </Field>
      <Field label="证据备注 / 链接">
        <textarea
          name="evidence"
          defaultValue={initialExecution?.evidence || ""}
          required={requireEvidence}
          rows={2}
          className={fieldClass}
          placeholder="日志摘要、截图或报告链接"
        />
      </Field>
      <p className="text-12 text-secondary">本次执行会独立保存。重新执行会追加记录，不会覆盖此前结果。</p>
    </Modal>
  );
}
