// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { CasePicker } from "./case-picker";
import type { CaseOption } from "./case-selection";
import { CaseForm } from "./case-form";
import { Button } from "@plane/ui";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { can } from "./types";
import type { Context, Plan, TestCase } from "./types";

export function PlanActions({
  base,
  plan,
  context,
  onSaved,
  onCopied,
  initialMode,
  onDismiss,
}: {
  initialMode?: "edit" | "copy";
  onDismiss?: () => void;
  base: string;
  plan: Plan;
  context: Context;
  onSaved: () => Promise<unknown>;
  onCopied: (plan: Plan) => void;
}) {
  const [mode, setMode] = useState<"edit" | "copy" | undefined>(initialMode);
  const [chosen, setChosen] = useState<CaseOption[]>(
    initialMode
      ? plan.items.map((item) => ({
          id: item.case_id,
          title: item.revision.title,
          version: item.current_case_version || item.revision.version,
          module: item.revision.snapshot.module || "",
          priority: item.revision.snapshot.priority || "medium",
          requirement_title: item.revision.snapshot.requirement_title || "",
        }))
      : []
  );
  const [revisionMode, setRevisionMode] = useState("frozen");
  const [adjusting, setAdjusting] = useState(false);
  const [editingCase, setEditingCase] = useState<string>();
  const { data: latestCase, mutate: refreshLatestCase } = useSWR(
    editingCase ? `${base}cases/${editingCase}/` : null,
    (url: string) => qualityApi.read<TestCase>(url)
  );
  const selectMode = (value: "copy" | "edit") => {
    setChosen(
      plan.items.map((item) => ({
        id: item.case_id,
        title: item.revision.title,
        version: item.current_case_version || item.revision.version,
        module: item.revision.snapshot.module || "",
        priority: item.revision.snapshot.priority || "medium",
        requirement_title: item.revision.snapshot.requirement_title || "",
      }))
    );
    setRevisionMode("frozen");
    setAdjusting(false);
    setMode(value);
  };
  if (!can(context, "manage_test_plan") || plan.data_regression) return null;
  return (
    <>
      {!initialMode && (
        <div className="flex flex-wrap gap-2">
          {["pending", "ready"].includes(plan.status) && plan.summary.executed === 0 && (
            <Button variant="neutral-primary" onClick={() => selectMode("edit")}>
              编辑测试安排
            </Button>
          )}
          <Button variant="neutral-primary" onClick={() => selectMode("copy")}>
            复制为新计划
          </Button>
        </div>
      )}
      {mode && (
        <Modal
          title={mode === "edit" ? "编辑测试安排" : "复制测试计划"}
          width="wide"
          onClose={() => {
            setMode(undefined);
            onDismiss?.();
          }}
          onSubmit={async (form) => {
            const result = await qualityApi.write<Plan>(
              `${base}plans/${plan.id}/${mode === "copy" ? "copy/" : ""}`,
              {
                expected_version: plan.workflow_version,
                name: form.get("name"),
                build: form.get("build"),
                environment: form.get("environment"),
                description: form.get("description"),
                case_ids: chosen.map((row) => row.id),
                use_latest: revisionMode === "latest",
                expected_case_versions: Object.fromEntries(
                  chosen
                    .filter((row) => revisionMode === "latest" || !plan.items.some((item) => item.case_id === row.id))
                    .map((row) => [row.id, row.version])
                ),
              },
              mode === "edit" ? "patch" : "post"
            );
            await onSaved();
            if (mode === "copy") onCopied(result);
          }}
        >
          <Field label="计划名称 *">
            <input
              required
              name="name"
              maxLength={255}
              defaultValue={mode === "copy" ? `${plan.name}（复测）` : plan.name}
              className={fieldClass}
            />
          </Field>
          <Field label="被测版本 *">
            <input required name="build" maxLength={120} defaultValue={plan.build} className={fieldClass} />
          </Field>
          <Field label="测试环境 *">
            <input required name="environment" maxLength={255} defaultValue={plan.environment} className={fieldClass} />
          </Field>
          <Field label="计划说明">
            <textarea
              name="description"
              rows={3}
              maxLength={20000}
              defaultValue={plan.description}
              className={fieldClass}
            />
          </Field>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <Field label={mode === "copy" ? "新计划的用例版本" : "本计划的用例版本"}>
              <select
                name="revision_mode"
                className={fieldClass}
                value={revisionMode}
                onChange={(event) => setRevisionMode(event.target.value)}
              >
                <option value="frozen">保留原计划的用例版本</option>
                <option value="latest">改用当前最新版本</option>
              </select>
            </Field>
            <Button variant="neutral-primary" onClick={() => setAdjusting(!adjusting)}>
              {adjusting ? "收起用例选择" : "调整用例"} · {chosen.length}
            </Button>
          </div>
          {adjusting && <CasePicker base={base} selected={chosen} onChange={setChosen} />}
          <div className="max-h-64 overflow-auto rounded-md border border-subtle">
            <table className="w-full text-left text-12">
              <thead className="sticky top-0 bg-layer-1 text-secondary">
                <tr>
                  <th className="p-3">用例</th>
                  <th className="p-3">原版本</th>
                  <th className="p-3">最新</th>
                  <th className="p-3">本次采用</th>
                  <th className="p-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {chosen.map((row) => {
                  const original = plan.items.find((item) => item.case_id === row.id);
                  const frozen = original?.revision.version;
                  const used = revisionMode === "latest" ? row.version : frozen || row.version;
                  return (
                    <tr key={row.id} className="border-t border-subtle">
                      <td className="max-w-80 p-3">{row.title}</td>
                      <td className="p-3">{frozen ? `v${frozen}` : "新增"}</td>
                      <td className="p-3">v{row.version}</td>
                      <td className={`p-3 ${used !== frozen ? "text-accent-primary" : "text-secondary"}`}>
                        v{used}
                        {frozen && used !== frozen ? " · 更新" : ""}
                      </td>
                      <td className="p-3">
                        <button
                          type="button"
                          onClick={() => setEditingCase(row.id)}
                          className="whitespace-nowrap text-accent-primary"
                        >
                          查看 / 编辑
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-12 text-secondary">
            {mode === "copy" ? "新计划需重新执行；原计划和历史结果保留。" : "执行后不能修改安排，可复制为新计划。"}
          </p>
        </Modal>
      )}
      {latestCase && editingCase && (
        <CaseForm
          base={base}
          context={context}
          value={latestCase}
          onClose={() => setEditingCase(undefined)}
          onSaved={async () => {
            const row = await qualityApi.read<TestCase>(`${base}cases/${editingCase}/`);
            setChosen((items) =>
              items.map((item) => (item.id === row.id ? { ...item, title: row.title, version: row.version } : item))
            );
            await refreshLatestCase();
            await onSaved();
            setEditingCase(undefined);
          }}
        />
      )}
    </>
  );
}
