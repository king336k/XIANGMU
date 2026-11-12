// SPDX-License-Identifier: AGPL-3.0-only
import { useRef, useState } from "react";
import { Modal, Field, fieldClass } from "@/components/quality/shared";
import { qualityApi } from "@/components/quality/api";
import { ScopeChoices } from "./member-scope-access";
import { updateScopeChanges } from "./member-scope-data";
import type { ScopeChanges } from "./member-scope-data";
export function CreateManagedAccount({ onSaved, onClose }: { onSaved: () => Promise<unknown>; onClose: () => void }) {
  const created = useRef(false);
  const [isCreated, setIsCreated] = useState(false);
  const [mode, setMode] = useState<"none" | "workspace" | "project">("none");
  const [pending, setPending] = useState<ScopeChanges>({});
  return (
    <Modal
      title="创建账号"
      width="wide"
      submitLabel={isCreated ? "重试刷新" : "创建账号"}
      onClose={onClose}
      onSubmit={async (form) => {
        if (!created.current) {
          const grants = Object.values(pending)
            .filter((row) => row.access_role > 0)
            .map(({ id, roles, access_role }) => ({ id, roles, access_role }));
          if (mode !== "none" && !grants.length) throw Error("请选择授权范围，或选择暂不授权。");
          await qualityApi.write("/api/quality-auth/accounts/", {
            username: form.get("username"),
            password: form.get("password"),
            grant_mode: mode,
            grants,
          });
          created.current = true;
          setIsCreated(true);
        }
        try {
          await onSaved();
        } catch {
          throw Error("账号已创建，列表刷新失败。可关闭弹窗或重试刷新。");
        }
      }}
    >
      {isCreated ? (
        <p role="status">账号已创建。</p>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="用户名">
              <input
                required
                name="username"
                pattern="[a-zA-Z0-9_.-]{2,128}"
                maxLength={128}
                autoComplete="off"
                className={fieldClass}
              />
            </Field>
            <Field label="初始密码">
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
          </div>
          <fieldset className="flex flex-wrap gap-4">
            <legend className="mb-2 text-13 font-medium">访问授权</legend>
            {(
              [
                ["none", "暂不授权"],
                ["workspace", "按工作空间"],
                ["project", "按项目"],
              ] as const
            ).map(([value, label]) => (
              <label
                key={value}
                className={`flex gap-2 rounded border px-3 py-2 text-13 ${mode === value ? "border-accent-strong bg-accent-subtle text-accent-primary" : "border-subtle"}`}
              >
                <input
                  type="radio"
                  name="grant_mode"
                  value={value}
                  checked={mode === value}
                  onChange={() => {
                    setMode(value);
                    setPending({});
                  }}
                />
                {label}
              </label>
            ))}
          </fieldset>
          {mode !== "none" && (
            <ScopeChoices
              key={mode}
              endpoint="/api/quality-auth/accounts/?scope_options=1"
              mode={mode}
              pending={pending}
              onChange={(row, access, roles) =>
                setPending((previous) => updateScopeChanges(previous, row, access, roles))
              }
            />
          )}
        </>
      )}
    </Modal>
  );
}
