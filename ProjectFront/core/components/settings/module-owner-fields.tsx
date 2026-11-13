// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { fieldClass } from "@/components/quality/shared";
import { toggleModuleOwner } from "./module-owner-data";
import type { ModuleBinding, ModuleWorkspace } from "./module-owner-data";
export function ModuleOwnerFields({
  value,
  onChange,
  eligibleWorkspaces,
  userId,
}: {
  value: ModuleBinding[];
  onChange: (value: ModuleBinding[]) => void;
  eligibleWorkspaces?: string[];
  userId?: string;
}) {
  const { data, error, mutate } = useSWR("/api/quality-auth/accounts/?per_page=1", (url: string) =>
    qualityApi.read<{ module_owner_options?: ModuleWorkspace[] }>(url)
  );
  const [workspace, setWorkspace] = useState("");
  const [name, setName] = useState(""),
    [key, setKey] = useState("");
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const choices = (data?.module_owner_options || []).filter(
    (row) => !eligibleWorkspaces || eligibleWorkspaces.includes(row.workspace_id)
  );
  const selected = choices.find((row) => row.workspace_id === workspace) || choices[0];
  return (
    <fieldset className="space-y-3 rounded-md border border-subtle bg-layer-1 p-3">
      <legend className="px-1 text-13 font-medium">模块责任</legend>
      {error ? (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error)}
        </p>
      ) : !data ? (
        <p role="status" className="text-12 text-secondary">
          正在读取模块…
        </p>
      ) : !choices.length ? (
        <p className="text-12 text-secondary">分配技术员岗位后可设置模块责任。</p>
      ) : (
        <>
          <select
            aria-label="模块责任工作空间"
            className={fieldClass}
            value={selected?.workspace_id || ""}
            onChange={(event) => setWorkspace(event.target.value)}
          >
            {choices.map((row) => (
              <option key={row.workspace_id} value={row.workspace_id}>
                {row.workspace_name}
              </option>
            ))}
          </select>
          <div className="grid gap-2 sm:grid-cols-2">
            {selected?.modules.map((module) => {
              const checked = value.some(
                (row) => row.workspace_id === selected.workspace_id && row.module_key === module.key
              );
              const replacing = checked && module.user_id && module.user_id !== userId;
              return (
                <label
                  key={module.key}
                  className={`flex cursor-pointer items-start gap-2 rounded-md border p-3 text-13 ${checked ? "border-accent-strong bg-accent-subtle text-accent-primary" : "border-subtle bg-surface-1"}`}
                >
                  <input
                    type="checkbox"
                    className="mt-1"
                    aria-label={`${selected.workspace_name} ${module.name}负责人`}
                    checked={checked}
                    onChange={(event) =>
                      onChange(toggleModuleOwner(value, selected.workspace_id, module.key, event.target.checked))
                    }
                  />
                  <span className="min-w-0">
                    <strong className="block font-medium">{module.name}</strong>
                    <span className={`mt-1 block text-11 ${replacing ? "text-warning-primary" : "text-secondary"}`}>
                      {replacing
                        ? `保存后替换 ${module.display_name || "原负责人"}`
                        : module.user_id
                          ? `当前：${module.display_name || "已设置"}`
                          : "未设置负责人"}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
          <p className="text-11 text-secondary">每个模块一位负责人，仅接收有项目权限的缺陷。</p>
          <details className="text-12">
            <summary className="cursor-pointer text-accent-primary">新增模块</summary>
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <label className="min-w-32 flex-1">
                模块名称
                <input
                  aria-label="模块名称"
                  value={name}
                  maxLength={80}
                  onChange={(event) => setName(event.target.value)}
                  className={fieldClass}
                />
              </label>
              <label className="min-w-32 flex-1">
                模块标识
                <input
                  aria-label="模块标识"
                  value={key}
                  maxLength={40}
                  placeholder="例如 camera"
                  onChange={(event) => setKey(event.target.value)}
                  className={fieldClass}
                />
              </label>
              <Button
                type="button"
                size="sm"
                disabled={busy || !name.trim() || !/^[a-z][a-z0-9_-]{1,39}$/.test(key)}
                onClick={async () => {
                  setBusy(true);
                  setMessage("");
                  try {
                    await qualityApi.write("/api/quality-auth/accounts/", {
                      action: "create_module",
                      name: name.trim(),
                      key,
                    });
                    await mutate();
                    setName("");
                    setKey("");
                  } catch (cause) {
                    setMessage(errorMessage(cause));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy ? "添加中…" : "添加"}
              </Button>
            </div>
            {message && (
              <p role="alert" className="mt-2 text-danger-primary">
                {message}
              </p>
            )}
          </details>
        </>
      )}
    </fieldset>
  );
}
