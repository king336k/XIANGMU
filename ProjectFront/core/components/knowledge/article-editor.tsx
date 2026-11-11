// SPDX-License-Identifier: AGPL-3.0-only
import { qualityApi } from "@/components/quality/api";
import { Field, fieldClass, Modal } from "@/components/quality/shared";
import type { Context } from "@/components/quality/types";
import type { Article } from "./types";

export function ArticleEditor({
  base,
  context,
  value,
  onClose,
  onSaved,
}: {
  base: string;
  context: Context;
  value?: Article;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  return (
    <Modal
      title={value ? "编辑知识草稿" : "新建知识草稿"}
      onClose={onClose}
      onSubmit={async (form) => {
        await qualityApi.write(
          `${base}articles/${value ? `${value.id}/` : ""}`,
          {
            title: form.get("title"),
            content: form.get("content"),
            tags: String(form.get("tags") || "")
              .split(/[,，]/)
              .map((v) => v.trim())
              .filter(Boolean),
            source_issue_id: form.get("source_issue_id") || null,
            ...(value ? { expected_version: value.edit_version } : {}),
          },
          value ? "patch" : "post"
        );
        await onSaved();
      }}
    >
      <Field label="知识标题 *">
        <input
          required
          name="title"
          maxLength={255}
          defaultValue={value?.title}
          className={fieldClass}
          placeholder="现象或问题，例如：采集启动失败排查"
        />
      </Field>
      <Field label="内容 *">
        <textarea
          required
          name="content"
          rows={12}
          maxLength={100000}
          defaultValue={value?.content}
          className={fieldClass}
          placeholder="记录适用范围、现象、原因、处理步骤和验证方法。请勿填写密码或令牌。"
        />
      </Field>
      <Field label="标签（用逗号分隔）">
        <input name="tags" defaultValue={value?.tags.join(", ")} className={fieldClass} />
      </Field>
      <Field label="来源工作项">
        <select name="source_issue_id" defaultValue={value?.source_issue_id ?? ""} className={fieldClass}>
          <option value="">无关联</option>
          {value?.source_issue_id && !context.issues.some((i) => i.id === value.source_issue_id) && (
            <option value={value.source_issue_id}>已关联工作项</option>
          )}
          {context.issues.map((i) => (
            <option key={i.id} value={i.id}>
              {context.identifier}-{i.sequence_id} · {i.name}
            </option>
          ))}
        </select>
      </Field>
      <p className="text-12 text-secondary">保存为草稿，发布后用于检索和问答。更新期间仍使用原发布版。</p>
    </Modal>
  );
}
