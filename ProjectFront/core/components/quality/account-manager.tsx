import { useCollectionPagination } from "./use-collection-pagination";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal, Paging } from "./shared";
export function AccountManager({
  project,
  onSaved,
  projectOnly = false,
  administratorsOnly = false,
}: {
  projectOnly?: boolean;
  administratorsOnly?: boolean;
  project?: { workspace: string; id: string };
  onSaved?: () => Promise<unknown>;
}) {
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("");
  const pagination = useCollectionPagination(`accounts:${project?.workspace}:${project?.id}:${search}:${source}`);
  const { data, error, mutate } = useSWR(
    `/api/quality-auth/accounts/?${new URLSearchParams({ ...Object.fromEntries(new URLSearchParams(pagination.query)), search, ...(source ? { source_instance: source } : {}), ...(project ? { workspace_slug: project.workspace, project_id: project.id } : {}) })}`,
    (url: string) =>
      qualityApi.read<{
        can_manage: boolean;
        can_manage_administrators?: boolean;
        count: number;
        external_partial?: boolean;
        external_limit?: number;
        external_notice?: string;
        results: {
          id: string;
          username: string;
          display_name: string;
          source: string;
          in_project?: boolean;
          is_administrator?: boolean;
        }[];
        external_results?: {
          source_instance: string;
          external_user_id: number;
          username: string;
          source: string;
          in_project?: boolean;
        }[];
        sources?: { id: string; name: string }[];
      }>(url)
  );
  const [creating, setCreating] = useState(false),
    [adding, setAdding] = useState<string>(),
    [administratorTarget, setAdministratorTarget] = useState<{
      id: string;
      username: string;
      administrator: boolean;
    }>();
  if (administratorsOnly && !data)
    return (
      <p role={error ? "alert" : "status"} className="text-13 text-secondary">
        {error ? errorMessage(error) : "正在读取账号权限…"}
      </p>
    );
  if (administratorsOnly && data?.can_manage_administrators !== true)
    return (
      <p role="alert" className="text-13 text-secondary">
        当前账号没有账号管理权限。
      </p>
    );
  if (!data?.can_manage) return error ? <p className="text-12 text-secondary">{errorMessage(error)}</p> : null;
  const people: {
    id: string;
    username: string;
    display_name: string;
    source: string;
    in_project?: boolean;
    source_instance?: string;
    external_user_id?: number;
  }[] = [
    ...data.results,
    ...(data.external_results || []).map((row) => ({
      source_instance: row.source_instance,
      external_user_id: row.external_user_id,
      username: row.username,
      source: row.source,
      in_project: row.in_project,
      id: `external:${row.source_instance}:${row.external_user_id}`,
      display_name: row.username,
    })),
  ];
  return (
    <section className="space-y-3 border-t border-subtle pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-14 font-medium">{projectOnly ? "添加项目成员" : "账号与权限"}</h2>
        {!projectOnly && (
          <Button size="sm" variant="neutral-primary" onClick={() => setCreating(true)}>
            创建项目平台账号
          </Button>
        )}
      </div>
      {!!data.sources?.length && (
        <label className="flex flex-col gap-1 text-12 text-secondary">
          账号目录
          <select
            aria-label="账号目录"
            value={source}
            onChange={(event) => setSource(event.target.value)}
            className={fieldClass}
          >
            <option value="">本平台已有账号</option>
            {data.sources.map((row) => (
              <option key={row.id} value={row.id}>
                数据平台：{row.name}（含未登录人员）
              </option>
            ))}
          </select>
        </label>
      )}
      <input
        aria-label="搜索账号"
        placeholder="搜索用户名"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className={fieldClass}
      />
      <div className="max-h-72 divide-y divide-subtle overflow-y-auto rounded border border-subtle">
        {data.results.map((row) => (
          <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-12">
            <span>
              <strong className="font-medium">{row.username}</strong>
              <span className="ml-3 text-secondary">{row.source}</span>
              {row.is_administrator && <span className="ml-2 text-secondary">管理员</span>}
            </span>
            {!projectOnly && data.can_manage_administrators && (
              <Button
                size="sm"
                variant="neutral-primary"
                onClick={() =>
                  setAdministratorTarget({ id: row.id, username: row.username, administrator: !row.is_administrator })
                }
              >
                {row.is_administrator ? "取消管理员" : "设为管理员"}
              </Button>
            )}
            {project && (
              <Button size="sm" variant="neutral-primary" disabled={row.in_project} onClick={() => setAdding(row.id)}>
                {row.in_project ? "已加入" : "加入本项目"}
              </Button>
            )}
          </div>
        ))}
      </div>
      <Paging {...pagination.paging} count={data.count} />
      {data.external_results && data.external_results.length > 0 && (
        <section className="space-y-2">
          <h4 className="text-13 font-medium">外部目录匹配账号</h4>
          <p role={data.external_partial ? "status" : undefined} className="text-12 text-secondary">
            外部目录最多显示{data.external_limit ?? 100}条匹配结果，请使用上方搜索缩小范围；不计入平台账号分页总数。
          </p>

          {people
            .filter((row) => row.external_user_id !== undefined)
            .map((row) => (
              <div key={row.id} className="flex items-center justify-between gap-2 p-3 text-12">
                <span>
                  {row.username}
                  <span className="ml-3 text-secondary">{row.source}</span>
                </span>
                {project && (
                  <Button
                    size="sm"
                    variant="neutral-primary"
                    disabled={row.in_project}
                    onClick={() => setAdding(row.id)}
                  >
                    {row.in_project ? "已加入" : "加入本项目"}
                  </Button>
                )}
              </div>
            ))}
        </section>
      )}

      {!projectOnly && administratorTarget && data.can_manage_administrators && (
        <Modal
          title={administratorTarget.administrator ? "设置管理员" : "取消管理员"}
          submitLabel="确认修改"
          onClose={() => setAdministratorTarget(undefined)}
          onSubmit={async () => {
            await qualityApi.write(
              "/api/quality-auth/accounts/",
              { user_id: administratorTarget.id, administrator: administratorTarget.administrator },
              "patch"
            );
            await mutate();
            await onSaved?.();
          }}
        >
          <p className="text-13">{administratorTarget.username}</p>
          <p className="text-12 text-secondary">
            管理员可以配置连接和凭据，并拥有全部业务权限。此操作由服务器核验当前管理员权限并保留审计。
          </p>
        </Modal>
      )}
      {creating && (
        <Modal
          title="创建项目平台账号"
          submitLabel="创建账号"
          onClose={() => setCreating(false)}
          onSubmit={async (form) => {
            await qualityApi.write("/api/quality-auth/accounts/", {
              username: form.get("username"),
              password: form.get("password"),
            });
            await mutate();
          }}
        >
          <Field label="用户名 *">
            <input
              required
              name="username"
              pattern="[a-zA-Z0-9_.-]{2,128}"
              maxLength={128}
              autoComplete="off"
              className={fieldClass}
            />
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
          <p className="text-12 text-secondary">只建立登录账号，项目和岗位可后续分配。</p>
        </Modal>
      )}
      {adding && project && (
        <Modal
          title="加入项目并分配岗位"
          onClose={() => setAdding(undefined)}
          onSubmit={async (form) => {
            const person = people.find((row) => row.id === adding);
            if (!person) throw new Error("请重新选择人员。");
            await qualityApi.write(`/api/quality-auth/accounts/${project.workspace}/projects/${project.id}/members/`, {
              ...(person.external_user_id !== undefined && person.source_instance
                ? { source_instance: person.source_instance, external_user_id: person.external_user_id }
                : { user_id: adding }),
              role: form.get("role"),
            });
            await onSaved?.();
            await mutate();
          }}
        >
          <p className="text-13">{people.find((row) => row.id === adding)?.username}</p>
          <Field label="首次岗位">
            <select name="role" className={fieldClass}>
              {Object.entries({
                PROJECT_MANAGER: "项目经理",
                TECHNICIAN: "技术员",
                REGRESSION_TESTER: "测试员",
                REPORTER: "数采员",
              }).map(([value, text]) => (
                <option key={value} value={value}>
                  {text}
                </option>
              ))}
            </select>
          </Field>
          <p className="text-12 text-secondary">加入后可在业务岗位中增加兼职。数据平台账号仍须具备来源项目授权。</p>
        </Modal>
      )}
    </section>
  );
}
