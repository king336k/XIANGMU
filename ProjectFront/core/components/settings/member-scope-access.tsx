// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { fieldClass, Paging } from "@/components/quality/shared";
import { ACCESS_LABELS, DUTY_LABELS } from "./member-management-data";
import { buildScopePayload, scopeKey, updateScopeChanges } from "./member-scope-data";
import type { ScopeChanges, ScopeRow } from "./member-scope-data";
export type ScopeMode = "workspace" | "project";
type Page = { results: ScopeRow[]; count: number; is_administrator: boolean };

export function ScopeChoices({
  endpoint,
  mode,
  pending,
  onChange,
  busy = false,
}: {
  endpoint: string;
  mode: ScopeMode;
  pending: ScopeChanges;
  onChange: (row: ScopeRow, access: number, roles?: string[]) => void;
  busy?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("all");
  const query = new URLSearchParams({
    kind: mode,
    search,
    page: String(page),
    per_page: "10",
    assignment: filter,
  });
  const { data, error } = useSWR(`${endpoint}${endpoint.includes("?") ? "&" : "?"}${query}`, (url: string) =>
    qualityApi.read<Page>(url)
  );
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-48 flex-1 text-13">
          {mode === "workspace" ? "搜索工作空间" : "搜索项目"}
          <input
            aria-label={mode === "workspace" ? "搜索工作空间" : "搜索项目"}
            className={fieldClass}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
          />
        </label>
        {!endpoint.includes("scope_options") && (
          <select
            aria-label="分配状态"
            className={`${fieldClass} max-w-36`}
            value={filter}
            onChange={(event) => {
              setFilter(event.target.value);
              setPage(1);
            }}
          >
            <option value="all">全部范围</option>
            <option value="assigned">已分配</option>
            <option value="unassigned">未分配</option>
          </select>
        )}
      </div>
      {data?.is_administrator ? (
        <p className="text-13 text-secondary">管理员 · 全部工作空间和项目</p>
      ) : error ? (
        <p role="alert">{errorMessage(error)}</p>
      ) : !data ? (
        <p role="status">正在加载…</p>
      ) : !data.results.length ? (
        <p className="text-13 text-secondary">暂无匹配范围。</p>
      ) : (
        data.results.map((row) => {
          const access = pending[scopeKey(row)]?.access_role ?? row.access_role;
          const roles = pending[scopeKey(row)]?.roles ?? row.roles;
          const inherited = mode === "project" && row.inherited_access;
          return (
            <section key={row.id} className="space-y-3 rounded border border-subtle p-3">
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex min-w-0 flex-1 items-center gap-2 text-13 font-medium">
                  <input
                    type="checkbox"
                    aria-label={`${row.name}访问`}
                    checked={access > 0}
                    disabled={busy || data.is_administrator || inherited}
                    onChange={(event) => onChange(row, event.target.checked ? 15 : 0, roles)}
                  />
                  <span>
                    {row.name}
                    {row.workspace_name && <span className="ml-2 text-12 text-secondary">{row.workspace_name}</span>}
                  </span>
                </label>
                <span className="text-12 text-secondary">
                  {inherited ? "继承工作空间" : row.access_role > 0 ? "已分配" : "未分配"}
                </span>
                {access > 0 && (
                  <select
                    aria-label={`${row.name}访问级别`}
                    className={`${fieldClass} max-w-36`}
                    value={access}
                    disabled={busy || inherited}
                    onChange={(event) => onChange(row, Number(event.target.value), roles)}
                  >
                    {Object.entries(ACCESS_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              {access >= 15 && (
                <fieldset disabled={busy} className="flex flex-wrap gap-x-4 gap-y-2 text-13">
                  <legend className="mb-2 text-12 text-secondary">
                    {mode === "workspace" ? "统一岗位 · 包含当前及后续全部项目" : "项目岗位"}
                  </legend>
                  {!!row.inherited_roles?.length && (
                    <p className="w-full text-12 text-secondary">
                      工作空间继承：
                      {row.inherited_roles
                        .map((role) => DUTY_LABELS[role])
                        .filter(Boolean)
                        .join("、")}
                    </p>
                  )}
                  {Object.entries(DUTY_LABELS).map(([value, label]) => (
                    <label key={value} className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={roles.includes(value)}
                        onChange={(event) =>
                          onChange(
                            row,
                            access,
                            event.target.checked ? [...roles, value] : roles.filter((role) => role !== value)
                          )
                        }
                      />
                      {label}
                    </label>
                  ))}
                </fieldset>
              )}
            </section>
          );
        })
      )}
      {data && <Paging page={page} perPage={10} count={data.count} onChange={setPage} />}
    </div>
  );
}

export function MemberScopeAccess({
  userId,
  own: _own,
  mode,
  onSaved,
}: {
  userId: string;
  own: boolean;
  mode?: ScopeMode;
  onSaved: () => Promise<unknown>;
}) {
  const endpoint = `/api/quality-auth/member-scopes/${userId}/`;
  const [searchMode, setSearchMode] = useState<ScopeMode>(mode || "workspace");
  const [pending, setPending] = useState<ScopeChanges>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const { mutate } = useSWRConfig();
  const count = Object.keys(pending).length;
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
      {!mode && (
        <nav aria-label="授权范围" className="flex gap-2">
          {(["workspace", "project"] as const).map((kind) => (
            <button
              key={kind}
              type="button"
              aria-current={searchMode === kind ? "page" : undefined}
              className={`rounded border px-3 py-2 text-13 ${searchMode === kind ? "border-accent-strong bg-accent-subtle text-accent-primary" : "border-subtle"}`}
              onClick={() => setSearchMode(kind)}
            >
              {kind === "workspace" ? "工作空间" : "项目"}
            </button>
          ))}
        </nav>
      )}
      <ScopeChoices
        key={mode || searchMode}
        endpoint={endpoint}
        mode={mode || searchMode}
        pending={pending}
        busy={busy}
        onChange={(row, access, roles) => {
          setPending((previous) => updateScopeChanges(previous, row, access, roles));
          setMessage("");
        }}
      />
      <div className="flex items-center gap-3 border-t border-subtle pt-3">
        <Button type="button" disabled={busy || !count} onClick={save}>
          {busy ? "正在保存…" : `保存${count ? `（${count}项）` : ""}`}
        </Button>
        <Button
          type="button"
          variant="neutral-primary"
          disabled={busy}
          onClick={async () => {
            setPending({});
            setMessage("");
            await mutate((key) => typeof key === "string" && key.startsWith(endpoint));
          }}
        >
          重置
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
