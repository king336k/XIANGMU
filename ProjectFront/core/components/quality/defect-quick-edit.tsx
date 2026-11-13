import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
// SPDX-License-Identifier: AGPL-3.0-only

import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { can, severityNames } from "./types";
import type { Context, Defect } from "./types";
import { PagedRecordSelect } from "./paged-record-select";
import { projectMembersPath } from "@/components/settings/management-paths";
import type { TestCase } from "./types";

export type DefectQuickField = "severity" | "assignee" | "affected_build" | "fixed_build" | "case";

export function DefectQuickEdit({
  base,
  context,
  value,
  field,
  onClose,
  onSaved,
}: {
  base: string;
  context: Context;
  value: Defect;
  field: DefectQuickField;
  projectUrl: string;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const severity = field === "severity";
  const assigning = field === "assignee";
  const transfer = assigning && !!value.assignee_id;
  const titles = {
    severity: "调整严重程度",
    assignee: "指派负责人",
    affected_build: "编辑影响版本",
    fixed_build: "编辑修复版本",
    case: "关联测试用例",
  };
  const members = context.members.filter(
    (member) =>
      (!context.business_roles_enabled ||
        (member.business_roles || [member.business_role]).some(
          (role) => typeof role === "string" && ["PLATFORM_ADMIN", "TECHNICIAN"].includes(role)
        )) &&
      (!transfer || member.id !== value.assignee_id)
  );
  const allowed =
    can(context, "manage_defect") &&
    !value.archived_at &&
    value.status !== "closed" &&
    (assigning ? context.is_manager : context.is_manager || value.assignee_id === context.user_id) &&
    !(field === "case" && value.source_execution);
  const pending = assigning && !!value.pending_assignee_id;
  const membersPath = projectMembersPath(base);
  return (
    <Modal
      width="compact"
      title={transfer ? "转派负责人" : titles[field]}
      onClose={onClose}
      submitLabel={transfer ? "发起交接" : "保存"}
      onSubmit={
        allowed && !pending && (!assigning || members.length > 0)
          ? async (form) => {
              if (!assigning)
                await qualityApi.write(
                  `${base}defects/${value.id}/`,
                  {
                    [field === "case" ? "case_id" : field]:
                      form.get(field === "case" ? "case_id" : field) || (field === "case" ? null : ""),
                    expected_version: value.edit_version,
                  },
                  "patch"
                );
              else if (transfer)
                await qualityApi.write(`${base}defects/${value.id}/team/`, {
                  action: "transfer",
                  user_id: form.get("assignee_id"),
                  reason: form.get("reason"),
                  expected_version: value.edit_version,
                });
              else
                await qualityApi.write(
                  `${base}defects/${value.id}/`,
                  {
                    assignee_id: form.get("assignee_id"),
                    expected_version: value.edit_version,
                  },
                  "patch"
                );
              await onSaved();
            }
          : undefined
      }
    >
      <p className="text-13 font-medium break-words">{value.title}</p>
      {severity ? (
        <Field label="严重程度">
          <select name="severity" defaultValue={value.severity} className={fieldClass}>
            {Object.entries(severityNames).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </Field>
      ) : field === "affected_build" || field === "fixed_build" ? (
        <Field label={field === "affected_build" ? "影响版本" : "修复版本"}>
          <input
            name={field}
            defaultValue={value[field]}
            maxLength={120}
            className={fieldClass}
            required={field === "fixed_build" && value.status === "resolved"}
          />
        </Field>
      ) : field === "case" ? (
        <Field label="关联测试用例">
          <PagedRecordSelect<TestCase>
            url={`${base}cases/`}
            name="case_id"
            placeholder="暂不关联"
            searchLabel="搜索测试用例"
            required={false}
            defaultValue={value.case_id ?? ""}
            defaultLabel={value.case_title ?? "已关联用例"}
            getLabel={(row) => row.title}
          />
        </Field>
      ) : pending ? (
        <p className="text-13 text-secondary">已有待接收的交接，请在缺陷详情的“成员协作与交接”中查看或取消。</p>
      ) : (
        <>
          <Field label="负责人">
            <select name="assignee_id" required className={fieldClass}>
              <option value="">{members.length ? "选择负责人" : "暂无可指派的技术员"}</option>
              {members.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name}
                </option>
              ))}
            </select>
          </Field>
          {transfer && (
            <>
              <Field label="交接原因 *">
                <textarea name="reason" required maxLength={4000} rows={2} className={fieldClass} />
              </Field>
              <p className="text-12 text-secondary">接收人确认后切换负责人，确认前仍由当前负责人处理。</p>
            </>
          )}
          {context.business_roles_enabled && membersPath && (
            <Link className="text-12 text-accent-primary hover:underline" to={membersPath}>
              成员与权限
            </Link>
          )}
        </>
      )}
    </Modal>
  );
}
