// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { fieldClass, Paging } from "@/components/quality/shared";
import { ACCESS_LABELS, DUTY_LABELS } from "./member-management-data";
import { buildScopePayload, scopeKey, updateScopeChanges } from "./member-scope-data";
import type { ScopeChanges, ScopeRow } from "./member-scope-data";

type Page = { results: ScopeRow[]; count: number; is_administrator: boolean };
type WorkspaceProps = {
  row: ScopeRow;
  endpoint: string;
  pending: ScopeChanges;
  busy: boolean;
  administrator: boolean;
  own: boolean;
  onChange: (row: ScopeRow, access: number, roles?: string[]) => void;
};
function WorkspaceScopes({ row, endpoint, pending, busy, administrator, own, onChange }: WorkspaceProps) {
  const [expanded, setExpanded] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const access = pending[scopeKey(row)]?.access_role ?? row.access_role;
  const workspaceRoles = pending[scopeKey(row)]?.roles ?? row.roles;
  const query = new URLSearchParams({
    kind: "project",
    workspace_id: row.id,
    search,
    page: String(page),
    per_page: "10",
  });
  const projects = useSWR(expanded ? `${endpoint}?${query}` : null, (url: string) => qualityApi.read<Page>(url));
  return (
    <section className="rounded border border-subtle p-3">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex min-w-0 flex-1 items-center gap-2 text-13 font-medium">
          <input
            type="checkbox"
            aria-label={`${row.name}工作空间访问`}
            checked={access > 0}
            disabled={busy || administrator || (own && row.access_role > 0)}
            onChange={(event) => onChange(row, event.target.checked ? 15 : 0)}
          />
          <span className="truncate">{row.name}</span>
        </label>
        {access > 0 && (
          <select
            aria-label={`${row.name}工作空间访问级别`}
            className={`${fieldClass} max-w-36`}
            value={access}
            disabled={busy || administrator || (own && row.access_role > 0)}
            onChange={(event) => onChange(row, Number(event.target.value))}
          >
            {Object.entries(ACCESS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        )}
        <Button type="button" variant="neutral-primary" onClick={() => setExpanded(!expanded)}>
          {expanded ? "收起项目" : `选择项目${row.project_count ? `（${row.project_count}）` : ""}`}
        </Button>
      </div>
      {access >= 15 && !administrator && (
        <fieldset className="mt-3 space-y-2 border-t border-subtle pt-3">
          <legend className="text-13 font-medium">工作区统一岗位</legend>
          <p className="text-12 text-secondary">
            所选岗位作用于工作区内所有项目，包括后续新建项目；单个项目岗位可另外设置。
          </p>
          <div className="flex flex-wrap gap-4">
            {Object.entries(DUTY_LABELS).map(([key, label]) => (
              <label key={key} className="flex items-center gap-2 text-13">
                <input
                  type="checkbox"
                  disabled={busy}
                  checked={workspaceRoles.includes(key)}
                  onChange={(event) =>
                    onChange(
                      row,
                      access,
                      event.target.checked ? [...workspaceRoles, key] : workspaceRoles.filter((role) => role !== key)
                    )
                  }
                />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      {expanded && (
        <div className="mt-3 space-y-3 border-t border-subtle pt-3">
          <label className="block text-12">
            搜索项目
            <input
              aria-label={`${row.name}搜索项目`}
              className={`${fieldClass} mt-1`}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
            />
          </label>
          {projects.error ? (
            <p role="alert" className="text-13 text-danger-primary">
              {errorMessage(projects.error)}
            </p>
          ) : !projects.data ? (
            <p role="status" className="text-13 text-secondary">
              正在加载…
            </p>
          ) : !projects.data.results.length ? (
            <p className="text-13 text-secondary">没有匹配项目。</p>
          ) : (
            projects.data.results.map((project) => {
              const change = pending[scopeKey(project)];
              const projectAccess = change?.access_role ?? project.access_role;
              const roles = change?.roles ?? project.roles;
              return (
                <div key={project.id} className="space-y-2 rounded border border-subtle p-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="flex min-w-0 flex-1 items-center gap-2 text-13">
                      <input
                        type="checkbox"
                        aria-label={`${project.name}项目访问`}
                        checked={projectAccess > 0}
                        disabled={busy || administrator || !access}
                        onChange={(event) =>
                          onChange(project, event.target.checked ? (access === 5 ? 5 : 15) : 0, roles)
                        }
                      />
                      <span className="truncate">
                        {project.name}
                        {project.identifier ? ` · ${project.identifier}` : ""}
                      </span>
                    </label>
                    {projectAccess > 0 && (
                      <select
                        aria-label={`${project.name}项目访问级别`}
                        className={`${fieldClass} max-w-36`}
                        value={projectAccess}
                        disabled={busy || administrator || !access}
                        onChange={(event) => onChange(project, Number(event.target.value), roles)}
                      >
                        {Object.entries(ACCESS_LABELS)
                          .filter(([value]) => access >= 15 || Number(value) === 5)
                          .map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                      </select>
                    )}
                  </div>
                  {projectAccess >= 15 &&
                    access >= 15 &&
                    (administrator ? (
                      <p className="text-12 text-secondary">管理员无需兼任岗位。</p>
                    ) : (
                      <fieldset disabled={busy} className="flex flex-wrap gap-x-4 gap-y-2 text-12">
                        <legend className="mb-2 text-secondary">项目岗位（可多选）</legend>
                        {!!project.inherited_roles?.length && (
                          <p className="w-full text-secondary">
                            工作区继承：{project.inherited_roles.map((role) => DUTY_LABELS[role] || role).join("、")}
                            ；以下可另加项目岗位。
                          </p>
                        )}
                        {Object.entries(DUTY_LABELS).map(([value, label]) => (
                          <label key={value} className="flex items-center gap-1.5">
                            <input
                              type="checkbox"
                              checked={roles.includes(value)}
                              onChange={(event) =>
                                onChange(
                                  project,
                                  projectAccess,
                                  event.target.checked ? [...roles, value] : roles.filter((role) => role !== value)
                                )
                              }
                            />
                            {label}
                          </label>
                        ))}
                      </fieldset>
                    ))}
                </div>
              );
            })
          )}
          {projects.data && <Paging page={page} perPage={10} count={projects.data.count} onChange={setPage} />}
        </div>
      )}
    </section>
  );
}

export function MemberScopeAccess({
  userId,
  own,
  onSaved,
}: {
  userId: string;
  own: boolean;
  onSaved: () => Promise<unknown>;
}) {
  const endpoint = `/api/quality-auth/member-scopes/${userId}/`;
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pending, setPending] = useState<ScopeChanges>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const { mutate } = useSWRConfig();
  const query = new URLSearchParams({ search, page: String(page), per_page: "10" });
  const { data, error } = useSWR(`${endpoint}?${query}`, (url: string) => qualityApi.read<Page>(url));
  const count = Object.keys(pending).length;
  const onChange = (row: ScopeRow, access: number, roles?: string[]) => {
    setPending((previous) => updateScopeChanges(previous, row, access, roles));
    setMessage("");
  };
  const save = async () => {
    setBusy(true);
    setMessage("");
    let saved = false;
    try {
      await qualityApi.write(endpoint, buildScopePayload(pending));
      saved = true;
      setPending({});
      await Promise.all([mutate((key) => typeof key === "string" && key.startsWith(endpoint)), onSaved()]);
      setMessage("已保存。");
    } catch (failure) {
      setMessage(saved ? "权限已保存，列表刷新失败，请刷新查看。" : errorMessage(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3">
      <p className="text-12 text-secondary">
        {data?.is_administrator
          ? "管理员自动管理全部工作空间和项目，无需逐项分配；如需限制访问，请先取消管理员身份。"
          : "选择工作空间和项目。取消工作空间会同时移除其项目访问。"}
      </p>
      <label className="block text-13">
        搜索工作空间
        <input
          aria-label="搜索工作空间"
          className={`${fieldClass} mt-1`}
          value={search}
          disabled={busy}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
        />
      </label>
      {error ? (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      ) : !data ? (
        <p role="status" className="text-13 text-secondary">
          正在加载…
        </p>
      ) : !data.results.length ? (
        <p className="text-13 text-secondary">没有匹配工作空间。</p>
      ) : (
        data.results.map((row) => (
          <WorkspaceScopes
            key={row.id}
            row={row}
            endpoint={endpoint}
            pending={pending}
            busy={busy}
            administrator={data.is_administrator}
            own={own}
            onChange={onChange}
          />
        ))
      )}
      {data && <Paging page={page} perPage={10} count={data.count} onChange={setPage} />}
      <div className="flex flex-wrap items-center gap-3 border-t border-subtle pt-3">
        <Button type="button" disabled={busy || !count} onClick={save}>
          {busy ? "正在保存…" : `保存${count ? `（${count}项）` : ""}`}
        </Button>
        <Button
          type="button"
          variant="neutral-primary"
          disabled={busy}
          onClick={async () => {
            if (count && !window.confirm("放弃未保存的权限修改并刷新？")) return;
            setPending({});
            setMessage("");
            await mutate((key) => typeof key === "string" && key.startsWith(endpoint));
          }}
        >
          刷新
        </Button>
      </div>
      {message && (
        <p role="status" className="text-13">
          {message}
        </p>
      )}
    </div>
  );
}
