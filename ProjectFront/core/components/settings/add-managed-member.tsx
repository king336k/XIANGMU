// SPDX-License-Identifier: AGPL-3.0-only
import { useRef, useState } from "react";
import useSWR from "swr";
import { Modal, Field, fieldClass, Paging } from "@/components/quality/shared";
import { qualityApi } from "@/components/quality/api";
import { DUTY_LABELS, joinMemberWithRoles } from "./member-management-data";
import { MemberScopeAccess } from "./member-scope-access";
import type { ScopeMode } from "./member-scope-access";
import type { DirectoryPerson } from "./member-management-data";
type Person = DirectoryPerson & { in_project?: boolean };
export type AccountDirectory = {
  can_manage: boolean;
  can_manage_administrators?: boolean;
  results: Person[];
  count: number;
};
export function AddManagedMember({
  workspace,
  projectId,
  canAdmin: _canAdmin,
  scopeMode,
  onSaved,
  onClose,
}: {
  workspace: string;
  projectId: string;
  canAdmin: boolean;
  scopeMode?: ScopeMode;
  onSaved: () => Promise<unknown>;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Person>();
  const progress = useRef<{ userId?: string }>({});
  const query = new URLSearchParams({
    page: String(page),
    per_page: "20",
    search,
    exclude_administrators: "1",
    ...(!scopeMode && projectId ? { workspace_slug: workspace, project_id: projectId } : {}),
  });
  const { data, error } = useSWR(`/api/quality-auth/accounts/?${query}`, (url: string) =>
    qualityApi.read<AccountDirectory>(url)
  );
  return (
    <Modal
      title={scopeMode === "workspace" ? "添加工作空间成员" : "添加项目成员"}
      width="wide"
      onClose={onClose}
      {...(!scopeMode
        ? {
            submitLabel: "加入项目",
            onSubmit: async (form: FormData) => {
              if (!selected) throw Error("请选择已有账号。");
              await joinMemberWithRoles({
                workspace,
                projectId,
                person: { user_id: selected.id },
                roles: form.getAll("roles").map(String),
                progress: progress.current,
                write: (url, payload) => qualityApi.write(url, payload),
              });
              await onSaved();
            },
          }
        : {})}
    >
      <Field label="搜索账号">
        <input
          className={fieldClass}
          aria-label="搜索账号"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
        />
      </Field>
      {error && <p role="alert">账号目录加载失败。</p>}
      <div className="max-h-56 overflow-auto rounded border border-subtle">
        {data?.results
          .filter((person) => !person.is_administrator)
          .map((person) => (
            <label key={person.id} className="flex gap-2 border-b border-subtle p-3 text-13">
              <input
                type="radio"
                name="chosen_account"
                value={person.id}
                disabled={!scopeMode && person.in_project}
                checked={selected?.id === person.id}
                onChange={() => {
                  setSelected(person);
                  progress.current = {};
                }}
              />
              {person.display_name || person.username}
              <span className="text-secondary">
                {person.username}
                {!scopeMode && person.in_project ? " · 已加入" : ""}
              </span>
            </label>
          ))}
      </div>
      <Paging page={page} perPage={20} count={data?.count || 0} onChange={setPage} />
      {scopeMode && selected ? (
        <MemberScopeAccess key={selected.id} userId={selected.id} own={false} mode={scopeMode} onSaved={onSaved} />
      ) : (
        !scopeMode && (
          <fieldset className="flex flex-wrap gap-4">
            <legend className="mb-2 text-13">项目岗位（可选）</legend>
            {Object.entries(DUTY_LABELS).map(([key, label]) => (
              <label key={key} className="flex gap-2 text-13">
                <input type="checkbox" name="roles" value={key} />
                {label}
              </label>
            ))}
          </fieldset>
        )
      )}
    </Modal>
  );
}
