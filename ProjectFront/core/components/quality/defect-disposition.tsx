import { PagedRecordSelect } from "./paged-record-select";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import type { Context, Defect } from "./types";
import type { ReactNode } from "react";
export const resolutionNames: Record<string, string> = {
  fixed: "按修复回归处理",
  duplicate: "重复缺陷",
  deferred: "延期处理",
  not_reproducible: "无法复现",
  not_a_bug: "非缺陷",
  wont_fix: "决定不修复",
};
export function DefectDispositionPanel({
  base,
  value,
  context,
  onChanged,
  trigger,
}: {
  base: string;
  value: Defect;
  context: Context;
  onChanged: (row: Defect) => Promise<void>;
  trigger?: ReactNode;
}) {
  const [editing, setEditing] = useState(false),
    [kind, setKind] = useState("duplicate");
  if (!context.is_manager || value.status === "closed" || value.archived_at) return null;
  return (
    <>
      {trigger ? (
        <button
          type="button"
          aria-label="更改处理分类"
          onClick={() => setEditing(true)}
          className="group focus-visible:ring-accent-primary mt-1 inline-flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-13 hover:bg-layer-1 focus-visible:ring-2"
        >
          {trigger}
          <span aria-hidden="true" className="shrink-0 text-11 text-accent-primary">
            修改
          </span>
        </button>
      ) : (
        <Button variant="neutral-primary" onClick={() => setEditing(true)}>
          分类处理（重复 / 延期等）
        </Button>
      )}
      {editing && (
        <Modal
          title="经理确认缺陷处理结论"
          onClose={() => setEditing(false)}
          onSubmit={async (form) => {
            const row = await qualityApi.write<Defect>(`${base}defects/${value.id}/disposition/`, {
              kind,
              reason: form.get("reason"),
              expected_version: value.edit_version,
              ...(kind === "duplicate" ? { duplicate_of_id: form.get("duplicate_of_id") } : {}),
              ...(kind === "deferred" ? { defer_until: form.get("defer_until") } : {}),
            });
            await onChanged(row);
          }}
        >
          <Field label="处理结论">
            <select value={kind} onChange={(event) => setKind(event.target.value)} className={fieldClass}>
              {Object.entries(resolutionNames)
                .filter(([key]) => key !== "fixed")
                .map(([key, text]) => (
                  <option key={key} value={key}>
                    {text}
                  </option>
                ))}
            </select>
          </Field>
          {kind === "duplicate" && (
            <Field label="归并到主缺陷 *">
              <PagedRecordSelect<Defect>
                url={`${base}defects/`}
                name="duplicate_of_id"
                placeholder="选择当前项目的主缺陷"
                getLabel={(row) => row.title}
                isAllowed={(row) => row.id !== value.id && !row.duplicate_of_id}
              />
            </Field>
          )}
          {kind === "deferred" && (
            <Field label="计划重新处理日期 *">
              <input required type="date" name="defer_until" className={fieldClass} />
            </Field>
          )}
          <Field label="决策原因与依据 *">
            <textarea required name="reason" rows={4} maxLength={4000} className={fieldClass} />
          </Field>
          <p className="text-12 text-secondary">
            延期保持未关闭；其他分类记录经理决策后结束此条处理，不代表已经修复或通过回归。重复缺陷的主记录继续独立追踪。
          </p>
        </Modal>
      )}
    </>
  );
}
