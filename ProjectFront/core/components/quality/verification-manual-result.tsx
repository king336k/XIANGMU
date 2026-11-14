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
  onSaved,
  onClose,
}: {
  base: string;
  defectId: string;
  round: VerificationRound;
  onSaved: (data: VerificationData) => Promise<void>;
  onClose: () => void;
}) {
  const [round] = useState(currentRound);
  const previous = round.manual_results?.[0];
  const [requestId] = useState<string>(() => uuidv4());
  const [result, setResult] = useState("");
  const [actualResult, setActualResult] = useState(previous?.actual_result || "");
  const needsReason = result === "inconclusive";
  return (
    <Modal
      title="填写测试结果"
      submitLabel="提交测试结果"
      onClose={onClose}
      onSubmit={async (form) => {
        await onSaved(
          await qualityApi.write<VerificationData>(`${base}defects/${defectId}/verification/result/`, {
            expected_version: round.version,
            request_id: requestId,
            result: form.get("result"),
            actual_result: actualResult,
            evidence: "",
            reason_category: needsReason ? form.get("reason_category") : "",
            next_action: needsReason ? form.get("next_action") : "",
            step_results: round.steps.map(() => ({ result: form.get("result"), actual: actualResult })),
          })
        );
      }}
    >
      <p className="text-13">
        {round.fixed_build} · {round.environment}
      </p>
      <Field label="测试结果">
        <select
          aria-label="测试结果"
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
      <Field label="结果说明">
        <textarea
          required
          maxLength={4000}
          rows={3}
          className={fieldClass}
          value={actualResult}
          onChange={(event) => setActualResult(event.target.value)}
          placeholder="简要说明测试表现"
        />
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
