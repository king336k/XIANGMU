// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Button } from "@plane/ui";
import { Modal, Field, fieldClass } from "@/components/quality/shared";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { accountDutyLabel, ACCESS_LABELS, DUTY_LABELS } from "./member-management-data";
import type { ManagedMember } from "./member-management-data";
import { MemberScopeAccess } from "./member-scope-access";
export function MemberPermissionsModal({
  person,
  workspace,
  projectId,
  currentUserId,
  canRoles,
  canAdmin,
  canWorkspaceAccess,
  canProjectAccess,
  onSaved,
  onClose,
  identityOnly = false,
}: {
  identityOnly?: boolean;
  person: ManagedMember;
  workspace: string;
  projectId: string;
  currentUserId: string;
  canRoles: boolean;
  canAdmin: boolean;
  canWorkspaceAccess: boolean;
  canProjectAccess: boolean;
  onSaved: () => Promise<unknown>;
  onClose: () => void;
}) {
  const [tab, setTab] = useState(identityOnly ? "administrator" : canAdmin ? "access" : "roles"),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const admin = person.is_administrator === true,
    own = person.id === currentUserId;
  const save = async (url: string, payload: object, method: "post" | "patch" | "delete" = "post") => {
    setBusy(true);
    setMessage("");
    try {
      await qualityApi.write(url, payload, method);
      await onSaved();
      setMessage("已保存。");
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={`编辑权限 · ${person.display_name || person.username}`} onClose={onClose}>
      <nav aria-label="权限内容" className="platform-selection-group mb-4 flex gap-2">
        {[
          ...(!canAdmin ? [{ key: "roles", label: "业务岗位" }] : []),
          ...(!identityOnly ? [{ key: "access", label: canAdmin ? "工作空间与项目" : "访问范围" }] : []),
          ...(canAdmin ? [{ key: "administrator", label: "管理员身份" }] : []),
        ].map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => {
              setTab(item.key);
              setMessage("");
            }}
            aria-current={tab === item.key ? "page" : undefined}
            className="rounded border border-subtle px-3 py-2 text-13"
          >
            {item.label}
          </button>
        ))}
      </nav>
      <p className="text-12 text-secondary">{person.username === person.id ? person.display_name : person.username}</p>
      {tab === "roles" && (
        <section key={`${person.id}:roles`} className="space-y-3">
          {admin ? (
            <p>管理员无需兼任岗位。</p>
          ) : !projectId || !person.projectMembership ? (
            <p>加入项目后可设置岗位。</p>
          ) : (
            <>
              <fieldset disabled={!canRoles || busy}>
                <legend className="my-3 text-13 font-medium">本项目岗位（可多选）</legend>
                {Object.entries(DUTY_LABELS).map(([key, label]) => (
                  <label key={key} className="flex gap-2 py-1 text-13">
                    <input type="checkbox" name="roles" value={key} defaultChecked={person.roles.includes(key)} />
                    {label}
                  </label>
                ))}
              </fieldset>
              {canRoles ? (
                <Button
                  type="button"
                  disabled={busy}
                  onClick={(event) => {
                    if (!canRoles || admin || !projectId || !person.projectMembership || !event.currentTarget.form)
                      return;
                    const form = new FormData(event.currentTarget.form);
                    void save(`/api/workspaces/${workspace}/projects/${projectId}/quality/roles/`, {
                      user_id: person.id,
                      roles: form.getAll("roles"),
                    });
                  }}
                >
                  保存业务岗位
                </Button>
              ) : (
                <p className="text-12 text-secondary">岗位只读。</p>
              )}
            </>
          )}
        </section>
      )}
      {tab === "access" && canAdmin && <MemberScopeAccess userId={person.id} own={own} onSaved={onSaved} />}
      {tab === "access" && !canAdmin && (
        <div className="space-y-4">
          <p className="text-12 text-secondary">按项目设置访问范围与岗位。</p>
          {[
            {
              kind: "workspace",
              title: "工作空间访问",
              membership: person.workspaceMembership,
              allowed: canWorkspaceAccess && !own && !admin && person.workspaceMembership?.is_active !== false,
            },
            {
              kind: "project",
              title: "本项目访问",
              membership: person.projectMembership,
              allowed:
                canProjectAccess &&
                !admin &&
                person.projectMembership?.is_active !== false &&
                person.workspaceMembership?.is_active !== false,
            },
          ].map(
            (scope) =>
              scope.membership && (
                <section key={scope.kind} className="space-y-2">
                  <Field label={scope.title}>
                    <select
                      name={`${scope.kind}_access_role`}
                      defaultValue={scope.membership.original_role ?? scope.membership.role}
                      disabled={!scope.allowed || busy}
                      className={fieldClass}
                    >
                      {Object.entries(ACCESS_LABELS).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  {scope.allowed && (
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        disabled={busy}
                        onClick={(event) => {
                          if (!scope.allowed || !event.currentTarget.form) return;
                          const data = new FormData(event.currentTarget.form);
                          void save(
                            `/api/workspaces/${workspace}/${scope.kind === "project" ? `projects/${projectId}/` : ""}members/${scope.membership!.id}/`,
                            { role: Number(data.get(`${scope.kind}_access_role`)) },
                            "patch"
                          );
                        }}
                      >
                        保存{scope.title}
                      </Button>
                      <Button
                        type="button"
                        variant="neutral-primary"
                        disabled={busy}
                        onClick={() => {
                          if (window.confirm(`确认移除${person.username}的${scope.title}？`))
                            void save(
                              `/api/workspaces/${workspace}/${scope.kind === "project" ? `projects/${projectId}/` : ""}members/${scope.membership!.id}/`,
                              {},
                              "delete"
                            );
                        }}
                      >
                        移除{scope.title}
                      </Button>
                    </div>
                  )}
                </section>
              )
          )}
          {admin && <p className="text-12 text-secondary">管理员身份单独设置。</p>}
        </div>
      )}
      {tab === "administrator" && canAdmin && (
        <section className="space-y-3">
          <p className="text-13">当前身份：{accountDutyLabel(person)}。</p>
          <label className="flex gap-2 text-13">
            <input key={String(admin)} required type="checkbox" name="confirm" />
            确认{admin ? "取消" : "授予"}管理员身份
          </label>
          <Button
            type="button"
            disabled={busy}
            onClick={(event) => {
              if (!event.currentTarget.form) return;
              const form = new FormData(event.currentTarget.form);
              if (form.get("confirm") !== "on") {
                setMessage("请先确认管理员身份变更。");
                return;
              }
              void save("/api/quality-auth/accounts/", { user_id: person.id, administrator: !admin }, "patch");
            }}
          >
            {admin ? "取消" : "设为"}管理员
          </Button>
        </section>
      )}
      {message && (
        <p role="status" className="mt-3 text-13">
          {message}
        </p>
      )}
    </Modal>
  );
}
