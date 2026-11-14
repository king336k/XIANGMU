import { useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { CasePicker } from "./case-picker";
import { CaseForm } from "./case-form";
import type { CaseOption } from "./case-selection";
import { Field, fieldClass } from "./shared";
import type { Context } from "./types";
import type { VerificationData, VerificationRound } from "./verification-types";

export function VerificationCaseSupplement({
  base,
  defectId,
  round,
  context,
  onSaved,
}: {
  base: string;
  defectId: string;
  round: VerificationRound;
  context: Context;
  onSaved: (data: VerificationData) => Promise<void>;
}) {
  const [selected, setSelected] = useState<CaseOption[]>([]);
  const [title, setTitle] = useState("");
  const [howToTest, setHowToTest] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [creatingLibraryCase, setCreatingLibraryCase] = useState(false);
  const [pickerVersion, setPickerVersion] = useState(0);
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await onSaved(
        await qualityApi.write<VerificationData>(`${base}defects/${defectId}/verification/cases/`, {
          expected_version: round.version,
          request_id: uuidv4(),
          case_ids: selected.map((row) => row.id),
          temporary_cases: title.trim()
            ? [{ title: title.trim(), preconditions: "", steps: [{ action: howToTest.trim(), expected: "" }] }]
            : [],
        })
      );
      setSelected([]);
      setTitle("");
      setHowToTest("");
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="rounded-md border border-subtle">
      <summary className="cursor-pointer px-3 py-2.5 text-13 font-medium">补充本轮用例</summary>
      <div className="space-y-3 border-t border-subtle p-3">
        <Button type="button" variant="neutral-primary" onClick={() => setCreatingLibraryCase(true)}>
          新建公共用例
        </Button>
        <CasePicker key={pickerVersion} base={base} selected={selected} onChange={setSelected} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="临时用例名称（选填）">
            <input
              value={title}
              maxLength={255}
              className={fieldClass}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="只用于当前缺陷轮次"
            />
          </Field>
          <Field label="如何测试（填写临时用例时必填）">
            <textarea
              value={howToTest}
              required={!!title.trim()}
              maxLength={4000}
              rows={2}
              className={fieldClass}
              onChange={(event) => setHowToTest(event.target.value)}
              placeholder="写清测试操作"
            />
          </Field>
        </div>
        {message && (
          <p role="status" className="text-12 text-success-primary">
            {message}
          </p>
        )}
        {error && (
          <p role="alert" className="text-12 text-danger-primary">
            {error}
          </p>
        )}
        <Button
          type="button"
          disabled={busy || (!selected.length && (!title.trim() || !howToTest.trim()))}
          onClick={() => void save()}
        >
          {busy ? "正在添加…" : "添加到本轮"}
        </Button>
      </div>
      {creatingLibraryCase && (
        <CaseForm
          base={base}
          context={context}
          onClose={() => setCreatingLibraryCase(false)}
          onSaved={async () => {
            setMessage("公共用例已创建，请在上方搜索后添加到本轮。");
            setPickerVersion((value) => value + 1);
            setCreatingLibraryCase(false);
          }}
        />
      )}
    </details>
  );
}
