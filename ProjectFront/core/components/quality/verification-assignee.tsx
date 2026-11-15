import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { v4 as uuidv4 } from "uuid";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import type { Context } from "./types";
import type { VerificationData } from "./verification-types";

export function VerificationAssignee({
  base,
  defectId,
  context,
  onArrange,
}: {
  base: string;
  defectId: string;
  context: Context;
  onArrange: () => void;
}) {
  const endpoint = `${base}defects/${defectId}/verification/`;
  const { data, error, mutate } = useSWR(endpoint, (url: string) => qualityApi.read<VerificationData>(url));
  const { mutate: revalidate } = useSWRConfig();
  const [editing, setEditing] = useState<{ version: number; assignee: string; requestId: string }>();
  const current = data?.current;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-12 text-secondary">测试</h4>
        {current?.can_configure && (
          <button
            type="button"
            className="text-12 text-accent-primary hover:underline"
            onClick={() =>
              setEditing({ version: current.version, assignee: current.assignee_id || "", requestId: uuidv4() })
            }
          >
            修改指派
          </button>
        )}
        {data && !current && data.defect_status === "resolved" && canSchedule(context) && (
          <button type="button" className="text-12 text-accent-primary hover:underline" onClick={onArrange}>
            安排测试
          </button>
        )}
      </div>
      {error ? (
        <button type="button" className="text-12 text-danger-primary" onClick={() => void mutate()}>
          读取失败，重试
        </button>
      ) : (
        <p className="text-13">{!data ? "加载中…" : current ? current.assignee_name || "待安排测试员" : "未安排"}</p>
      )}
      {editing && (
        <Modal
          title="指派测试员"
          submitLabel="保存指派"
          width="compact"
          onClose={() => setEditing(undefined)}
          onSubmit={async (form) => {
            const result = await qualityApi.write<VerificationData>(`${endpoint}workflow/`, {
              action: "assign",
              expected_version: editing.version,
              request_id: editing.requestId,
              assignee_id: form.get("assignee_id") || null,
            });
            await mutate(result, false);
            void revalidate(
              (key) =>
                typeof key === "string" && (key.startsWith(base) || key.startsWith("/api/quality-auth/my-todos/"))
            );
          }}
        >
          <Field label="测试员">
            <select
              required
              name="assignee_id"
              aria-label="指派测试员"
              defaultValue={editing.assignee}
              className={fieldClass}
            >
              <option value="" disabled>
                选择测试员
              </option>
              {context.members
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
        </Modal>
      )}
    </div>
  );
}

function canSchedule(context: Context) {
  return (
    context.is_administrator ||
    context.is_manager ||
    context.business_role === "TECHNICIAN" ||
    (context.business_roles || []).includes("TECHNICIAN")
  );
}
