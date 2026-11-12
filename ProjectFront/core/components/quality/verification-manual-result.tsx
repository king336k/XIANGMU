import { useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { resultNames, reasonNames } from "./types";
import type { Result } from "./types";
import type { VerificationData, VerificationRound } from "./verification-types";
export function VerificationManualResult({
  base,
  defectId,
  round: currentRound,
  initialStepIndex,
  initialResult,
  onSaved,
  onClose,
}: {
  base: string;
  defectId: string;
  round: VerificationRound;
  initialStepIndex?: number;
  initialResult?: string;
  onSaved: (data: VerificationData) => Promise<void>;
  onClose: () => void;
}) {
  const [round] = useState(currentRound);
  const previous = round.manual_results?.[0];
  const [requestId] = useState<string>(() => uuidv4());
  const [stepRows] = useState(() => round.steps.map((step) => ({ step, key: uuidv4() })));
  const [result, setResult] = useState(initialResult || "");
  const [stepResults, setStepResults] = useState<string[]>(
    round.steps.map((_, index) =>
      index === initialStepIndex ? initialResult || "" : previous?.step_results[index]?.result || ""
    )
  );
  const needsReason = result === "inconclusive" || stepResults.includes("inconclusive");
  return (
    <Modal
      title="记录验证结果"
      submitLabel="提交结果"
      onClose={onClose}
      onSubmit={async (form) => {
        await onSaved(
          await qualityApi.write<VerificationData>(`${base}defects/${defectId}/verification/result/`, {
            expected_version: round.version,
            request_id: requestId,
            result: form.get("result"),
            actual_result: form.get("actual_result") || "",
            evidence: form.get("evidence") || "",
            reason_category: needsReason ? form.get("reason_category") : "",
            next_action: needsReason ? form.get("next_action") : "",
            step_results: round.steps.map((_, index) => ({
              result: form.get(`result_${index}`),
              actual: form.get(`actual_${index}`),
            })),
          })
        );
      }}
    >
      <p className="text-13">
        {round.fixed_build} · {round.environment}
      </p>
      {stepRows.map(({ step, key: stepKey }, index) => (
        <section key={stepKey} className="space-y-2 border-b border-subtle pb-3">
          <p className="text-13">
            {index + 1}. {step.action}
          </p>
          <p className="text-12 text-secondary">预期：{step.expected}</p>
          <Field label="实际结果">
            <textarea
              required
              name={`actual_${index}`}
              maxLength={4000}
              rows={2}
              className={fieldClass}
              defaultValue={previous?.step_results[index]?.actual || ""}
            />
          </Field>
          <Field label="步骤结果">
            <select
              aria-label="步骤结果"
              name={`result_${index}`}
              value={stepResults[index]}
              onChange={(event) =>
                setStepResults(stepResults.map((value, i) => (i === index ? event.target.value : value)))
              }
              required
              className={fieldClass}
            >
              <option value="" disabled>
                选择结果
              </option>
              {Object.entries(resultNames)
                .filter(([key]) => key !== "pending")
                .map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
            </select>
          </Field>
        </section>
      ))}
      <Field label="验证结论">
        <select
          aria-label="验证结论"
          name="result"
          value={result}
          onChange={(event) => setResult(event.target.value)}
          required
          className={fieldClass}
        >
          <option value="" disabled>
            选择结果
          </option>
          {Object.entries(resultNames)
            .filter(([key]) => key !== "pending")
            .map(([key, label]) => (
              <option key={key} value={key as Result}>
                {label}
              </option>
            ))}
        </select>
      </Field>
      {needsReason && (
        <>
          <Field label="无法判定原因">
            <select aria-label="无法判定原因" name="reason_category" required className={fieldClass} defaultValue="">
              <option value="" disabled>
                选择原因
              </option>
              {Object.entries(reasonNames).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="下一步">
            <textarea name="next_action" required rows={2} maxLength={4000} className={fieldClass} />
          </Field>
        </>
      )}
    </Modal>
  );
}
