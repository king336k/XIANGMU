import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { renderNumericDateTime } from "@plane/utils";
import { useState } from "react";
import { DefectReportEdit } from "./defect-report-edit";
// SPDX-License-Identifier: AGPL-3.0-only

import { Pencil } from "lucide-react";
import { qualityApi } from "./api";
import { DefectQuickEdit } from "./defect-quick-edit";
import { DefectReassign } from "./defect-reassign";
import type { DefectQuickField } from "./defect-quick-edit";
import { Badge, Modal } from "./shared";
import { DefectAttachments } from "./defect-attachments";
import { CollaborationPanel } from "./collaboration-panel";
import { DefectDispositionPanel, resolutionNames } from "./defect-disposition";
import { DiagnosticsPanel } from "./diagnostics-panel";
import { DeploymentSnapshots } from "./deployment-snapshots";
import { DefectTeam } from "./defect-team";
import { SolutionPanel } from "./solution-panel";
import { DefectVerificationScope } from "./defect-verification-scope";
import { DefectComments } from "./defect-comments";
import { can, severityNames } from "./types";
import type { Context, Defect } from "./types";

import { RecordProgress } from "./record-progress";

export function DefectDescription({ description }: { description?: string }) {
  const content = description || "暂未填写现象描述。";
  const structured = content.match(
    /^问题范围：([^\n]*)\n+发生阶段：([^\n]*)\n+受影响模块：([^\n]*)\n+异常类型：([^\n]*)\n+现场描述：([\s\S]*?)(?:\n{2,}时间说明：([\s\S]*))?$/
  );
  return (
    <details open className="platform-record-section group/description">
      <summary className="cursor-pointer text-13 font-semibold text-primary">现象与重现步骤</summary>
      <div className="mt-3 space-y-4">
        {structured ? (
          <>
            <dl className="grid gap-x-6 gap-y-3 rounded-md bg-layer-1 p-3 sm:grid-cols-2">
              {["问题范围", "发生阶段", "受影响模块", "异常类型"].map((label, index) => (
                <div key={label} className="min-w-0 space-y-1">
                  <dt className="text-11 text-secondary">{label}</dt>
                  <dd className="text-13 break-words text-primary">{structured[index + 1]}</dd>
                </div>
              ))}
            </dl>
            <div className="space-y-2">
              <h5 className="text-12 font-medium text-secondary">现场描述</h5>
              <p className="text-13 leading-6 break-words whitespace-pre-wrap">{structured[5]}</p>
            </div>
            {structured[6] && (
              <p className="border-accent-primary border-l-2 pl-3 text-12 leading-5 break-words whitespace-pre-wrap text-secondary">
                时间说明：{structured[6]}
              </p>
            )}
          </>
        ) : (
          <p className="text-13 leading-6 break-words whitespace-pre-wrap">{content}</p>
        )}
      </div>
    </details>
  );
}

export function DefectDetail({
  base,
  value,
  context,
  projectUrl,
  onClose,
  onEdit,
  onChanged,
}: {
  base: string;
  value: Defect;
  context: Context;
  projectUrl: string;
  onClose: () => void;
  onEdit: (mode: "details" | "workflow") => void;
  onChanged: (defect: Defect) => Promise<void>;
}) {
  const [editingReport, setEditingReport] = useState(false);
  const [reassigning, setReassigning] = useState(false);
  const [property, setProperty] = useState<DefectQuickField>();
  const [activeTab, setActiveTab] = useState(value.source_kind === "daq" ? "diagnosis" : "overview");
  const canEditReport =
    can(context, "report") &&
    value.created_by_id === context.user_id &&
    value.status !== "closed" &&
    !value.archived_at;
  const canEdit =
    can(context, "manage_defect") &&
    !value.archived_at &&
    (context.is_manager || value.assignee_id === context.user_id);
  const canEditProperties = canEdit && value.status !== "closed";
  const canReassign =
    !value.archived_at &&
    value.status !== "closed" &&
    (context.is_administrator || context.is_manager || value.assignee_id === context.user_id);
  const updateStatus = () => {
    if (value.has_verification && ["resolved", "closed"].includes(value.status)) setActiveTab("regression");
    else onEdit("workflow");
  };
  const assignee = context.members.find((member) => member.id === value.assignee_id)?.name;
  const sourceCategories: Record<string, string> = {
    DataAnomaly: "数据异常",
    UploadError: "上传异常",
    ValidationFailed: "校验失败",
    TimestampAnomaly: "时间戳异常",
    Other: "其他异常",
  };
  const sourcePrefix = value.title.match(/^(DataAnomaly|UploadError|ValidationFailed|TimestampAnomaly|Other):\s*/);
  const displayTitle = sourcePrefix ? value.title.slice(sourcePrefix[0].length) : value.title;
  return (
    <>
      <Modal title="缺陷详情" presentation="page" breadcrumb={context.project_name} onClose={onClose}>
        <div className="defect-page-heading">
          <div className="record-detail-heading flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1 space-y-2">
              {sourcePrefix && (
                <span className="inline-flex rounded border border-subtle bg-layer-1 px-2 py-0.5 text-11 text-secondary">
                  DAQ · {sourceCategories[sourcePrefix[1]]}
                </span>
              )}
              {value.code && <p className="text-12 font-medium text-accent-primary">{value.code}</p>}
              <h3 className="max-w-3xl text-18 leading-7 font-semibold break-words">{displayTitle}</h3>
            </div>
            <div className="defect-page-status flex flex-wrap items-center gap-2">
              {activeTab !== "regression" && canEditReport && !canEdit && (
                <button
                  type="button"
                  onClick={() => setEditingReport(true)}
                  className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-12 text-accent-primary hover:bg-layer-1"
                >
                  <Pencil className="size-3.5" />
                  补充上报信息
                </button>
              )}
              {canEdit ? (
                <button type="button" aria-label="更新处理状态" onClick={updateStatus}>
                  <Badge value={value.status} />
                </button>
              ) : (
                <Badge value={value.status} />
              )}
              {activeTab !== "regression" && canEdit && (
                <button
                  type="button"
                  onClick={() => onEdit("details")}
                  disabled={value.status === "closed"}
                  title={value.status === "closed" ? "重开后可编辑" : "编辑标题、现象和严重程度"}
                  className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-12 text-secondary hover:bg-layer-1 hover:text-primary"
                >
                  <Pencil className="size-3.5" />
                  编辑缺陷
                </button>
              )}
              {activeTab !== "regression" && canEdit && (
                <button
                  type="button"
                  onClick={updateStatus}
                  className="rounded-md border border-subtle px-3 py-1.5 text-12 font-medium text-accent-primary hover:bg-accent-subtle"
                >
                  {value.status === "closed"
                    ? "重开缺陷"
                    : value.status === "resolved" && context.is_manager
                      ? "回归验收"
                      : "更新处理状态"}
                </button>
              )}
            </div>
          </div>
          {activeTab !== "regression" && (
            <div className="flex flex-wrap items-center justify-between gap-2 text-12 text-secondary">
              <span>
                {value.source_kind === "daq" ? "DAQ 上报" : value.source_kind === "test" ? "测试提报" : "平台新建"} ·{" "}
                {value.source_kind === "daq" ? "采集员" : "创建人"}：
                {(value.source_kind === "daq" ? value.reporter?.username : undefined) ||
                  value.created_by_name ||
                  "未记录"}
                {value.created_at ? ` · ${renderNumericDateTime(value.created_at)}` : ""}
              </span>
              <RecordProgress base={base} kind="defect" id={value.id} projectUrl={projectUrl} />
            </div>
          )}
          {activeTab !== "regression" && (
            <details className="text-12 text-secondary">
              <summary className="cursor-pointer">更多处理</summary>
              <div className="mt-2">
                <DefectDispositionPanel base={base} value={value} context={context} onChanged={onChanged} />
              </div>
            </details>
          )}
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-subtle bg-layer-1 px-3 py-2 text-12">
            <span
              className={`rounded px-2 py-1 font-medium ${value.module ? "bg-accent-subtle text-accent-primary" : "bg-warning-subtle text-warning-primary"}`}
            >
              {value.module?.name || "模块待确认"}
            </span>
            <span className="font-medium">{assignee || value.assignee_name || "待指派"}</span>
            {value.assignment_origin === "diagnostic" && (
              <span className="rounded bg-success-subtle px-2 py-1 text-success-primary">诊断指派</span>
            )}
            {["initial", "triage"].includes(value.assignment_origin || "") && (
              <span className="rounded bg-warning-subtle px-2 py-1 text-warning-primary">
                {value.assignment_origin === "initial" ? "初分" : "待分诊"}
              </span>
            )}
            {value.assignment_origin === "manual" && (
              <span className="rounded bg-layer-2 px-2 py-1 text-secondary">人工改派</span>
            )}
            {value.assignment_reason && (
              <details className="min-w-0 flex-1 text-secondary">
                <summary className="cursor-pointer text-accent-primary">指派依据</summary>
                <p className="mt-2 break-words">{value.assignment_reason}</p>
              </details>
            )}
            {canReassign && (
              <button
                type="button"
                onClick={() => setReassigning(true)}
                className="ml-auto rounded px-2 py-1 text-accent-primary hover:bg-accent-subtle"
              >
                {value.assignee_id ? "改派" : "指派"}
              </button>
            )}
          </div>
          {value.duplicate_of_id && (
            <Link className="text-12 text-accent-primary" to={`${projectUrl}/defects?defect=${value.duplicate_of_id}`}>
              查看归并的主缺陷 →
            </Link>
          )}
        </div>
        <nav aria-label="缺陷详情内容" className="defect-page-tabs" role="tablist">
          {[
            ["overview", "概况"],
            ["diagnosis", "诊断"],
            ["solution", "处理方案"],
            ["regression", "回归测试"],
            ["comments", "评论"],
            ["history", "操作记录"],
          ].map(([key, title]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={activeTab === key}
              onClick={() => setActiveTab(key)}
              className={`focus-visible:ring-accent-primary shrink-0 rounded-md px-4 py-2 text-13 transition-colors focus-visible:ring-2 focus-visible:outline-none ${activeTab === key ? "bg-accent-subtle font-semibold text-accent-primary" : "text-secondary hover:bg-surface-1 hover:text-primary"}`}
            >
              {title}
            </button>
          ))}
        </nav>
        <div
          className={
            ["regression", "comments"].includes(activeTab)
              ? "defect-page-regression"
              : "record-detail-grid defect-page-panels"
          }
        >
          <div className="min-w-0 space-y-6">
            <div hidden={activeTab !== "overview"} className="space-y-5">
              <DefectDescription description={value.description} />
              <DeploymentSnapshots base={base} defectId={value.id} />
              <DefectAttachments base={base} defectId={value.id} context={context} />
              {value.resolution && (
                <section className="space-y-2">
                  <h4 className="text-13 font-medium">处理说明</h4>
                  <p className="text-13 leading-7 break-words whitespace-pre-wrap">{value.resolution}</p>
                </section>
              )}
            </div>
            <div hidden={activeTab !== "diagnosis"} className="platform-detail-panel">
              <DiagnosticsPanel
                base={base}
                defectId={value.id}
                context={context}
                onCompleted={async () => onChanged(await qualityApi.read<Defect>(`${base}defects/${value.id}/`))}
              />
            </div>
            <div hidden={activeTab !== "solution"} className="platform-detail-panel space-y-5">
              <details className="rounded-md border border-subtle px-4 py-3">
                <summary className="cursor-pointer text-13 text-secondary">分工与交接</summary>
                <div className="mt-3">
                  <DefectTeam base={base} value={value} context={context} onChanged={onChanged} />
                </div>
              </details>
              <SolutionPanel base={base} defectId={value.id} context={context} />
            </div>
            <div hidden={activeTab !== "regression"} className="defect-page-verification">
              <DefectVerificationScope
                projectUrl={projectUrl}
                base={base}
                value={value}
                context={context}
                onChanged={onChanged}
              />
            </div>
            <div hidden={activeTab !== "comments"} className="platform-detail-panel min-w-0">
              <DefectComments
                key={`${value.id}:${context.user_id}`}
                base={base}
                defectId={value.id}
                active={activeTab === "comments"}
              />
            </div>
            <div hidden={activeTab !== "history"} className="platform-detail-panel space-y-5">
              <CollaborationPanel base={base} value={value} context={context} onChanged={onChanged} />
            </div>
          </div>
          {!["regression", "comments"].includes(activeTab) && (
            <aside aria-label="缺陷属性" className="space-y-4 border-subtle">
              {[
                {
                  label: "严重程度",
                  text: severityNames[value.severity],
                  field: "severity",
                  action: "调整严重程度",
                  editable: true,
                },
                {
                  label: "处理分类",
                  text: resolutionNames[value.resolution_kind] || "按修复回归处理",
                  field: "disposition",
                  action: "更改处理分类",
                  editable: context.is_manager,
                },
                {
                  label: "技术负责人",
                  text: assignee || value.assignee_name || "未分派",
                  field: "assignee",
                  action: value.assignee_id ? "转派技术负责人" : "指派技术负责人",
                  editable: true,
                },
                {
                  label: "影响版本",
                  text: value.affected_build || "未填写",
                  field: "affected_build",
                  action: "编辑影响版本",
                  editable: true,
                },
                {
                  label: "修复版本",
                  text: value.fixed_build || (value.resolution_kind !== "fixed" ? "分类处理，无修复版本" : "待修复"),
                  field: "fixed_build",
                  action: "编辑修复版本",
                  editable: true,
                },
                {
                  label: "关联用例",
                  text: value.case_title || "尚未关联",
                  field: "case",
                  action: "关联测试用例",
                  editable: !value.source_execution,
                },
              ].map((item) => (
                <div key={item.field}>
                  <h4 className="px-2 text-11 text-secondary">{item.label}</h4>
                  {(item.field === "assignee" ? canReassign : canEditProperties && item.editable) ? (
                    item.field === "disposition" ? (
                      <DefectDispositionPanel
                        base={base}
                        value={value}
                        context={context}
                        onChanged={onChanged}
                        trigger={<span className="min-w-0 break-words">{item.text}</span>}
                      />
                    ) : (
                      <button
                        type="button"
                        aria-label={item.action}
                        onClick={() =>
                          item.field === "assignee" ? setReassigning(true) : setProperty(item.field as DefectQuickField)
                        }
                        className="group focus-visible:ring-accent-primary mt-1 inline-flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-13 hover:bg-layer-1 focus-visible:ring-2"
                      >
                        <span className="min-w-0 break-words">{item.text}</span>
                        <Pencil aria-hidden="true" className="size-3 shrink-0 text-accent-primary" />
                      </button>
                    )
                  ) : (
                    <p className="mt-1.5 px-2 text-13 break-words">{item.text}</p>
                  )}
                  {item.field === "case" && value.source_execution && (
                    <p className="mt-1 px-2 text-11 text-secondary">来自测试执行，保留来源用例</p>
                  )}
                </div>
              ))}
              {value.defer_until && (
                <div>
                  <h4 className="px-2 text-11 text-secondary">计划重新处理</h4>
                  <p className="mt-1.5 px-2 text-13">{value.defer_until}</p>
                </div>
              )}
              {value.repair_issue_id && (
                <div>
                  <h4 className="text-11 text-secondary">修复任务</h4>
                  <Link
                    className="mt-1.5 block text-13 text-accent-primary"
                    to={`${projectUrl}/issues/${value.repair_issue_id}`}
                  >
                    {value.repair_issue_name || "打开修复任务"} ↗
                  </Link>
                </div>
              )}
              {value.source_execution && (
                <div className="space-y-2">
                  <h4 className="text-11 text-secondary">来源测试</h4>
                  <p className="text-12">
                    {value.source_execution.plan_name} · {value.source_execution.build}
                  </p>
                  <Badge value={value.source_execution.result} />
                </div>
              )}
            </aside>
          )}
        </div>
      </Modal>
      {property && (
        <DefectQuickEdit
          base={base}
          value={value}
          context={context}
          projectUrl={projectUrl}
          field={property}
          onClose={() => setProperty(undefined)}
          onSaved={async () => {
            await onChanged(await qualityApi.read<Defect>(`${base}defects/${value.id}/`));
          }}
        />
      )}
      {reassigning && (
        <DefectReassign
          base={base}
          value={value}
          context={context}
          onClose={() => setReassigning(false)}
          onSaved={async () => {
            await onChanged(await qualityApi.read<Defect>(`${base}defects/${value.id}/`));
            setReassigning(false);
          }}
        />
      )}
      {editingReport && (
        <DefectReportEdit
          base={base}
          value={value}
          onClose={() => setEditingReport(false)}
          onSaved={async (updated) => {
            await onChanged(updated);
            setEditingReport(false);
          }}
        />
      )}
    </>
  );
}
