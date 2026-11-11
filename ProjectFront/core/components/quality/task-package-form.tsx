// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";
type Preview = {
  id: string;
  name: string;
  case_count: number;
  status: string;
  warnings: string[];
  source_signed: false;
};
export function TaskPackageForm({
  base,
  onClose,
  onSaved,
}: {
  base: string;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const [file, setFile] = useState<File>(),
    [preview, setPreview] = useState<Preview>(),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [ack, setAck] = useState(false);
  return (
    <Modal
      title="导入现场测试任务包"
      onClose={onClose}
      submitLabel="确认创建测试计划"
      onSubmit={
        preview && ack
          ? async (form) => {
              await qualityApi.write(`${base}task-packages/${preview.id}/confirm/`, {
                acknowledged: true,
                environment: form.get("environment"),
              });
              await onSaved();
            }
          : undefined
      }
    >
      <p className="text-12 text-secondary">支持 RTP 任务包。校验后创建测试计划，执行结果和权限不导入。</p>
      <Field label="选择任务ZIP包 *">
        <input
          type="file"
          accept=".zip,application/zip"
          className={fieldClass}
          onChange={(event) => {
            setFile(event.target.files?.[0]);
            setPreview(undefined);
            setAck(false);
          }}
        />
      </Field>
      <Button
        type="button"
        variant="neutral-primary"
        disabled={!file || busy}
        onClick={async () => {
          if (!file) return;
          setBusy(true);
          setError("");
          try {
            const form = new FormData();
            form.set("file", file);
            setPreview(await qualityApi.write<Preview>(`${base}task-packages/`, form));
          } catch (e) {
            setError(errorMessage(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "正在预检…" : "预检任务包"}
      </Button>
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
      {preview && (
        <>
          <div className="rounded border border-subtle p-3 text-13">
            <p>
              {preview.name} · {preview.case_count}条用例
            </p>
            <p className="mt-2 text-12 text-secondary">{preview.warnings.join("；")}</p>
          </div>
          <Field label="新计划测试环境 *">
            <input
              required
              name="environment"
              maxLength={255}
              className={fieldClass}
              placeholder="确认导入后实际执行的环境"
            />
          </Field>
          <label className="flex gap-2 text-12">
            <input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} />
            我已核对来源内容；原结果不作为新版测试通过或允许发布的依据。
          </label>
        </>
      )}
    </Modal>
  );
}
