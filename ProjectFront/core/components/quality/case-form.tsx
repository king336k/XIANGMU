import { PagedRecordSelect } from "./paged-record-select";
// SPDX-License-Identifier: AGPL-3.0-only
import { useMemo, useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { priorityNames } from "./types";
import type { Context, Revision, TestCase } from "./types";

export function CaseForm({
  base,
  context,
  value,
  copy = false,
  requirementId,
  onClose,
  onSaved,
}: {
  base: string;
  context: Context;
  value?: TestCase;
  copy?: boolean;
  requirementId?: string;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const [steps, setSteps] = useState(
    (value?.steps ?? [{ action: "", expected: "", localId: crypto.randomUUID() }]).map((step) => ({
      action: step.action,
      expected: step.expected,
      localId: crypto.randomUUID(),
    }))
  );
  const [selectedRevision, setSelectedRevision] = useState("");
  const { data: detail } = useSWR(value ? `${base}cases/${value.id}/` : null, (url: string) =>
    qualityApi.read<TestCase & { revisions: Revision[] }>(url)
  );
  const historical = detail?.revisions.find((r) => r.id === selectedRevision);
  const historicalSteps = useMemo(
    () => historical?.snapshot.steps.map((step) => ({ step, key: crypto.randomUUID() })) ?? [],
    [historical?.snapshot.steps]
  );
  return (
    <Modal
      title={copy ? "复制测试用例" : value ? `编辑用例 · 当前 v${value.version}` : "新建测试用例"}
      onClose={onClose}
      onSubmit={
        context.can_write
          ? async (form) => {
              await qualityApi.write(
                `${base}cases/${value && !copy ? `${value.id}/` : ""}`,
                {
                  title: form.get("title"),
                  module: form.get("module"),
                  priority: form.get("priority"),
                  preconditions: form.get("preconditions"),
                  requirement_id: form.get("requirement_id") || null,
                  steps,
                  ...(value && !copy ? { expected_version: value.version } : {}),
                },
                value && !copy ? "patch" : "post"
              );
              await onSaved();
            }
          : undefined
      }
    >
      <Field label="用例标题 *">
        <input
          required
          maxLength={255}
          name="title"
          defaultValue={copy ? `${value?.title}（副本）` : value?.title}
          className={fieldClass}
          placeholder="例如：正确账号可以登录"
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="所属模块">
          <input
            name="module"
            maxLength={120}
            defaultValue={value?.module}
            className={fieldClass}
            placeholder="例如：账号与权限"
          />
        </Field>
        <Field label="优先级">
          <select name="priority" defaultValue={value?.priority ?? "medium"} className={fieldClass}>
            {Object.entries(priorityNames).map(([key, text]) => (
              <option key={key} value={key}>
                {text}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label="关联需求 / 工作项">
        <PagedRecordSelect<{ id: string; name: string; code?: string }>
          url={`${base}work-item-options/`}
          name="requirement_id"
          placeholder="暂不关联"
          searchLabel="搜索关联需求或任务"
          required={false}
          defaultValue={value?.requirement_id || requirementId || ""}
          defaultLabel={value?.requirement_title || "已关联工作项"}
          getLabel={(row) => row.name}
        />
      </Field>
      <Field label="前置条件">
        <textarea name="preconditions" rows={2} defaultValue={value?.preconditions} className={fieldClass} />
      </Field>
      <fieldset className="space-y-3">
        <legend className="mb-3 text-13 font-medium">测试步骤与预期结果 *</legend>
        {steps.map((step, index) => (
          <div key={step.localId} className="grid gap-3 rounded-md border border-subtle p-3 sm:grid-cols-2">
            <Field label={`步骤 ${index + 1}`}>
              <textarea
                required
                rows={2}
                className={fieldClass}
                value={step.action}
                onChange={(e) => setSteps(steps.map((s, i) => (i === index ? { ...s, action: e.target.value } : s)))}
              />
            </Field>
            <Field label={`预期结果 ${index + 1}`}>
              <textarea
                required
                rows={2}
                className={fieldClass}
                value={step.expected}
                onChange={(e) => setSteps(steps.map((s, i) => (i === index ? { ...s, expected: e.target.value } : s)))}
              />
            </Field>
            {steps.length > 1 && (
              <button
                type="button"
                className="text-left text-12 text-danger-primary"
                onClick={() => setSteps(steps.filter((_, i) => i !== index))}
              >
                移除步骤 {index + 1}
              </button>
            )}
          </div>
        ))}
        <Button
          variant="neutral-primary"
          disabled={steps.length >= 100}
          onClick={() => setSteps([...steps, { action: "", expected: "", localId: crypto.randomUUID() }])}
        >
          添加步骤
        </Button>
      </fieldset>
      {copy && <p className="text-12 text-secondary">复制为独立用例，从 v1 开始；原用例、原计划与执行记录保持不变。</p>}
      {value && !copy && (
        <div className="space-y-3 border-t border-subtle pt-4">
          <p className="text-12 text-secondary">保存会新增版本；已加入测试计划的旧版本保持不变。</p>
          <Field label="查看历史版本">
            <select
              className={fieldClass}
              value={selectedRevision}
              onChange={(e) => setSelectedRevision(e.target.value)}
            >
              <option value="">选择一个版本</option>
              {detail?.revisions.map((r) => (
                <option key={r.id} value={r.id}>
                  v{r.version} · {r.title}
                </option>
              ))}
            </select>
          </Field>
          {historical && (
            <div className="space-y-2 rounded-md bg-layer-1 p-3 text-12">
              <p>{historical.snapshot.preconditions}</p>
              {historicalSteps.map(({ step: s, key }, i) => (
                <p key={key}>
                  {i + 1}. {s.action} → {s.expected}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
