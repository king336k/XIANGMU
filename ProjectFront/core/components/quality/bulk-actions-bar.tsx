// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
type Row = {
  id: string;
  title?: string;
  name?: string;
  version?: number;
  workflow_version?: number;
  edit_version?: number;
  archived_at?: string | null;
};
export function BulkActionsBar({
  base,
  kind,
  rows,
  archived,
  deleted = false,
  onSaved,
}: {
  base: string;
  kind: string;
  rows: Row[];
  archived: boolean;
  deleted?: boolean;
  onSaved: () => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <>
      <Button variant="neutral-primary" onClick={() => setEditing(true)}>
        {deleted ? "批量恢复删除" : archived ? "批量恢复" : "批量维护"}
      </Button>
      {editing && (
        <Modal
          title={archived ? "恢复已归档记录" : "批量维护当前页记录"}
          onClose={() => setEditing(false)}
          onSubmit={async (form) => {
            const ids = new Set(form.getAll("ids").map(String));
            const items = rows
              .filter((row) => ids.has(row.id))
              .map((row) => ({ id: row.id, version: row.version || row.workflow_version || row.edit_version }));
            if (!items.length) throw new Error("请勾选至少一条记录。");
            await qualityApi.write(`${base}bulk-actions/`, {
              resource: kind,
              action: form.get("action"),
              items,
              priority: form.get("priority") || undefined,
              reason: form.get("reason"),
            });
            await onSaved();
          }}
        >
          <Field label="操作">
            <select name="action" className={fieldClass}>
              {deleted ? (
                <option value="untrash">从回收站恢复</option>
              ) : archived ? (
                <option value="restore">恢复到正常列表</option>
              ) : (
                <>
                  <option value="archive">归档（保留历史，可恢复）</option>
                  {["cases", "suites"].includes(kind) && <option value="trash">删除（移入回收站，可恢复）</option>}
                  {kind === "cases" && <option value="priority">调整用例优先级</option>}
                </>
              )}
            </select>
          </Field>
          {kind === "cases" && !archived && (
            <Field label="优先级（调整优先级时生效）">
              <select name="priority" className={fieldClass}>
                <option value="high">高</option>
                <option value="medium">中</option>
                <option value="low">低</option>
              </select>
            </Field>
          )}
          <fieldset className="max-h-64 space-y-2 overflow-auto">
            <legend className="mb-2 text-13">选择记录（仅当前页，最多100条）</legend>
            {rows.map((row) => (
              <label key={row.id} className="flex items-center gap-2 text-13">
                <input type="checkbox" name="ids" value={row.id} />
                {row.title || row.name}
              </label>
            ))}
          </fieldset>
          <Field label="原因 *">
            <textarea required name="reason" rows={3} maxLength={4000} className={fieldClass} />
          </Field>
          <p className="text-12 text-secondary">
            全部记录先校验版本和归属，再一起修改。进行中计划、未关闭缺陷不能归档；已有执行和固定版本继续保留。
          </p>
        </Modal>
      )}
    </>
  );
}
