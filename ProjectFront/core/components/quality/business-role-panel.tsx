// SPDX-License-Identifier: AGPL-3.0-only
import { AccountManager } from "./account-manager";
import { useResolvedProjectParams } from "@/hooks/use-resolved-project-params";
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import type { Context } from "./types";

type RoleData = {
  enabled: boolean;
  roles: Record<string, string>;
  results: { user_id: string; name: string; role: string; roles?: string[]; is_administrator?: boolean }[];
};
const duties: Record<string, string> = {
  PLATFORM_ADMIN: "最高权限，包含项目经理、技术员、测试员和数采员的全部业务操作，无需额外兼任。",
  PROJECT_MANAGER: "项目分派、方案审核、测试验收与知识治理。",
  TECHNICIAN: "接收分派、根因分析、方案提交、修复与发起验证。",
  REGRESSION_TESTER: "维护用例与套件、安排和执行测试计划、提交结果与回归返修。",
  REPORTER: "采集数据、从真实 Session 上报异常并跟踪处理进度。",
};

export function BusinessRolePanel({
  base,
  context,
  onSaved,
  includeAccounts = true,
}: {
  includeAccounts?: boolean;
  base: string;
  context: Context;
  onSaved: () => Promise<unknown>;
}) {
  const { workspaceSlug, projectId } = useResolvedProjectParams();
  const { data, error, mutate } = useSWR(`${base}roles/`, (url: string) => qualityApi.read<RoleData>(url));
  const [editing, setEditing] = useState(false);
  const [binding, setBinding] = useState<RoleData["results"][number]>();
  const [confirmPolicy, setConfirmPolicy] = useState(false);
  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-16 font-semibold">成员与业务角色</h2>
          <p className="mt-1 text-12 text-secondary">项目成员关系控制访问范围，业务角色决定在流程中承担的职责。</p>
        </div>
        <Button
          onClick={() => {
            setBinding(undefined);
            setEditing(true);
          }}
        >
          设置成员角色
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {!data && !error && (
        <p role="status" className="text-13 text-secondary">
          正在读取业务角色…
        </p>
      )}
      {data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-subtle p-4">
            <div>
              <h3 className="text-13 font-medium">{data.enabled ? "业务角色权限已启用" : "当前沿用平台成员权限"}</h3>
              <p className="mt-1 text-12 text-secondary">
                管理员拥有全部业务权限；项目经理、技术员、测试员和数采员按职责操作。未分配业务角色的成员只能查看。
              </p>
            </div>
            {context.is_administrator && (
              <Button variant="neutral-primary" onClick={() => setConfirmPolicy(true)}>
                {data.enabled ? "调整权限策略" : "启用业务角色"}
              </Button>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-13">
              <thead>
                <tr className="border-b border-subtle text-secondary">
                  <th className="py-3">成员</th>
                  <th>业务角色</th>
                  <th>职责</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((row) => (
                  <tr key={row.user_id} className="border-b border-subtle">
                    <td className="py-4 pr-3">{row.name}</td>
                    <td className="pr-3 whitespace-nowrap">
                      {row.is_administrator
                        ? "管理员"
                        : (row.roles || [row.role])
                            .filter((role) => role !== "PLATFORM_ADMIN")
                            .map((role) => data.roles[role])
                            .join("、") || "项目成员"}
                    </td>
                    <td className="pr-3 text-12 text-secondary">
                      {row.is_administrator
                        ? duties.PLATFORM_ADMIN
                        : (row.roles || [row.role])
                            .filter((role) => role !== "PLATFORM_ADMIN")
                            .map((role) => duties[role])
                            .join("；")}
                    </td>
                    <td>
                      {!row.is_administrator && (
                        <button
                          className="text-accent-primary"
                          onClick={() => {
                            setBinding(row);
                            setEditing(true);
                          }}
                        >
                          编辑
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.results.length === 0 && (
            <p className="text-13 text-secondary">尚未分配业务角色。先设置项目经理和其他岗位，再启用权限策略。</p>
          )}
        </>
      )}
      {editing && data && (
        <Modal
          title="设置业务角色"
          onClose={() => setEditing(false)}
          onSubmit={async (form) => {
            await qualityApi.write(`${base}roles/`, { user_id: form.get("user_id"), roles: form.getAll("roles") });
            await mutate();
            await onSaved();
          }}
        >
          <Field label="项目成员">
            <select required name="user_id" defaultValue={binding?.user_id || ""} className={fieldClass}>
              <option value="">选择项目成员</option>
              {context.members.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          </Field>
          <fieldset className="space-y-2">
            <legend className="mb-2 text-13 font-medium">业务岗位（可多选）</legend>
            {Object.entries(data.roles)
              .filter(([key]) => key !== "PLATFORM_ADMIN")
              .map(([key, label]) => (
                <label key={key} className="flex items-center gap-2 text-13">
                  <input
                    type="checkbox"
                    name="roles"
                    value={key}
                    defaultChecked={(binding?.roles || [binding?.role || "REPORTER"]).includes(key)}
                  />
                  {label}
                </label>
              ))}
          </fieldset>
          <p className="text-12 text-secondary">
            这里只分配本项目业务岗位；管理员由账号管理统一设置，拥有全部岗位权限。
          </p>
        </Modal>
      )}
      {confirmPolicy && data && (
        <Modal
          title="确认业务权限策略"
          onClose={() => setConfirmPolicy(false)}
          onSubmit={async (form) => {
            await qualityApi.write(`${base}role-policy/`, { enabled: form.get("enabled") === "true" });
            await mutate();
            await onSaved();
          }}
        >
          <Field label="权限策略">
            <select name="enabled" defaultValue={String(data.enabled || !data.results.length)} className={fieldClass}>
              <option value="true">启用五类业务角色校验</option>
              {!data.enabled && <option value="false">沿用平台成员权限</option>}
            </select>
          </Field>
          <p className="text-13 text-secondary">
            启用前请确认已有可用的项目经理与管理员。角色和策略变更均保留审计记录。
          </p>
        </Modal>
      )}
      {includeAccounts && workspaceSlug && projectId && (
        <AccountManager
          project={{ workspace: workspaceSlug, id: projectId }}
          onSaved={async () => {
            await mutate();
            await onSaved();
          }}
        />
      )}
    </section>
  );
}
