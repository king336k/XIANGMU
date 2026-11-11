// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { CasePicker } from "./case-picker";
import type { CaseOption } from "./case-selection";
import type { Suite } from "./assets-panel";
import { can } from "./types";
import type { Context } from "./types";

export function PlanForm({
  base,
  context,
  onClose,
  onSaved,
  defaultBuild,
}: {
  defaultBuild?: string;
  base: string;
  context: Context;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const [suiteId, setSuiteId] = useState("");
  const { data: suites } = useSWR(`${base}suites/all`, () => qualityApi.all<Suite>(`${base}suites/`));
  const [selected, setSelected] = useState<CaseOption[]>([]);
  return (
    <Modal
      title="新建测试计划"
      width="wide"
      onClose={onClose}
      onSubmit={async (form) => {
        if (!suiteId && !selected.length) throw new Error("请选择至少一条测试用例。");
        await qualityApi.write(`${base}plans/`, {
          name: form.get("name"),
          build: form.get("build"),
          environment: form.get("environment"),
          description: form.get("description"),
          managed: form.get("managed") === "on",
          assignee_id: form.get("assignee_id") || null,
          ...(suiteId ? { suite_id: suiteId } : { case_ids: selected.map((row) => row.id) }),
        });
        await onSaved();
      }}
    >
      <Field label="计划名称 *">
        <input required name="name" maxLength={255} className={fieldClass} placeholder="例如：v1.0 发布回归" />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="被测版本 *">
          <input
            required
            name="build"
            defaultValue={defaultBuild}
            maxLength={120}
            className={fieldClass}
            placeholder="例如：v1.0.1"
          />
        </Field>
        <Field label="测试环境 *">
          <input
            required
            name="environment"
            maxLength={255}
            className={fieldClass}
            placeholder="例如：预发布 / Chrome"
          />
        </Field>
      </div>
      <Field label="测试负责人（测试安排）">
        <select name="assignee_id" disabled={!can(context, "manage_test_plan")} className={fieldClass}>
          <option value="">未指定</option>
          {context.members
            .filter(
              (m) =>
                !context.business_roles_enabled ||
                (m.business_roles || [m.business_role]).some(
                  (role) => typeof role === "string" && ["PLATFORM_ADMIN", "REGRESSION_TESTER"].includes(role)
                )
            )
            .map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
        </select>
      </Field>
      <label className="flex items-start gap-3 rounded-md border border-subtle p-3 text-13">
        <input type="checkbox" name="managed" defaultChecked />
        <span>
          启用分派与经理验收
          <p className="mt-1 text-12 text-secondary">
            先分派/认领，记录本轮全部实际结果后提交确认，失败、阻塞、跳过均可如实反馈；退回后保留历史并开启新一轮。
          </p>
        </span>
      </label>
      <Field label="计划说明">
        <textarea name="description" rows={2} className={fieldClass} />
      </Field>
      <Field label="复用用例集（可选，也可在下方直接选用例）">
        <select
          className={fieldClass}
          value={suiteId}
          onChange={(e) => {
            setSuiteId(e.target.value);
            setSelected([]);
          }}
        >
          <option value="">手工选择用例</option>
          {suites
            ?.filter((suite) => suite.published)
            .map((suite) => (
              <option key={suite.id} value={suite.id}>
                {suite.name} · {suite.items.length} 条固定版本用例
              </option>
            ))}
        </select>
      </Field>
      {suiteId ? (
        <p className="rounded border border-subtle p-3 text-13">
          将使用所选用例集的 {suites?.find((suite) => suite.id === suiteId)?.items.length || 0}{" "}
          条固定版本用例；创建新计划，不继承旧结果。
        </p>
      ) : (
        <CasePicker base={base} selected={selected} onChange={setSelected} />
      )}
    </Modal>
  );
}
