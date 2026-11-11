// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { CustomMenu } from "@plane/ui";
import { Ellipsis, Archive, Trash2, RotateCcw } from "lucide-react";
import { qualityApi } from "./api";
import { Modal, Field, fieldClass } from "./shared";
export function RecordLifecycleActions({
  base,
  resource,
  row,
  onSaved,
}: {
  base: string;
  resource: "cases" | "suites";
  row: {
    id: string;
    title?: string;
    name?: string;
    version?: number;
    edit_version?: number;
    archived_at?: string | null;
    trashed_at?: string | null;
  };
  onSaved: () => Promise<unknown>;
}) {
  const [action, setAction] = useState<string>();
  const title = row.title || row.name || "记录";
  return (
    <>
      <CustomMenu
        placement="bottom-end"
        closeOnSelect
        customButton={
          <span
            aria-label={`更多操作：${title}`}
            className="grid size-7 place-items-center rounded text-secondary hover:bg-layer-1"
          >
            <Ellipsis className="size-4" />
          </span>
        }
      >
        {row.trashed_at ? (
          <CustomMenu.MenuItem onClick={() => setAction("untrash")}>
            <RotateCcw className="size-3.5" />
            从回收站恢复
          </CustomMenu.MenuItem>
        ) : (
          <>
            <CustomMenu.MenuItem onClick={() => setAction(row.archived_at ? "restore" : "archive")}>
              <Archive className="size-3.5" />
              {row.archived_at ? "恢复归档" : "归档"}
            </CustomMenu.MenuItem>
            <CustomMenu.MenuItem onClick={() => setAction("trash")}>
              <Trash2 className="size-3.5" />
              删除
            </CustomMenu.MenuItem>
          </>
        )}
      </CustomMenu>
      {action && (
        <Modal
          title={`${action === "trash" ? "删除" : action === "untrash" ? "恢复" : action === "archive" ? "归档" : "恢复归档"}${resource === "cases" ? "用例" : "用例集"}`}
          submitLabel={action === "trash" ? "移入回收站" : action === "archive" ? "确认归档" : "确认恢复"}
          onClose={() => setAction(undefined)}
          onSubmit={async (form) => {
            await qualityApi.write(`${base}bulk-actions/`, {
              resource,
              action,
              items: [{ id: row.id, version: row.version || row.edit_version }],
              reason: form.get("reason"),
            });
            await onSaved();
          }}
        >
          <p className="text-13 font-medium">{title}</p>
          <p className="text-12 text-secondary">
            {action === "trash"
              ? "移入回收站，可恢复。历史计划和执行证据继续保留。"
              : action === "archive"
                ? "从正常列表隐藏，可在已归档记录中恢复。"
                : "恢复后按原归档状态展示。"}
          </p>
          <Field label="操作原因 *">
            <textarea name="reason" required maxLength={4000} rows={3} className={fieldClass} />
          </Field>
        </Modal>
      )}
    </>
  );
}
