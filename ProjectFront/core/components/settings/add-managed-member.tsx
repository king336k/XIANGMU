// SPDX-License-Identifier: AGPL-3.0-only
import { useRef, useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { Modal, Field, fieldClass, Paging } from "@/components/quality/shared";
import { qualityApi } from "@/components/quality/api";
import { DUTY_LABELS, joinMemberWithRoles } from "./member-management-data";
import type { DirectoryPerson } from "./member-management-data";
type Person = DirectoryPerson & { source_instance?: string; external_user_id?: number; in_project?: boolean };
export type AccountDirectory = {
  can_manage: boolean;
  can_manage_administrators?: boolean;
  results: Person[];
  count: number;
  external_results?: Person[];
  sources?: { id: string; name: string }[];
  external_partial?: boolean;
};
export function AddManagedMember({
  workspace,
  projectId,
  canAdmin,
  onSaved,
  onClose,
}: {
  workspace: string;
  projectId: string;
  canAdmin: boolean;
  onSaved: () => Promise<unknown>;
  onClose: () => void;
}) {
  const [mode, setMode] = useState("existing"),
    [search, setSearch] = useState(""),
    [page, setPage] = useState(1),
    [selected, setSelected] = useState<Person>(),
    [created, setCreated] = useState<Person>();
  const progress = useRef<{ userId?: string }>({});
  const query = new URLSearchParams({
    page: String(page),
    per_page: "20",
    search,
    ...(projectId ? { workspace_slug: workspace, project_id: projectId } : {}),
  });
  const { data, error } = useSWR(`/api/quality-auth/accounts/?${query}`, (url: string) =>
    qualityApi.read<AccountDirectory>(url)
  );
  const choose = (person: Person) => {
    setSelected(person);
    progress.current = {};
  };
  const people = data?.results || [];
  return (
    <Modal
      title="添加成员"
      width="wide"
      onClose={onClose}
      submitLabel={mode === "local" && !created ? "创建账号" : "加入所选项目"}
      onSubmit={async (form) => {
        let person = mode === "local" ? created : selected;
        if (mode === "local" && !created) {
          if (!canAdmin) throw Error("只有管理员可以创建账号。");
          person = await qualityApi.write<Person>("/api/quality-auth/accounts/", {
            username: form.get("username"),
            password: form.get("password"),
          });
          setCreated(person);
          if (!projectId) {
            await onSaved();
            return;
          }
          throw Error("账号已创建，尚未加入项目。请选择岗位后加入。");
        }
        if (!person) throw Error("请选择一个账号。");
        if (!projectId) throw Error("请先选择要加入的项目。");
        await joinMemberWithRoles({
          workspace,
          projectId,
          person: { user_id: person.id },
          roles: form.getAll("roles").map(String),
          progress: progress.current,
          write: (url, payload) => qualityApi.write(url, payload),
        });
        await onSaved();
      }}
    >
      <nav aria-label="添加方式" className="mb-4 flex gap-2">
        <Button type="button" variant="neutral-primary" onClick={() => setMode("existing")}>
          选择已有账号
        </Button>
        {canAdmin && (
          <Button type="button" variant="neutral-primary" onClick={() => setMode("local")}>
            创建账号
          </Button>
        )}
      </nav>
      {mode === "existing" ? (
        <>
          <Field label="搜索人员">
            <input
              className={fieldClass}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
            />
          </Field>
          {error && <p role="alert">账号目录加载失败，请重试。</p>}
          <div className="my-3 max-h-64 overflow-auto rounded border border-subtle">
            {people.map((person) => (
              <label key={person.id} className="flex gap-2 border-b border-subtle p-3 text-13">
                <input
                  type="radio"
                  name="chosen_account"
                  value={person.id}
                  disabled={person.in_project}
                  checked={selected?.id === person.id}
                  onChange={() => choose(person)}
                />
                {person.username}
                {person.in_project ? " · 已在项目中" : ""}
              </label>
            ))}
          </div>
          <Paging page={page} perPage={20} count={data?.count || 0} onChange={setPage} />
        </>
      ) : created ? (
        <p role="status">账号 {created.username} 已创建，尚未加入项目。</p>
      ) : (
        <>
          <Field label="用户名 *">
            <input required name="username" pattern="[a-zA-Z0-9_.-]{2,128}" maxLength={128} className={fieldClass} />
          </Field>
          <Field label="初始密码 *">
            <input
              required
              name="password"
              type="password"
              minLength={8}
              maxLength={256}
              autoComplete="new-password"
              className={fieldClass}
            />
          </Field>
        </>
      )}
      {projectId && (
        <fieldset className="mt-4 space-y-2">
          <legend className="text-13 font-medium">本项目业务岗位（可多选）</legend>
          {Object.entries(DUTY_LABELS).map(([key, label]) => (
            <label key={key} className="flex gap-2 text-13">
              <input type="checkbox" name="roles" value={key} defaultChecked={key === "REPORTER"} />
              {label}
            </label>
          ))}
        </fieldset>
      )}
      <p className="mt-3 text-12 text-secondary">账号资料和密码由项目管理平台独立管理。</p>
    </Modal>
  );
}
