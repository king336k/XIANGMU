// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import type { TestCase } from "./types";

type Preview = {
  id: string;
  name: string;
  valid: boolean;
  case_count: number;
  rows: (TestCase & { previewId: string })[];
  errors: { row: number; fields: Record<string, unknown> }[];
};
const example = [
  {
    title: "项目成员创建任务",
    module: "项目协作",
    priority: "medium",
    steps: [{ action: "填写任务标题并保存", expected: "任务出现在项目列表" }],
  },
];
export function ImportForm({
  base,
  onClose,
  onSaved,
}: {
  base: string;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState<Preview>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const downloadTemplate = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(example, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "test-case-template.json";
    link.click();
    URL.revokeObjectURL(url);
  };
  const preflight = async () => {
    setError("");
    setBusy(true);
    setPreview(undefined);
    try {
      let rows: unknown;
      try {
        rows = JSON.parse(content);
      } catch {
        throw new Error("文件内容不是有效的 JSON，请检查格式。");
      }
      if (!Array.isArray(rows)) throw new Error("用例文件必须是 JSON 数组，请参考模板。");
      const result = await qualityApi.write<Preview>(`${base}case-imports/`, { name, cases: rows });
      setPreview({ ...result, rows: result.rows.map((row) => Object.assign(row, { previewId: crypto.randomUUID() })) });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title="导入测试用例"
      onClose={onClose}
      submitLabel="确认导入"
      onSubmit={
        preview?.valid
          ? async () => {
              await qualityApi.write(`${base}case-imports/${preview.id}/confirm/`, {});
              await onSaved();
            }
          : undefined
      }
    >
      <p className="text-12 text-secondary">
        先预检并核对用例，再确认写入。当前支持 JSON 用例文件，最多500条、2MB；不处理脚本或压缩包。
      </p>
      <Button type="button" variant="neutral-primary" onClick={downloadTemplate}>
        下载用例模板
      </Button>
      <fieldset disabled={busy} className="space-y-4">
        <Field label="导入批次名称 *">
          <input
            required
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setPreview(undefined);
            }}
            maxLength={255}
            className={fieldClass}
          />
        </Field>
        <Field label="选择用例 JSON 文件">
          <input
            type="file"
            accept=".json,application/json"
            disabled={busy}
            className={fieldClass}
            onChange={async (event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              setError("");
              setPreview(undefined);
              if (file.size > 2 * 1024 * 1024) {
                setError("文件不能超过2MB。");
                return;
              }
              try {
                setContent(await file.text());
                if (!name) setName(file.name);
              } catch {
                setError("文件读取失败，请重新选择。");
              }
            }}
          />
        </Field>
        <Field label="文件内容（可编辑）">
          <textarea
            value={content}
            onChange={(e) => {
              setContent(e.target.value);
              setPreview(undefined);
            }}
            rows={7}
            className={fieldClass}
            placeholder={JSON.stringify(example, null, 2)}
          />
        </Field>
        <Button
          type="button"
          variant="neutral-primary"
          disabled={busy || !name.trim() || !content.trim()}
          onClick={() => void preflight()}
        >
          {busy ? "正在预检…" : "预检并预览"}
        </Button>
        {error && (
          <p role="alert" className="text-13 text-danger-primary">
            {error}
          </p>
        )}
      </fieldset>
      {preview && (
        <div className="space-y-3">
          <p role="status" className="text-13">
            {preview.valid
              ? `预检通过，共 ${preview.case_count} 条用例。确认后创建用例初始版本。`
              : "预检未通过，请修改文件内容后重试。"}
          </p>
          {preview.errors.map((row) => (
            <p key={row.row} className="text-12 text-danger-primary">
              第 {row.row} 条：
              {Object.entries(row.fields)
                .map(
                  ([field, value]) =>
                    `${({ title: "用例标题", steps: "测试步骤", priority: "优先级", module: "模块", requirement_id: "关联需求", preconditions: "前置条件", unknown: "字段" } as Record<string, string>)[field] || field}：${Array.isArray(value) ? value.join("；") : JSON.stringify(value)}`
                )
                .join("；")}
            </p>
          ))}
          <ol className="max-h-48 space-y-2 overflow-auto text-12">
            {preview.rows.map((row, index) => (
              <li key={row.previewId}>
                {index + 1}. {typeof row.title === "string" ? row.title : "标题格式错误"} ·{" "}
                {Array.isArray(row.steps) ? row.steps.length : 0} 个步骤
              </li>
            ))}
          </ol>
        </div>
      )}
    </Modal>
  );
}
