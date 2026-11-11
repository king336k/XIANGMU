// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { can } from "./types";
import type { Context } from "./types";
export const requirementStatuses: Record<string, string> = {
  draft: "待完善",
  review: "待审核",
  approved: "已确认",
  completed: "验收完成",
  cancelled: "已取消",
  archived: "已归档",
};
export function requirementTransitions(
  status: string,
  manager: boolean,
  restoredStatus = "draft"
): Record<string, string> {
  if (!manager) return status === "draft" ? { review: "submit" } : {};
  return (
    (
      {
        draft: { review: "submit", cancelled: "cancel" },
        review: { approved: "approve", draft: "return", cancelled: "cancel" },
        approved: { completed: "accept", cancelled: "cancel" },
        completed: { draft: "reopen", archived: "archive" },
        cancelled: { draft: "reopen", archived: "archive" },
        archived: { [restoredStatus]: "restore" },
      } as Record<string, Record<string, string>>
    )[status] || {}
  );
}
export function RequirementState({
  base,
  value,
  context,
  onClose,
  onSaved,
}: {
  base: string;
  value: {
    id: string;
    title: string;
    status: string;
    version: number;
    trashed_at?: string | null;
    revisions?: { version: number; snapshot: Record<string, string> }[];
  };
  context: Context;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const previous = value.revisions?.find((row) => row.version === value.version - 1)?.snapshot.status;
  const restored = previous && ["completed", "cancelled"].includes(previous) ? previous : "draft";
  const options = requirementTransitions(value.status, context.is_manager, restored);
  const [next, setNext] = useState(value.status);
  const allowed = can(context, "knowledge_write") && !value.trashed_at;
  return (
    <Modal
      title="更新需求状态"
      submitLabel="确认更新"
      onClose={onClose}
      onSubmit={
        allowed
          ? async (form) => {
              const action = options[next];
              if (!action) throw new Error("请选择新的需求状态。");
              await qualityApi.write(`${base}requirements/${value.id}/workflow/`, {
                action,
                expected_version: value.version,
                comment: form.get("comment") || "",
              });
              await onSaved();
            }
          : undefined
      }
    >
      <p className="text-13 font-medium">{value.title}</p>
      <Field label="需求状态">
        <select aria-label="需求状态" value={next} onChange={(e) => setNext(e.target.value)} className={fieldClass}>
          {Object.entries(requirementStatuses).map(([key, name]) => (
            <option key={key} value={key} disabled={key !== value.status && !options[key]}>
              {name}
              {key === value.status ? "（当前）" : !options[key] ? "（当前不可选）" : ""}
            </option>
          ))}
        </select>
      </Field>
      {value.status === "archived" && next !== value.status && (
        <p className="text-12 text-secondary">恢复后保留归档前的处理阶段；重新开展需求可再重开。</p>
      )}
      <Field label={next === "completed" ? "验收过程与结果 *" : "说明"}>
        <textarea
          name="comment"
          rows={3}
          required={next !== value.status && !["review", "approved"].includes(next)}
          maxLength={4000}
          className={fieldClass}
        />
      </Field>
    </Modal>
  );
}
