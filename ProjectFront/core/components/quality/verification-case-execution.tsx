import { useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { resultNames, reasonNames } from "./types";
import type { Result } from "./types";
import type { VerificationData, VerificationItem, VerificationRound } from "./verification-types";

export function VerificationCaseExecution({
  base,
  item,
  round,
  initialResult,
  onSaved,
  onClose,
}: {
  base: string;
  item: VerificationItem;
  round: VerificationRound;
  initialResult?: string;
  onSaved: (data: VerificationData) => Promise<void>;
  onClose: () => void;
}) {
  const [result, setResult] = useState<Result | "">(
    (initialResult || item.latest_execution?.result || "") as Result | ""
  );
  const [actual, setActual] = useState(item.latest_execution?.actual_result || "");
  const [note, setNote] = useState(item.latest_execution?.evidence || "");
  const [requestId, setRequestId] = useState(() => uuidv4());
  const needsReason = result === "inconclusive";
  const steps = item.snapshot.steps;
  return (
    <Modal
      title={`提交用例结果 · ${item.title}`}
      submitLabel="提交测试结果"
      onClose={onClose}
      onSubmit={async (form) =>
        onSaved(
          await qualityApi.write<VerificationData>(`${base}verification/cases/${item.item_id}/executions/`, {
            expected_version: round.version,
            request_id: requestId,
            result,
            actual_result: actual,
            evidence: note,
            reason_category: needsReason ? form.get("reason_category") : "",
            next_action: needsReason ? form.get("next_action") : "",
            step_results: [],
          })
        )
      }
    >
      <p className="rounded-md bg-layer-1 p-3 text-12 text-secondary">
        {steps
          .map((step, index) => `${index + 1}. ${step.action}${step.expected ? `（预期：${step.expected}）` : ""}`)
          .join("\n")}
      </p>
      <Field label="测试结果">
        <select
          required
          aria-label="测试结果"
          value={result}
          onChange={(event) => {
            setResult(event.target.value as Result);
            setRequestId(uuidv4());
          }}
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
      <Field label="测试结果说明">
        <textarea
          required
          rows={3}
          maxLength={4000}
          value={actual}
          onChange={(event) => {
            setActual(event.target.value);
            setRequestId(uuidv4());
          }}
          className={fieldClass}
          placeholder="简要说明该用例的实际表现"
        />
      </Field>
      <Field label="测试备注（选填）">
        <textarea
          rows={2}
          maxLength={4000}
          value={note}
          onChange={(event) => {
            setNote(event.target.value);
            setRequestId(uuidv4());
          }}
          className={fieldClass}
          placeholder="补充本条用例的情况"
        />
      </Field>
      {needsReason && (
        <>
          <Field label="无法判定原因">
            <select
              required
              name="reason_category"
              className={fieldClass}
              defaultValue=""
              onChange={() => setRequestId(uuidv4())}
            >
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
            <textarea
              required
              name="next_action"
              rows={2}
              maxLength={4000}
              className={fieldClass}
              onChange={() => setRequestId(uuidv4())}
            />
          </Field>
        </>
      )}
    </Modal>
  );
}
