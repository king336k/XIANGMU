// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import type { Context, Defect } from "./types";
import { RoutingPanel } from "./routing-panel";
export function DefectTeam({
  base,
  value,
  context,
  onChanged,
}: {
  base: string;
  value: Defect;
  context: Context;
  onChanged: (row: Defect) => Promise<void>;
}) {
  const [action, setAction] = useState<string>(),
    [error, setError] = useState("");
  const act = async (verb: string, userId?: string, reason = "") => {
    const changed = await qualityApi.write<Defect>(`${base}defects/${value.id}/team/`, {
      action: verb,
      user_id: userId,
      reason,
      expected_version: value.edit_version,
    });
    await onChanged(changed);
  };
  const pending = context.members.find((row) => row.id === value.pending_assignee_id);
  return (
    <>
      <RoutingPanel base={base} value={value} context={context} onChanged={onChanged} />
      <section className="space-y-3 border-t border-subtle pt-4">
        <h3 className="text-13 font-medium">成员协作与交接</h3>
        {value.pending_assignee_id && (
          <p className="text-12 text-secondary">
            等待{pending?.name || "指定成员"}接收交接；当前负责人继续负责，接收后再切换。原因：{value.transfer_reason}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {value.collaborators?.map((row) => (
            <span key={row.user_id} className="rounded border border-subtle px-2 py-1 text-12">
              {row.name}
              {context.is_manager && (
                <button
                  type="button"
                  className="ml-2 text-secondary"
                  aria-label={`移除协作者${row.name}`}
                  onClick={() => {
                    void act("remove", row.user_id).catch((e) => setError(errorMessage(e)));
                  }}
                >
                  ×
                </button>
              )}
            </span>
          ))}
        </div>
        {value.status !== "closed" && (
          <div className="flex flex-wrap gap-2">
            {context.is_manager && (
              <>
                <Button variant="neutral-primary" onClick={() => setAction("add")}>
                  添加协作者
                </Button>
                <Button
                  variant="neutral-primary"
                  onClick={() => setAction(value.pending_assignee_id ? "cancel_transfer" : "transfer")}
                >
                  {value.pending_assignee_id ? "取消交接" : "转派并交接"}
                </Button>
              </>
            )}
            {value.pending_assignee_id === context.user_id && (
              <>
                <Button
                  onClick={() => {
                    void act("accept").catch((e) => setError(errorMessage(e)));
                  }}
                >
                  接收交接
                </Button>
                <Button variant="neutral-primary" onClick={() => setAction("decline")}>
                  拒绝交接
                </Button>
              </>
            )}
          </div>
        )}
        {error && (
          <p role="alert" className="text-12 text-danger-primary">
            {error}
          </p>
        )}
        {action && (
          <Modal
            title={
              { add: "添加协作者", transfer: "转派并交接", decline: "拒绝交接", cancel_transfer: "取消交接" }[action] ||
              "成员协作"
            }
            onClose={() => setAction(undefined)}
            onSubmit={async (form) => {
              await act(action, String(form.get("user_id") || "") || undefined, String(form.get("reason") || ""));
            }}
          >
            {["add", "transfer"].includes(action) && (
              <Field label="项目成员 *">
                <select required name="user_id" className={fieldClass}>
                  <option value="">选择有效项目成员</option>
                  {context.members
                    .filter(
                      (row) =>
                        action !== "transfer" ||
                        !context.business_roles_enabled ||
                        (row.business_roles || [row.business_role]).some((role) => typeof role === "string" && ["PLATFORM_ADMIN", "TECHNICIAN"].includes(role))
                    )
                    .map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.name}
                      </option>
                    ))}
                </select>
              </Field>
            )}
            <Field label={action === "transfer" || action === "decline" ? "原因 *" : "说明"}>
              <textarea
                required={action === "transfer" || action === "decline"}
                name="reason"
                maxLength={4000}
                rows={3}
                className={fieldClass}
              />
            </Field>
            <p className="text-12 text-secondary">
              协作者不会因此获得技术负责人、测试员或经理权限。交接记录保留在缺陷时间线。
            </p>
          </Modal>
        )}
      </section>
    </>
  );
}
