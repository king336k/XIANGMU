// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { CasePicker } from "./case-picker";
import type { CaseOption } from "./case-selection";
import type { TestCase } from "./types";
export function CaseListActions({
  base,
  selected,
  onSelection,
  onSaved,
}: {
  base: string;
  selected: TestCase[];
  onSelection: (rows: TestCase[]) => void;
  onSaved: () => Promise<unknown>;
}) {
  const [mode, setMode] = useState<"suite" | "archive" | "trash">();
  const [adjust, setAdjust] = useState(false);
  const [chosen, setChosen] = useState<CaseOption[]>([]);
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 text-12">
        <span className="text-secondary">已选 {selected.length} 条</span>
        <Button
          size="sm"
          variant="neutral-primary"
          disabled={!selected.length}
          onClick={() => {
            setChosen(
              selected.map((row) => ({
                id: row.id,
                title: row.title,
                module: row.module,
                priority: row.priority,
                version: row.version,
                requirement_title: row.requirement_title,
              }))
            );
            setAdjust(false);
            setMode("suite");
          }}
        >
          创建用例集
        </Button>
        <Button size="sm" variant="neutral-primary" disabled={!selected.length} onClick={() => setMode("archive")}>
          归档所选
        </Button>
        <Button size="sm" variant="neutral-primary" disabled={!selected.length} onClick={() => setMode("trash")}>
          删除所选
        </Button>
        {selected.length > 0 && (
          <button
            type="button"
            onClick={() => onSelection([])}
            className="rounded px-2 py-1.5 text-secondary hover:bg-layer-1"
          >
            清空选择
          </button>
        )}
      </div>
      {mode === "suite" && (
        <Modal
          title="创建用例集"
          width="wide"
          onClose={() => setMode(undefined)}
          onSubmit={async (form) => {
            await qualityApi.write(`${base}suites/`, {
              name: form.get("name"),
              description: form.get("description"),
              case_ids: chosen.map((row) => row.id),
            });
            await onSaved();
            onSelection([]);
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="用例集名称 *">
              <input name="name" required maxLength={255} className={fieldClass} />
            </Field>
            <Field label="说明">
              <input name="description" maxLength={10000} className={fieldClass} />
            </Field>
          </div>
          <div className="flex items-center justify-between text-12">
            <span>已选 {chosen.length} 条用例 · 固定当前版本</span>
            <Button variant="neutral-primary" onClick={() => setAdjust(!adjust)}>
              {adjust ? "收起选择" : "调整用例"}
            </Button>
          </div>
          {adjust ? (
            <CasePicker
              base={base}
              selected={chosen}
              onChange={(rows) => {
                if (rows.length > 500) throw new Error("最多选择500条用例。");
                setChosen(rows);
              }}
            />
          ) : (
            <div className="max-h-72 divide-y divide-subtle overflow-y-auto rounded-md border border-subtle">
              {chosen.map((row) => (
                <div key={row.id} className="flex items-center justify-between gap-3 px-3 py-2 text-12">
                  <span>{row.title}</span>
                  <span className="shrink-0 text-secondary">v{row.version}</span>
                </div>
              ))}
            </div>
          )}
        </Modal>
      )}
      {(mode === "archive" || mode === "trash") && (
        <Modal
          title={`${mode === "trash" ? "删除" : "归档"}所选用例 · ${selected.length} 条`}
          submitLabel={mode === "trash" ? "移入回收站" : "确认归档"}
          onClose={() => setMode(undefined)}
          onSubmit={async (form) => {
            if (selected.length > 100) throw new Error("单次最多归档100条，请缩小选择范围。");
            await qualityApi.write(`${base}bulk-actions/`, {
              resource: "cases",
              action: mode,
              items: selected.map((row) => ({ id: row.id, version: row.version })),
              reason: form.get("reason"),
            });
            await onSaved();
            onSelection([]);
          }}
        >
          <p className="text-13 text-secondary">
            {mode === "trash" ? "移入回收站，可恢复。历史测试记录保留。" : "归档后可恢复，历史测试记录保留。"}
          </p>
          <Field label={mode === "trash" ? "删除原因 *" : "归档原因 *"}>
            <textarea name="reason" required maxLength={4000} rows={3} className={fieldClass} />
          </Field>
        </Modal>
      )}
    </>
  );
}
