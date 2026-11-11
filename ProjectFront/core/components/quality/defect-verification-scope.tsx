import { useState } from "react";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import type { Context, Defect } from "./types";

export function DefectVerificationScope({
  base,
  value,
  context,
  onChanged,
}: {
  base: string;
  value: Defect;
  context: Context;
  onChanged: (value: Defect) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const label = "功能验证";
  return (
    <div className="mb-4 flex items-center justify-between gap-3 rounded-md border border-subtle bg-layer-1 px-3 py-2">
      <p className="text-13">
        <span className="mr-2 text-secondary">验证方式</span>
        {label}
      </p>
      {context.is_manager && value.status === "resolved" && value.manual_verification_allowed && (
        <button
          type="button"
          className="text-12 font-medium text-accent-primary hover:underline"
          onClick={() => setVerifying(true)}
        >
          验证并关闭
        </button>
      )}
      {context.is_manager && value.status !== "closed" && (
        <button type="button" className="text-12 text-accent-primary hover:underline" onClick={() => setEditing(true)}>
          调整
        </button>
      )}
      {editing && (
        <Modal
          title="调整验证方式"
          onClose={() => setEditing(false)}
          onSubmit={async (form) => {
            const saved = await qualityApi.write<Defect>(
              `${base}defects/${value.id}/`,
              {
                expected_version: value.edit_version,
                verification_scope: form.get("verification_scope"),
                verification_scope_reason: form.get("reason"),
              },
              "patch"
            );
            await onChanged(saved);
            setEditing(false);
          }}
        >
          <Field label="验证方式">
            <select
              name="verification_scope"
              className={fieldClass}
              defaultValue={value.requires_data_regression ? "data" : "functional"}
            >
              <option value="functional">功能验证</option>
            </select>
          </Field>
          <Field label="调整原因">
            <textarea
              name="reason"
              required
              maxLength={1000}
              rows={2}
              className={fieldClass}
              placeholder="简要说明本次修改影响哪些操作或数据"
            />
          </Field>
        </Modal>
      )}
      {verifying && (
        <Modal
          title="验证并关闭"
          submitLabel="确认关闭"
          onClose={() => setVerifying(false)}
          onSubmit={async (form) => {
            const saved = await qualityApi.write<Defect>(
              `${base}defects/${value.id}/`,
              {
                expected_version: value.edit_version,
                status: "closed",
                verification_method: "manual",
                verification_note: form.get("result"),
              },
              "patch"
            );
            await onChanged(saved);
            setVerifying(false);
          }}
        >
          <Field label="验证结果">
            <textarea
              name="result"
              required
              maxLength={4000}
              rows={3}
              className={fieldClass}
              placeholder="填写已验证的操作及结果"
            />
          </Field>
        </Modal>
      )}
    </div>
  );
}
