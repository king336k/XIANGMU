// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { Modal, fieldClass, Paging } from "@/components/quality/shared";
import { accountDutyLabel, accountModuleLabel, canSetAccountModules, DUTY_LABELS } from "./member-management-data";
import type { DirectoryPerson, ManagedMember } from "./member-management-data";
import type { ScopeRow } from "./member-scope-data";
import { MemberScopeAccess } from "./member-scope-access";
import { MemberPermissionsModal } from "./member-permissions-modal";
import { AddManagedMember } from "./add-managed-member";
import { CreateManagedAccount } from "./create-managed-account";
import { ModuleOwnerFields } from "./module-owner-fields";
import type { ModuleBinding } from "./module-owner-data";
type Person = DirectoryPerson & { scopes: ScopeRow[]; module_owners?: ModuleBinding[] };
export function ManagedAccounts({
  workspace,
  projectId,
  currentUserId,
  view,
  onViewChange,
  canAdmin = false,
}: {
  canAdmin?: boolean;
  workspace: string;
  projectId: string;
  currentUserId: string;
  view: string;
  onViewChange: (view: string) => void;
}) {
  const mode = view === "workspace" || view === "project" ? view : "accounts";
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Person>();
  const [identity, setIdentity] = useState<ManagedMember>();
  const [deleting, setDeleting] = useState<Person>();
  const [moduleTarget, setModuleTarget] = useState<Person>();
  const [moduleBindings, setModuleBindings] = useState<ModuleBinding[]>([]);
  const { mutate } = useSWRConfig();
  const query = new URLSearchParams({
    page: String(page),
    per_page: "20",
    search,
    ...(mode !== "accounts" ? { assignment_kind: mode } : {}),
  });
  const { data, error } = useSWR(`/api/quality-auth/accounts/?${query}`, (url: string) =>
    qualityApi.read<{ results: Person[]; count: number }>(url)
  );
  const refresh = async () => {
    await mutate(
      (key) =>
        typeof key === "string" &&
        (key.startsWith("/api/quality-auth/") || key.includes("/quality/context/") || key.endsWith("/members/"))
    );
  };
  return (
    <section className="space-y-4">
      <nav aria-label="成员管理分类" className="flex flex-wrap gap-2">
        {(
          [
            ["accounts", "账号管理"],
            ["workspace", "工作空间成员"],
            ["project", "项目成员"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            aria-current={mode === key ? "page" : undefined}
            className={`rounded border px-3 py-2 text-13 ${mode === key ? "border-accent-strong bg-accent-subtle font-medium text-accent-primary" : "border-subtle"}`}
            onClick={() => {
              onViewChange(key);
              setPage(1);
              setSearch("");
            }}
          >
            {label}
          </button>
        ))}
      </nav>
      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-48 flex-1 text-13">
          搜索账号
          <input
            aria-label="搜索账号"
            className={fieldClass}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
          />
        </label>
        <Button onClick={() => (mode === "accounts" ? setCreating(true) : setAdding(true))}>
          {mode === "accounts" ? "创建账号" : "添加成员"}
        </Button>
      </div>
      {error ? (
        <p role="alert">{errorMessage(error)}</p>
      ) : !data ? (
        <p role="status">正在加载…</p>
      ) : (
        <div className="overflow-x-auto rounded border border-subtle">
          <table className="w-full text-left text-13">
            <thead>
              <tr className="border-b border-subtle text-secondary">
                <th className="p-3">姓名与账号</th>
                <th className="p-3">{mode === "accounts" ? "账号身份" : "已分配范围"}</th>
                {mode === "accounts" && <th className="p-3">模块责任</th>}
                <th className="p-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((person) => (
                <tr key={person.id} className="border-b border-subtle">
                  <td className="p-3">
                    <p>{person.display_name || person.username}</p>
                    {person.display_name && person.display_name !== person.username && (
                      <p className="text-12 text-secondary">{person.username}</p>
                    )}
                  </td>
                  <td className="p-3">
                    {mode === "accounts" ? (
                      accountDutyLabel(person)
                    ) : (
                      <div className="space-y-1">
                        {person.scopes?.map((scope) => (
                          <p key={scope.id}>
                            {scope.name}
                            {scope.workspace_name ? ` · ${scope.workspace_name}` : ""}
                            <span className="ml-2 text-12 text-secondary">
                              {scope.inherited_access ? "继承工作空间" : "直接分配"} ·{" "}
                              {[...new Set([...scope.roles, ...(scope.inherited_roles || [])])]
                                .map((role) => DUTY_LABELS[role])
                                .filter(Boolean)
                                .join("、") || "普通成员"}
                            </span>
                          </p>
                        ))}
                      </div>
                    )}
                  </td>
                  {mode === "accounts" && (
                    <td className="p-3">
                      <div className="flex flex-wrap gap-1.5">
                        {canSetAccountModules(person) && person.module_owners?.length ? (
                          person.module_owners.map((binding) => (
                            <span
                              key={`${binding.workspace_id}:${binding.module_key}`}
                              className={`rounded border px-2 py-1 text-11 ${binding.eligible === false ? "border-warning-subtle bg-warning-subtle text-warning-primary" : "border-accent-subtle bg-accent-subtle text-accent-primary"}`}
                            >
                              {binding.module_name || binding.module_key}
                              {binding.eligible === false ? " · 权限待调整" : ""}
                            </span>
                          ))
                        ) : (
                          <span className="text-12 text-secondary">{accountModuleLabel(person)}</span>
                        )}
                      </div>
                    </td>
                  )}
                  <td className="p-3">
                    <div className="flex flex-wrap gap-x-3 gap-y-2">
                      <button
                        type="button"
                        className="text-accent-primary"
                        onClick={() =>
                          mode === "accounts"
                            ? setIdentity({ ...person, roles: person.business_roles || [] })
                            : setEditing(person)
                        }
                      >
                        {mode === "accounts" ? "管理身份" : "编辑范围"}
                      </button>
                      {mode === "accounts" && canSetAccountModules(person) && (
                        <button
                          type="button"
                          className="text-accent-primary"
                          onClick={() => {
                            setModuleTarget(person);
                            setModuleBindings(person.module_owners || []);
                          }}
                        >
                          模块负责人
                        </button>
                      )}
                      {mode === "accounts" && canAdmin && person.id !== currentUserId && (
                        <button
                          type="button"
                          className="text-danger-primary hover:underline"
                          onClick={() => setDeleting(person)}
                        >
                          删除账号
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!data.results.length && <p className="p-4 text-13 text-secondary">暂无匹配账号。</p>}
        </div>
      )}
      <Paging page={page} perPage={20} count={data?.count || 0} onChange={setPage} />
      {deleting && canAdmin && (
        <Modal
          title={`删除账号 · ${deleting.display_name || deleting.username}`}
          submitLabel="删除账号"
          width="compact"
          onClose={() => setDeleting(undefined)}
          onSubmit={async () => {
            if (deleting.id === currentUserId) throw Error("不能删除当前账号");
            await qualityApi.write("/api/quality-auth/accounts/", { user_id: deleting.id }, "delete");
            await refresh();
          }}
        >
          <p className="text-13">删除后无法登录，历史记录保留。</p>
        </Modal>
      )}
      {creating && <CreateManagedAccount onSaved={refresh} onClose={() => setCreating(false)} />}
      {moduleTarget && (
        <Modal
          title={`模块责任 · ${moduleTarget.display_name || moduleTarget.username}`}
          width="wide"
          submitLabel="保存模块责任"
          onClose={() => setModuleTarget(undefined)}
          onSubmit={async () => {
            await qualityApi.write(
              "/api/quality-auth/accounts/",
              {
                action: "module_owners",
                user_id: moduleTarget.id,
                bindings: moduleBindings.map(({ workspace_id, module_key }) => ({ workspace_id, module_key })),
              },
              "patch"
            );
            await refresh();
          }}
        >
          <ModuleOwnerFields
            key={moduleTarget.id}
            value={moduleBindings}
            onChange={setModuleBindings}
            userId={moduleTarget.id}
          />
        </Modal>
      )}
      {adding && mode !== "accounts" && (
        <AddManagedMember
          workspace={workspace}
          projectId={projectId}
          canAdmin
          scopeMode={mode}
          onSaved={refresh}
          onClose={() => setAdding(false)}
        />
      )}
      {editing && mode !== "accounts" && (
        <Modal
          title={`编辑${mode === "workspace" ? "工作空间" : "项目"}范围 · ${editing.display_name || editing.username}`}
          width="wide"
          onClose={() => setEditing(undefined)}
        >
          <MemberScopeAccess userId={editing.id} own={editing.id === currentUserId} mode={mode} onSaved={refresh} />
        </Modal>
      )}
      {identity && (
        <MemberPermissionsModal
          identityOnly
          person={identity}
          workspace={workspace}
          projectId={projectId}
          currentUserId={currentUserId}
          canAdmin
          canRoles={false}
          canWorkspaceAccess={false}
          canProjectAccess={false}
          onSaved={refresh}
          onClose={() => setIdentity(undefined)}
        />
      )}
    </section>
  );
}
