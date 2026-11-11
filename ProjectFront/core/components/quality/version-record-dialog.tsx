// SPDX-License-Identifier: AGPL-3.0-only
import useSWR from "swr";
import { qualityApi, errorMessage } from "./api";
import type { Requirement } from "./requirements-workbench";
import { RequirementsWorkbench } from "./requirements-workbench";
import { RequirementState } from "./requirement-state";
import { PlanActions } from "./plan-actions";
import { PlanDetail } from "./plan-detail";
import { PlanForm } from "./plan-form";
import { DefectForm } from "./defect-form";
import { Modal, Field, fieldClass } from "./shared";
import { can } from "./types";
import type { Context, Defect, Plan } from "./types";
import type { LinkedRecordKind, LinkedRecordMode } from "./version-records";
export type VersionRecordTarget = {
  kind: Exclude<LinkedRecordKind, "issue">;
  id?: string;
  mode: LinkedRecordMode | "create";
};
export function VersionRecordDialog({
  target,
  base,
  projectUrl,
  context,
  build,
  onClose,
  onSaved,
}: {
  target: VersionRecordTarget;
  base: string;
  projectUrl: string;
  context: Context;
  build: string;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const {
    data,
    error,
    mutate: refreshRecord,
  } = useSWR(
    target.id
      ? `${base}${target.kind === "plan" ? "plans" : target.kind === "requirement" ? "requirements" : "defects"}/${target.id}/`
      : null,
    (url: string) => qualityApi.read<Plan | Defect | Requirement>(url)
  );
  const saved = async () => {
    if (target.mode !== "delete") await refreshRecord();
    await onSaved();
  };
  if (target.mode === "delete" || target.mode === "archive") {
    if (!data)
      return (
        <Modal title="正在读取记录" onClose={onClose}>
          <p className="text-13 text-secondary">{error ? errorMessage(error) : "正在加载…"}</p>
        </Modal>
      );
    const removing = target.mode === "delete";
    return (
      <Modal
        title={removing ? "删除需求" : "归档记录"}
        onClose={onClose}
        submitLabel={removing ? "移入回收站" : "确认归档"}
        onSubmit={
          context.is_manager
            ? async (form) => {
                if (target.kind === "requirement")
                  await qualityApi.write(`${base}requirements/${target.id}/workflow/`, {
                    action: removing ? "trash" : "archive",
                    expected_version: (data as Requirement).version,
                    comment: form.get("reason"),
                  });
                else
                  await qualityApi.write(`${base}bulk-actions/`, {
                    resource: target.kind === "plan" ? "plans" : "defects",
                    action: "archive",
                    items: [
                      {
                        id: target.id,
                        version:
                          target.kind === "plan" ? (data as Plan).workflow_version : (data as Defect).edit_version,
                      },
                    ],
                    reason: form.get("reason"),
                  });
                await saved();
              }
            : undefined
        }
      >
        <p className="text-13 font-medium">{"title" in data ? data.title : data.name}</p>
        <p className="text-12 text-secondary">
          {removing
            ? "移入需求回收站，可恢复；历史修订与测试证据保留。"
            : "从日常列表隐藏，历史记录保留，可在已归档记录中恢复。"}
        </p>
        <Field label="操作原因 *">
          <textarea name="reason" required maxLength={4000} rows={2} className={fieldClass} />
        </Field>
      </Modal>
    );
  }
  if (target.kind === "requirement" && target.mode === "workflow") {
    if (!data)
      return (
        <Modal title="更新需求状态" onClose={onClose}>
          <p className="text-13 text-secondary">{error ? errorMessage(error) : "正在加载…"}</p>
        </Modal>
      );
    return (
      <RequirementState base={base} value={data as Requirement} context={context} onClose={onClose} onSaved={saved} />
    );
  }

  if (target.kind === "requirement")
    return (
      <RequirementsWorkbench
        embedded={{
          id: target.id,
          mode: target.mode === "create" ? "create" : target.mode === "edit" ? "edit" : "details",
          defaultBuild: build,
          onClose,
          onSaved,
        }}
      />
    );
  if (target.mode === "create")
    return target.kind === "plan" ? (
      <PlanForm base={base} context={context} defaultBuild={build} onClose={onClose} onSaved={saved} />
    ) : (
      <DefectForm
        base={base}
        projectUrl={projectUrl}
        context={context}
        defaultBuild={build}
        onClose={onClose}
        onSaved={saved}
      />
    );
  if (!data)
    return (
      <Modal title={target.kind === "plan" ? "测试计划" : "缺陷详情"} onClose={onClose}>
        <p role={error ? "alert" : "status"} className="text-13 text-secondary">
          {error ? errorMessage(error) : "正在加载…"}
        </p>
      </Modal>
    );
  if (target.kind === "plan" && target.mode === "edit") {
    const plan = data as Plan;
    if (
      can(context, "manage_test") &&
      !plan.data_regression &&
      !plan.archived_at &&
      ["pending", "ready"].includes(plan.status) &&
      plan.summary.executed === 0
    )
      return (
        <PlanActions
          base={base}
          plan={plan}
          context={context}
          initialMode="edit"
          onDismiss={onClose}
          onSaved={saved}
          onCopied={() => {
            void onSaved();
            onClose();
          }}
        />
      );
  }
  if (target.kind === "plan")
    return (
      <Modal title="测试计划" width="wide" onClose={onClose}>
        <PlanDetail
          base={base}
          value={data as Plan}
          context={context}
          canWrite={can(context, "execute")}
          onBack={onClose}
          onSaved={saved}
          onCopied={() => {
            void onSaved();
            onClose();
          }}
        />
      </Modal>
    );
  const defect = data as Defect;
  const editable =
    can(context, "manage_defect") &&
    !defect.archived_at &&
    (context.is_manager || defect.assignee_id === context.user_id);
  return (
    <DefectForm
      key={`${defect.id}-${target.mode}`}
      base={base}
      value={defect}
      projectUrl={projectUrl}
      context={context}
      initialMode={
        editable
          ? target.mode === "edit"
            ? "details"
            : target.mode === "workflow"
              ? "workflow"
              : undefined
          : undefined
      }
      onClose={onClose}
      onSaved={saved}
    />
  );
}
