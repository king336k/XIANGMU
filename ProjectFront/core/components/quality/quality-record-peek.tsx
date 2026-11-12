import useSWR from "swr";
import { qualityApi, errorMessage } from "./api";
import { Modal } from "./shared";
import { DefectForm } from "./defect-form";
import { PlanDetail } from "./plan-detail";
import { CaseHistory } from "./case-history";
import type { OverviewRecord } from "./quality-overview-details";
import { can } from "./types";
import type { Context, Defect, Plan, TestCase } from "./types";
export function QualityRecordPeek({
  base,
  record,
  context,
  projectUrl,
  onClose,
  onSaved,
}: {
  base: string;
  record: OverviewRecord;
  context: Context;
  projectUrl: string;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const endpoint = `${base}${record.kind === "case" ? "cases" : record.kind === "plan" ? "plans" : "defects"}/${record.id}/`;
  const { data, error } = useSWR(endpoint, (url: string) => qualityApi.read<Defect | Plan | TestCase>(url));
  if (error || !data)
    return (
      <Modal title="记录详情" onClose={onClose}>
        <p role={error ? "alert" : "status"} className="text-13 text-secondary">
          {error ? errorMessage(error) : "正在加载…"}
        </p>
      </Modal>
    );
  if (record.kind === "defect")
    return (
      <DefectForm
        base={base}
        context={context}
        value={data as Defect}
        projectUrl={projectUrl}
        onClose={onClose}
        onSaved={onSaved}
      />
    );
  if (record.kind === "case") return <CaseHistory base={base} value={data as TestCase} currentOnly onClose={onClose} />;
  return (
    <Modal title="测试计划" width="wide" onClose={onClose}>
      <PlanDetail
        base={base}
        value={data as Plan}
        context={context}
        canWrite={can(context, "execute")}
        backLabel="返回统计明细"
        onBack={onClose}
        onCopied={() => {}}
        onSaved={onSaved}
      />
    </Modal>
  );
}
