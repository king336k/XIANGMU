import { useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { Button } from "@plane/ui";
import { CasePicker } from "./case-picker";
import type { CaseOption } from "./case-selection";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass } from "./shared";
import type { Context } from "./types";
import type { VerificationData, VerificationItem, VerificationRound, SolutionReviewGate } from "./verification-types";

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
  repairRequired = false,
  solutionReview,
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
  repairRequired?: boolean;
  solutionReview?: SolutionReviewGate;
}) {
  const [expectedVersion] = useState(version);
  const [solutionRevisionId] = useState(solutionReview?.revision_id);
  const [mode, setMode] = useState(initialMode || initial?.mode || "manual");
  const [howToTest, setHowToTest] = useState(
    initial?.steps.map((step) => step.action).join("\n") || solutionReview?.test_requirements || ""
  );
  const [selected, setSelected] = useState<CaseOption[]>(
    (initial?.items || [])
      .filter((item): item is VerificationItem & { case_id: string } => !!item.case_id)
      .map((item) => ({
        id: item.case_id,
        title: item.title,
        version: item.case_version ?? 1,
        module: item.snapshot.module || "",
        priority: item.snapshot.priority || "medium",
      }))
  );
  const [testRequirements, setTestRequirements] = useState(
    mode === "cases"
      ? initial?.steps.map((step) => step.action).join("\n") || solutionReview?.test_requirements || ""
      : ""
  );
  const [repairNote, setRepairNote] = useState(solutionReview?.repair_note || "");
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
        expected_version: expectedVersion,
        ...(repairRequired ? { repair_and_arrange: true, repair_note: repairNote } : {}),
        ...(solutionRevisionId ? { solution_revision_id: solutionRevisionId } : {}),
        request_id: requestId,
        mode,
        fixed_build: build,
        environment,
        assignee_id: assignee || null,
        test_requirements: mode === "cases" ? testRequirements : "",
        ...(mode === "manual"
          ? { steps: [{ action: howToTest, expected: "" }] }
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
      <div className="rounded-md border border-subtle bg-layer-1 p-3">
        <h3 className="text-13 font-medium">{repairRequired ? "修复并安排测试" : "安排测试"}</h3>
        {solutionReview?.status === "approved" && (
          <p className="mt-1 text-12 text-success-primary">修复方案已通过：{solutionReview.title}</p>
        )}
        <p className="mt-1 text-12 text-secondary">
          {repairRequired ? "确认已按审核方案完成修复，填写修复版本后交给测试员验证。" : "保存后交给指派测试员执行。"}
        </p>
      </div>
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
      {repairRequired && (
        <Field label="处理说明">
          <textarea
            required
            rows={3}
            maxLength={4000}
            className={fieldClass}
            value={repairNote}
            onChange={(event) => {
              setRepairNote(event.target.value);
              change();
            }}
            placeholder="简要说明修复内容"
          />
        </Field>
      )}
      <Field label="指派测试员">
        <select
          aria-label="指派测试员"
          required
          value={assignee}
          className={fieldClass}
          onChange={(event) => {
            setAssignee(event.target.value);
            change();
          }}
        >
          <option value="" disabled>
            选择测试员
          </option>
          {context?.members
            .filter((member) => {
              if (member.is_administrator) return false;
              const roles = [member.business_role, ...(member.business_roles || [])].filter(Boolean);
              return roles.length
                ? roles.includes("REGRESSION_TESTER")
                : !context.business_roles_enabled && member.role === 15;
            })
            .map((member) => (
              <option key={member.id} value={member.id}>
                {member.name}
              </option>
            ))}
        </select>
      </Field>
      {mode === "manual" ? (
        <Field label="如何测试">
          <textarea
            required
            className={fieldClass}
            rows={4}
            maxLength={4000}
            value={howToTest}
            onChange={(event) => {
              setHowToTest(event.target.value);
              change();
            }}
            placeholder="写清测试操作，可按 1、2、3 分行填写。"
          />
        </Field>
      ) : (
        <div className="space-y-3">
          <CasePicker
            base={base}
            selected={selected}
            onChange={(rows) => {
              setSelected(rows);
              change();
            }}
          />
          <Field label="测试要求（选填）">
            <textarea
              className={fieldClass}
              rows={3}
              maxLength={4000}
              value={testRequirements}
              onChange={(event) => {
                setTestRequirements(event.target.value);
                change();
              }}
              placeholder="未关联用例时，请写清测试目标；测试员可据此补充本轮用例。"
            />
          </Field>
        </div>
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
            !assignee ||
            (repairRequired && !repairNote.trim()) ||
            !environment.trim() ||
            (mode === "manual" ? !howToTest.trim() : !selected.length && !testRequirements.trim())
          }
          onClick={() => void save()}
        >
          {busy ? "正在保存…" : repairRequired ? "完成修复并安排测试" : "保存安排"}
        </Button>
        <Button type="button" variant="neutral-primary" onClick={onCancel}>
          取消
        </Button>
      </div>
    </fieldset>
  );
}
