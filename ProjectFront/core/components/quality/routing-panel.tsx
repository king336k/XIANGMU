// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import type { Context, Defect } from "./types";

type Settings = { enabled: boolean; departments: string[]; components: string[]; version: number };
type Routing = Settings & { department: string; component: string; edit_version: number; can_edit: boolean };

export function RoutingPanel({
  base,
  value,
  context,
  onChanged,
}: {
  base: string;
  value: Defect;
  context: Context;
  onChanged: (row: Defect) => Promise<void>;
}) {
  const url = `${base}defects/${value.id}/routing/`;
  const { data, error, mutate } = useSWR([url, value.edit_version], () => qualityApi.read<Routing>(url));
  const [editing, setEditing] = useState(false);
  const [configuring, setConfiguring] = useState<Settings>();
  const [actionError, setActionError] = useState("");
  if (!data)
    return error ? (
      <p role="alert" className="text-12 text-danger-primary">
        {errorMessage(error)}
      </p>
    ) : null;
  if (!data.enabled && !context.is_manager && !data.department && !data.component) return null;
  return (
    <section className="space-y-3 border-t border-subtle pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-13 font-medium">责任路由（可选）</h3>
        <div className="flex flex-wrap gap-2">
          {data.enabled && data.can_edit && (
            <Button variant="neutral-primary" onClick={() => setEditing(true)}>
              调整部门 / 组件
            </Button>
          )}
          {context.is_manager && (
            <button
              type="button"
              className="text-12 text-accent-primary"
              onClick={() => {
                setActionError("");
                void qualityApi
                  .read<Settings>(`${base}collaboration-settings/`)
                  .then(setConfiguring)
                  .catch((e) => setActionError(errorMessage(e)));
              }}
            >
              配置路由选项
            </button>
          )}
        </div>
      </div>
      {(data.enabled || data.department || data.component) && (
        <p className="text-12 text-secondary">
          部门：{data.department || "未指定"} · 组件：{data.component || "未指定"}
          {!data.enabled && "（项目已停用路由，保留历史归属）"}
        </p>
      )}
      {actionError && (
        <p role="alert" className="text-12 text-danger-primary">
          {actionError}
        </p>
      )}
      {editing && (
        <Modal
          title="调整责任路由"
          onClose={() => setEditing(false)}
          onSubmit={async (form) => {
            await qualityApi.write(
              url,
              {
                department: form.get("department"),
                component: form.get("component"),
                expected_version: data.edit_version,
              },
              "patch"
            );
            await mutate();
            await onChanged(await qualityApi.read<Defect>(`${base}defects/${value.id}/`));
          }}
        >
          <p className="text-12 text-secondary">不改变负责人、协作者或权限，两项均可留空。</p>
          {(
            [
              ["department", "责任部门", data.departments, data.department],
              ["component", "组件", data.components, data.component],
            ] as const
          ).map(([name, label, choices, selected]) => (
            <Field key={name} label={label}>
              <select name={name} defaultValue={selected} className={fieldClass}>
                <option value="">未指定</option>
                {[...new Set([...choices, ...(selected ? [selected] : [])])].map((choice) => (
                  <option key={choice} value={choice}>
                    {choice}
                  </option>
                ))}
              </select>
            </Field>
          ))}
        </Modal>
      )}
      {configuring && (
        <Modal
          title="项目路由选项"
          onClose={() => setConfiguring(undefined)}
          onSubmit={async (form) => {
            const labels = (name: string) =>
              String(form.get(name) || "")
                .split(/\r?\n/)
                .map((s) => s.trim())
                .filter(Boolean);
            await qualityApi.write(`${base}collaboration-settings/`, {
              enabled: form.get("enabled") === "on",
              departments: labels("departments"),
              components: labels("components"),
              expected_version: configuring.version,
            });
            await mutate();
          }}
        >
          <label className="flex items-center gap-2 text-13">
            <input type="checkbox" name="enabled" defaultChecked={configuring.enabled} />
            在此项目启用可选部门和组件
          </label>
          <p className="text-12 text-secondary">每行一个选项，最多100项；停用或删除选项会保留缺陷已有值。</p>
          <Field label="责任部门">
            <textarea
              name="departments"
              defaultValue={configuring.departments.join("\n")}
              rows={4}
              className={fieldClass}
            />
          </Field>
          <Field label="组件">
            <textarea
              name="components"
              defaultValue={configuring.components.join("\n")}
              rows={4}
              className={fieldClass}
            />
          </Field>
        </Modal>
      )}
    </section>
  );
}
