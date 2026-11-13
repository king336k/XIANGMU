// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Modal, Field, fieldClass } from "./shared";
import { qualityApi } from "./api";
import type { Context, Defect } from "./types";
import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { projectMembersPath } from "@/components/settings/management-paths";
export function DefectReassign({
  base,
  value,
  context,
  onClose,
  onSaved,
}: {
  base: string;
  value: Defect;
  context: Context;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const [module, setModule] = useState(value.module?.key || "");
  const [assignee, setAssignee] = useState(value.assignee_id || "");
  const scope = base.match(/\/workspaces\/([^/]+)\/projects\/([^/]+)\//);
  const { data } = useSWR(
    scope
      ? `/api/quality-auth/accounts/?module_options=1&workspace_slug=${encodeURIComponent(scope[1])}&project_id=${encodeURIComponent(scope[2])}`
      : null,
    (url: string) => qualityApi.read<{ module_options: { key: string; name: string }[] }>(url)
  );
  const members = context.members.filter((member) =>
    (member.business_roles || [member.business_role]).includes("TECHNICIAN")
  );
  const allowed =
    !value.archived_at &&
    value.status !== "closed" &&
    (context.is_administrator || context.is_manager || value.assignee_id === context.user_id);
  return (
    <Modal
      title={value.assignee_id ? "改派负责人" : "指派负责人"}
      width="compact"
      submitLabel="确认指派"
      onClose={onClose}
      onSubmit={
        allowed
          ? async (form) => {
              await qualityApi.write(`${base}defects/${value.id}/reassign/`, {
                assignee_id: assignee || null,
                module_key: module || null,
                reason: form.get("reason"),
                expected_version: value.edit_version,
              });
              await onSaved();
            }
          : undefined
      }
    >
      <p className="text-13 font-medium">
        {value.code} · {value.title}
      </p>
      <Field label="责任模块">
        <select
          aria-label="责任模块"
          value={module}
          onChange={(event) => setModule(event.target.value)}
          className={fieldClass}
        >
          <option value="">待确认</option>
          {data?.module_options.map((item) => (
            <option key={item.key} value={item.key}>
              {item.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="技术负责人">
        <select
          aria-label="技术负责人"
          value={assignee}
          onChange={(event) => setAssignee(event.target.value)}
          className={fieldClass}
        >
          <option value="">待指派</option>
          {members.map((member) => (
            <option key={member.id} value={member.id}>
              {member.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="指派原因">
        <textarea
          name="reason"
          aria-label="指派原因"
          required
          rows={3}
          maxLength={2000}
          className={fieldClass}
          placeholder="说明分工或排查结论"
        />
      </Field>
      <p className="text-12 text-secondary">保存后立即由新负责人处理，改派过程保留记录。</p>
      {context.is_manager && projectMembersPath(base) && (
        <Link to={projectMembersPath(base)!} className="text-12 text-accent-primary hover:underline">
          成员与权限
        </Link>
      )}
    </Modal>
  );
}
