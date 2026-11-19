import useSWR from "swr";
import { useEffect, useRef } from "react";
import { Button } from "@plane/ui";
import { qualityApi } from "./api";
import { can } from "./types";
import type { Context, Defect } from "./types";
import { verificationNextStep } from "./verification-types";
import type { VerificationData } from "./verification-types";

type FlowAction = { tab: "diagnosis" | "solution" | "regression"; label: string };
const stageTabs = ["overview", "diagnosis", "solution", "regression", "regression"] as const;

export function defectFlowTab(stage: number) {
  return stage >= 0 && stage < stageTabs.length ? stageTabs[stage] : undefined;
}

export function defectFlowStep(value: Defect, context: Context, data: VerificationData) {
  const review = data.solution_review;
  const round = data.current;
  const manager = context.is_administrator || context.is_manager;
  const owner = manager || (!!context.user_id && value.assignee_id === context.user_id);
  const ownerName = value.assignee_name || "技术负责人";
  const author = context.is_administrator || review?.created_by_id === context.user_id;
  const authorName = context.members?.find((member) => member.id === review?.created_by_id)?.name || "方案创建人";
  const canCreate =
    can(context, "solution") &&
    (context.is_administrator || value.assignee_id === context.user_id || !context.business_roles_enabled);
  let stage = 2;
  let message = "技术负责人填写修复方案，提交项目经理或管理员审核。";
  let action: FlowAction | undefined;
  if (value.archived_at) return { stage: -1, message: "缺陷已归档，可在操作记录查看处理过程。" };
  if (value.status === "closed") return { stage: 5, message: "缺陷已关闭，处理和验证记录已保留。" };
  if (!review || review.status === "missing") {
    if (!value.assignee_id || (!value.module && ["initial", "triage"].includes(value.assignment_origin || ""))) {
      stage = 1;
      message = manager ? "核对诊断材料与责任模块，确认技术负责人。" : "等待项目经理确认诊断与技术负责人。";
      if (manager) action = { tab: "diagnosis", label: "核对诊断与分配" };
    } else {
      message = owner ? "提交修复方案，经审核通过后安排回归测试。" : `等待 ${ownerName} 提交修复方案。`;
      if (canCreate) action = { tab: "solution", label: "填写修复方案" };
    }
  } else if (["draft", "rejected"].includes(review.status)) {
    message = review.status === "rejected" ? "方案已退回，修改后重新提交审核。" : "方案草稿待提交审核。";
    if (author && can(context, "solution")) action = { tab: "solution", label: "编辑并提交方案" };
    else message = `等待 ${authorName} 修改并提交修复方案。`;
  } else if (review.status === "review") {
    const reviewer = (review.pending_reviewer_ids || review.reviewer_ids)?.includes(context.user_id || "");
    message = reviewer
      ? "请审核修复方案；通过后由技术负责人完成修复并安排测试。"
      : "等待指定项目经理或管理员审核修复方案。";
    if (reviewer && can(context, "review")) action = { tab: "solution", label: "审核修复方案" };
  } else {
    stage = 3;
    if (!round || ["open", "in_progress", "pending_tech", "needs_tech"].includes(data.defect_status)) {
      message = data.can_configure
        ? "方案已通过，确认修复版本并指派测试员，交接后开始验证。"
        : `方案已通过，等待 ${ownerName} 完成修复并安排测试。`;
      if (data.can_configure) action = { tab: "regression", label: "修复并安排测试" };
    } else if (round.status === "review") {
      stage = 4;
      message = round.can_return_test
        ? "检查本轮实测结果，全部通过后验收关闭；未通过可退回补测或修复。"
        : "测试结果已提交，等待项目经理或管理员验收。";
      if (round.can_return_test) action = { tab: "regression", label: "验收测试结果" };
    } else {
      message = verificationNextStep(round);
      if (round.can_record || round.can_configure)
        action = { tab: "regression", label: round.can_record ? "执行回归测试" : "安排回归测试" };
    }
  }
  return { stage, message, action };
}

export function DefectFlowGuidance({
  base,
  value,
  context,
  activeTab,
  onNavigate,
}: {
  base: string;
  value: Defect;
  context: Context;
  activeTab: string;
  onNavigate: (tab: string) => void;
}) {
  const { data } = useSWR(`${base}defects/${value.id}/verification/`, (url: string) =>
    qualityApi.read<VerificationData>(url)
  );
  const priorStage = useRef<number | null>(null);
  const flow = data ? defectFlowStep(value, context, data) : null;
  const stage = flow?.stage;
  const labels = ["上报反馈", "诊断分配", "修复方案", "回归测试", "验收关闭"];
  useEffect(() => {
    if (stage === undefined) return;
    if (priorStage.current === stage) return;
    priorStage.current = stage;
    const tab = defectFlowTab(stage);
    if (tab) onNavigate(tab);
  }, [stage, onNavigate]);
  if (!flow) return null;
  return (
    <section aria-label="缺陷处理流程" className="space-y-3 rounded-lg border border-subtle bg-layer-1 p-3 sm:p-4">
      <ol className="flex flex-wrap gap-x-5 gap-y-2 text-12" aria-label="处理阶段">
        {labels.map((label, index) => (
          <li
            key={label}
            className={`flex items-center gap-2 ${flow.stage === index ? "font-semibold text-accent-primary" : "text-secondary"}`}
          >
            <button
              type="button"
              aria-current={flow.stage === index ? "step" : undefined}
              onClick={() => onNavigate(stageTabs[index])}
              className="focus-visible:ring-accent-primary flex items-center gap-2 rounded focus-visible:ring-2 focus-visible:outline-none"
            >
              <span
                aria-hidden="true"
                className={`flex h-5 w-5 items-center justify-center rounded-full text-11 ${flow.stage > index ? "bg-success-subtle text-success-primary" : flow.stage === index ? "bg-accent-subtle" : "bg-layer-2"}`}
              >
                {flow.stage > index ? "✓" : index + 1}
              </span>
              {label}
            </button>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-subtle pt-3">
        <p role="status" className="min-w-0 flex-1 text-13">
          {flow.message}
        </p>
        {flow.action && flow.action.tab !== activeTab && (
          <Button type="button" size="sm" onClick={() => onNavigate(flow.action!.tab)}>
            {flow.action.label}
          </Button>
        )}
      </div>
    </section>
  );
}
