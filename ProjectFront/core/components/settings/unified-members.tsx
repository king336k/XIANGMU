// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { observer } from "mobx-react";
import useSWR, { useSWRConfig } from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { Field, fieldClass, Modal, Paging } from "@/components/quality/shared";
import { canOpenQualityTab } from "@/components/quality/types";
import type { Context } from "@/components/quality/types";
import { useUser } from "@/hooks/store/user";
import { useMember } from "@/hooks/store/use-member";
import { ProjectSettingsMemberDefaults } from "@/components/project/project-settings-member-defaults";
import { SendWorkspaceInvitationModal } from "@/components/workspace/members";
import { MemberPermissionsModal } from "./member-permissions-modal";
import { ManagedAccounts } from "./managed-accounts";
import { AddManagedMember } from "./add-managed-member";
import type { AccountDirectory } from "./add-managed-member";
import { mergeMemberRows, DUTY_LABELS, accessUserId, memberAccessLabel } from "./member-management-data";
import type { AccessMembership, MemberDuty, ManagedMember } from "./member-management-data";
export const UnifiedMembers = observer(function UnifiedMembers({
  workspace,
  projectId,
  context,
  view,
  onViewChange,
}: {
  workspace: string;
  projectId: string;
  context?: Context;
  view: string;
  onViewChange: (view: string) => void;
}) {
  const [search, setSearch] = useState(""),
    [page, setPage] = useState(1),
    [editing, setEditing] = useState<ManagedMember>(),
    [adding, setAdding] = useState(false),
    [defaults, setDefaults] = useState(false),
    [invite, setInvite] = useState(false),
    [policy, setPolicy] = useState(false);
  const { mutate: invalidate } = useSWRConfig();
  const { data: user } = useUser();
  const {
    workspace: { inviteMembersToWorkspace },
  } = useMember();
  const canRoles = canOpenQualityTab(context, "roles");
  const query = new URLSearchParams({
    page: String(page),
    per_page: "20",
    search,
    ...(projectId ? { workspace_slug: workspace, project_id: projectId } : {}),
  });
  const directory = useSWR(`/api/quality-auth/accounts/?${query}`, (url: string) =>
    qualityApi.read<AccountDirectory>(url)
  );
  const workspaceMembers = useSWR(`/api/workspaces/${workspace}/members/`, (url: string) =>
    qualityApi.read<AccessMembership[]>(url)
  );
  const projectMembers = useSWR(
    projectId ? `/api/workspaces/${workspace}/projects/${projectId}/members/` : null,
    (url: string) => qualityApi.read<AccessMembership[]>(url)
  );
  const roles = useSWR(
    projectId && canRoles ? `/api/workspaces/${workspace}/projects/${projectId}/quality/roles/` : null,
    (url: string) => qualityApi.read<{ enabled: boolean; roles: Record<string, string>; results: MemberDuty[] }>(url)
  );
  const canAdmin = directory.data?.can_manage_administrators === true;
  const mode = view === "accounts" && canAdmin ? "accounts" : "project";
  const nativeRows = projectId ? projectMembers.data || [] : [];
  const merged = mergeMemberRows(
    nativeRows,
    workspaceMembers.data || [],
    roles.data?.results || [],
    directory.data?.results || [],
    context?.members || [],
    mode === "project" && !projectId ? "workspace" : mode
  );
  const selectedRows =
    mode === "accounts"
      ? merged.filter((row) => (directory.data?.results || []).some((person) => person.id === row.id))
      : merged.filter((row) =>
          `${row.username} ${row.display_name || ""}`.toLowerCase().includes(search.toLowerCase())
        );
  const count = mode === "accounts" ? directory.data?.count || 0 : selectedRows.length;
  const visible = mode === "accounts" ? selectedRows : selectedRows.slice((page - 1) * 20, page * 20);
  const currentWorkspaceRole = workspaceMembers.data?.find((row) => accessUserId(row) === user?.id)?.role;
  const currentProjectRole = projectMembers.data?.find((row) => accessUserId(row) === user?.id)?.role;
  const refresh = async () => {
    await Promise.all([
      directory.mutate(),
      workspaceMembers.mutate(),
      projectMembers.mutate(),
      roles.mutate(),
      invalidate(
        (key) =>
          typeof key === "string" &&
          (key.includes("/quality/context/") ||
            key === "/api/quality-auth/work-access/" ||
            key.startsWith("/api/quality-auth/accounts/?"))
      ),
    ]);
  };
  if (canAdmin)
    return (
      <ManagedAccounts
        workspace={workspace}
        projectId={projectId}
        currentUserId={user?.id || ""}
        view={view}
        onViewChange={onViewChange}
      />
    );
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="min-w-48 flex-1 text-13">
          搜索人员
          <input
            aria-label="搜索人员"
            className={fieldClass}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
          />
        </label>
        {canAdmin && (
          <Field label="人员范围">
            <select
              aria-label="人员范围"
              className={fieldClass}
              value={mode}
              onChange={(event) => {
                onViewChange(event.target.value);
                setPage(1);
              }}
            >
              <option value="project">{projectId ? "项目成员" : "工作空间成员"}</option>
              <option value="accounts">全部人员</option>
            </select>
          </Field>
        )}
        {projectId && (canAdmin || canRoles) && <Button onClick={() => setAdding(true)}>添加成员</Button>}
      </div>
      {(projectMembers.error || roles.error || (!projectId && workspaceMembers.error)) && (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(projectMembers.error || roles.error || workspaceMembers.error)}
        </p>
      )}
      {!nativeRows.length && !directory.data && !directory.error ? (
        <p role="status">正在加载…</p>
      ) : (
        <div className="overflow-x-auto rounded border border-subtle">
          <table className="w-full text-left text-13">
            <thead>
              <tr className="border-b border-subtle text-secondary">
                <th className="p-3">姓名与账号</th>
                <th>业务岗位</th>
                <th>访问状态</th>
                <th>管理员</th>
                <th className="p-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((person) => (
                <tr key={person.id} className="border-b border-subtle">
                  <td className="p-3">
                    <p>{person.display_name || person.username}</p>
                    {person.username !== person.id && <p className="text-11 text-secondary">{person.username}</p>}
                  </td>
                  <td>
                    {person.is_administrator
                      ? "全部业务权限"
                      : person.roles
                          .map((role) => DUTY_LABELS[role])
                          .filter(Boolean)
                          .join("、") || "未分配岗位"}
                  </td>
                  <td>{memberAccessLabel(person, !!projectId)}</td>
                  <td>{person.is_administrator ? "管理员" : "—"}</td>
                  <td className="p-3">
                    {canAdmin ||
                    canRoles ||
                    currentWorkspaceRole === 20 ||
                    (currentProjectRole === 20 && person.id !== user?.id && person.workspaceMembership?.role !== 20) ? (
                      <button className="text-accent-primary" onClick={() => setEditing(person)}>
                        编辑权限
                      </button>
                    ) : (
                      <span className="text-secondary">只读</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!visible.length && <p className="p-4 text-13 text-secondary">暂无匹配人员。</p>}
        </div>
      )}
      <Paging page={page} perPage={20} count={count} onChange={setPage} />
      <details className="rounded border border-subtle p-3">
        <summary className="cursor-pointer text-13">更多访问管理</summary>
        <div className="mt-3 flex flex-wrap gap-2">
          {(canAdmin || currentWorkspaceRole === 20) && (
            <Button variant="neutral-primary" onClick={() => setInvite(true)}>
              邀请工作空间成员
            </Button>
          )}
          {projectId && currentProjectRole !== undefined && (
            <Button variant="neutral-primary" onClick={() => setDefaults(true)}>
              项目默认设置
            </Button>
          )}
          {context?.is_administrator && projectId && (
            <Button variant="neutral-primary" onClick={() => setPolicy(true)}>
              业务权限策略
            </Button>
          )}
        </div>
      </details>
      {editing && (
        <MemberPermissionsModal
          key={`${projectId}:${editing.id}`}
          person={merged.find((row) => row.id === editing.id) || editing}
          workspace={workspace}
          projectId={projectId}
          currentUserId={user?.id || ""}
          canRoles={canRoles}
          canAdmin={canAdmin}
          canWorkspaceAccess={canAdmin || currentWorkspaceRole === 20}
          canProjectAccess={
            canAdmin ||
            currentWorkspaceRole === 20 ||
            (currentProjectRole === 20 && editing.id !== user?.id && editing.workspaceMembership?.role !== 20)
          }
          onSaved={refresh}
          onClose={() => setEditing(undefined)}
        />
      )}
      {adding && (
        <AddManagedMember
          workspace={workspace}
          projectId={projectId}
          canAdmin={canAdmin}
          onSaved={refresh}
          onClose={() => setAdding(false)}
        />
      )}
      {defaults && projectId && (
        <Modal title="项目默认设置" onClose={() => setDefaults(false)}>
          <ProjectSettingsMemberDefaults projectId={projectId} workspaceSlug={workspace} members={context?.members} />
        </Modal>
      )}
      <SendWorkspaceInvitationModal
        isOpen={invite}
        onClose={() => setInvite(false)}
        onSubmit={async (data) => {
          await inviteMembersToWorkspace(workspace, data);
          setInvite(false);
          await refresh();
        }}
      />
      {policy && projectId && (
        <Modal
          title="业务权限策略"
          onClose={() => setPolicy(false)}
          onSubmit={async () => {
            await qualityApi.write(`/api/workspaces/${workspace}/projects/${projectId}/quality/role-policy/`, {
              enabled: true,
            });
            await refresh();
          }}
        >
          <p className="text-13">
            {roles.data?.enabled ? "业务角色权限已启用。" : "启用前请先分配有效的项目经理或管理员。"}
            启用后不能退回宽泛成员权限。
          </p>
        </Modal>
      )}
    </section>
  );
});
