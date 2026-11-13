import { useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { Button } from "@plane/ui";
import { CasePicker } from "./case-picker";
import type { CaseOption } from "./case-selection";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass } from "./shared";
import type { Context, Step } from "./types";
import type { VerificationData, VerificationRound } from "./verification-types";

export function VerificationConfigure({
  base,
  defectId,
  version,
  fixedBuild,
  initial,
  initialMode,
  onSaved,
  onCancel,
  context,
}: {
  base: string;
  defectId: string;
  version: number;
  fixedBuild: string;
  initial?: VerificationRound;
  initialMode?: "manual" | "cases";
  onSaved: (data: VerificationData) => Promise<void>;
  onCancel: () => void;
  context?: Context;
}) {
  const [mode, setMode] = useState(initialMode || initial?.mode || "manual");
  const [steps, setSteps] = useState<(Step & { id: string })[]>(
    (initial?.steps.length ? initial.steps : [{ action: "", expected: "" }]).map((step) => ({
      action: step.action,
      expected: step.expected,
      id: uuidv4(),
    }))
  );
  const [selected, setSelected] = useState<CaseOption[]>(
    (initial?.items || []).map((item) => ({
      id: item.case_id,
      title: item.title,
      version: item.case_version,
      module: item.snapshot.module || "",
      priority: item.snapshot.priority || "medium",
    }))
  );
  const [build, setBuild] = useState(initial?.fixed_build || fixedBuild);
  const [environment, setEnvironment] = useState(initial?.environment || "");
  const [assignee, setAssignee] = useState(initial?.assignee_id || "");
  const [requestId, setRequestId] = useState<string>(() => uuidv4());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const change = () => {
    setRequestId(uuidv4());
    setError("");
  };
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await qualityApi.write<VerificationData>(`${base}defects/${defectId}/verification/`, {
        expected_version: version,
        request_id: requestId,
        mode,
        fixed_build: build,
        environment,
        assignee_id: assignee || null,
        ...(mode === "manual"
          ? { steps: steps.map(({ action, expected }) => ({ action, expected })) }
          : { case_ids: selected.map((row) => row.id) }),
      });
      await onSaved(result);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <fieldset disabled={busy} className="min-w-0 space-y-4">
      <div role="group" aria-label="验证方式" className="flex flex-wrap gap-2">
        {(
          [
            ["manual", "人工验证"],
            ["cases", "用例回归"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            aria-pressed={mode === key}
            onClick={() => {
              setMode(key);
              change();
            }}
            className={`rounded-md border px-4 py-2 text-13 ${mode === key ? "border-accent-subtle bg-accent-subtle font-semibold text-accent-primary" : "border-subtle text-secondary hover:bg-layer-1"}`}
          >
            {mode === key ? "✓ " : ""}
            {label}
          </button>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="验证版本">
          <input
            className={fieldClass}
            value={build}
            maxLength={120}
            onChange={(event) => {
              setBuild(event.target.value);
              change();
            }}
          />
        </Field>
        <Field label="验证环境">
          <input
            className={fieldClass}
            value={environment}
            maxLength={255}
            onChange={(event) => {
              setEnvironment(event.target.value);
              change();
            }}
          />
        </Field>
      </div>
      <Field label="指派测试员">
        <select
          aria-label="指派测试员"
          value={assignee}
          className={fieldClass}
          onChange={(event) => {
            setAssignee(event.target.value);
            change();
          }}
        >
          <option value="">待测试员认领</option>
          {context?.members
            .filter(
              (member) =>
                !context.business_roles_enabled ||
                member.is_administrator ||
                [member.business_role, ...(member.business_roles || [])].includes("REGRESSION_TESTER")
            )
            .map((member) => (
              <option key={member.id} value={member.id}>
                {member.name}
              </option>
            ))}
        </select>
      </Field>
      {mode === "manual" ? (
        <div className="space-y-3">
          {steps.map((step, index) => (
            <div key={step.id} className="grid items-start gap-2 sm:grid-cols-[1fr_1fr_auto]">
              <Field label={`步骤 ${index + 1}`}>
                <textarea
                  className={fieldClass}
                  rows={2}
                  maxLength={4000}
                  value={step.action}
                  onChange={(event) => {
                    setSteps(steps.map((row) => (row.id === step.id ? { ...row, action: event.target.value } : row)));
                    change();
                  }}
                />
              </Field>
              <Field label="预期结果">
                <textarea
                  className={fieldClass}
                  rows={2}
                  maxLength={4000}
                  value={step.expected}
                  onChange={(event) => {
                    setSteps(steps.map((row) => (row.id === step.id ? { ...row, expected: event.target.value } : row)));
                    change();
                  }}
                />
              </Field>
              <Button
                type="button"
                variant="neutral-primary"
                disabled={steps.length === 1}
                onClick={() => {
                  setSteps(steps.filter((row) => row.id !== step.id));
                  change();
                }}
              >
                移除
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="neutral-primary"
            disabled={steps.length >= 100}
            onClick={() => {
              setSteps([...steps, { id: uuidv4(), action: "", expected: "" }]);
              change();
            }}
          >
            添加步骤
          </Button>
        </div>
      ) : (
        <CasePicker
          base={base}
          selected={selected}
          onChange={(rows) => {
            setSelected(rows);
            change();
          }}
        />
      )}
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          disabled={
            busy ||
            !build.trim() ||
            !environment.trim() ||
            (mode === "manual" ? steps.some((step) => !step.action.trim() || !step.expected.trim()) : !selected.length)
          }
          onClick={() => void save()}
        >
          {busy ? "正在保存…" : "保存安排"}
        </Button>
        <Button type="button" variant="neutral-primary" onClick={onCancel}>
          取消
        </Button>
      </div>
    </fieldset>
  );
}
