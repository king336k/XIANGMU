import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { PagedRecordSelect } from "./paged-record-select";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";

import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { can, planStatusNames } from "./types";
import type { Context, Defect, Plan, Step } from "./types";

type Regression = { id: string; fixed_build: string; plan: Plan };
type Solution = { id: string; title: string; status: string; submitted_version: number };
export function DataRegressionPanel({
  base,
  defect,
  context,
  projectUrl,
  onVerify,
}: {
  base: string;
  defect: Defect;
  context: Context;
  projectUrl: string;
  onVerify?: () => void;
}) {
  const [creating, setCreating] = useState(false);
  const [verificationSteps, setVerificationSteps] = useState<(Step & { key: string })[]>([]);
  const { data, error, mutate } = useSWR(`${base}defects/${defect.id}/data-regressions/`, (url: string) =>
    qualityApi.read<Regression[]>(url)
  );
  if (defect.requires_data_regression === false || (defect.manual_verification_allowed && !data?.length))
    return (
      <section className="space-y-3 border-t border-subtle pt-4">
        <h4 className="text-14 font-medium">功能验证</h4>
        <p className="text-12 leading-6 text-secondary">验证页面、操作或服务结果，无需重新采集。</p>
        {defect.status === "resolved" && context.is_manager && !defect.manual_verification_allowed && onVerify && (
          <Button variant="primary" onClick={onVerify}>
            验证并关闭
          </Button>
        )}
        <Link className="text-13 text-accent-primary hover:underline" to={`${projectUrl}/quality?tab=plans`}>
          进入测试计划 →
        </Link>
      </section>
    );
  return (
    <section className="space-y-3 border-t border-subtle pt-4">
      <div className="flex flex-wrap justify-between gap-3">
        <h4 className="text-14 font-medium">重新采集与数据回归</h4>
        {defect.status === "resolved" &&
          (can(context, "manage_test_plan") ||
            (can(context, "manage_defect") && (context.is_manager || context.user_id === defect.assignee_id))) &&
          !data?.some((row) => !["completed", "cancelled", "failed"].includes(row.plan.status)) && (
            <Button variant="neutral-primary" onClick={() => setCreating(true)}>
              发起新数据回归
            </Button>
          )}
      </div>
      <p className="text-12 leading-6 text-secondary">
        修复后重新采集，由测试员核对本轮新Session和数据包，再交项目经理确认。旧数据或普通用例通过不能代替本轮验证。
      </p>
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {data?.map((row) => (
        <Link
          key={row.id}
          className="block rounded-md border border-subtle p-3 hover:bg-layer-1"
          to={`${projectUrl}/quality?tab=plans&plan=${row.plan.id}`}
        >
          <p className="text-13 font-medium">{row.plan.name}</p>
          <p className="mt-1 text-12 text-secondary">
            {planStatusNames[row.plan.status]} · 修复版本 {row.fixed_build} · 第{row.plan.round_no}轮 · 负责人：
            {row.plan.assignee_name || "待安排负责人"}
          </p>
          <span className="text-12 text-accent-primary">进入测试计划 →</span>
        </Link>
      ))}
      {creating && (
        <Modal
          title="发起新数据回归"
          onClose={() => setCreating(false)}
          onSubmit={async (form) => {
            let environmentDetails: unknown = {};
            try {
              environmentDetails = JSON.parse(String(form.get("environment_details") || "{}").trim() || "{}");
            } catch {
              throw new Error("环境详情格式有误，请填写有效的JSON对象。");
            }
            await qualityApi.write(`${base}defects/${defect.id}/data-regressions/`, {
              solution_id: form.get("solution_id"),
              environment: form.get("environment"),
              test_target: form.get("test_target"),
              ...(verificationSteps.length
                ? { verification_steps: verificationSteps.map(({ action, expected }) => ({ action, expected })) }
                : {}),
              environment_details: environmentDetails,
            });
            await mutate();
          }}
        >
          <Field label="已审核的修复方案 *">
            <PagedRecordSelect<Solution>
              url={`${base}solutions/?defect_id=${defect.id}&status=approved`}
              name="solution_id"
              placeholder="选择已通过审核的方案"
              getLabel={(row) => `${row.title} · 送审版本${row.submitted_version}`}
              isAllowed={(row) => row.status === "approved"}
            />
          </Field>
          <Field label="验证环境 *">
            <input
              required
              name="environment"
              maxLength={255}
              className={fieldClass}
              placeholder="说明设备、软件和采集环境"
            />
          </Field>
          <details className="space-y-3 rounded-md border border-subtle p-3">
            <summary className="cursor-pointer text-13">测试目标、验证步骤与复杂环境（可选）</summary>
            <Field label="本次测试目标">
              <textarea
                name="test_target"
                maxLength={4000}
                rows={2}
                className={fieldClass}
                placeholder="不填写时使用已审核方案的验证要求"
              />
            </Field>
            <div className="space-y-3">
              <p className="text-13 text-secondary">自定义验证步骤</p>
              {verificationSteps.map((step, index) => (
                <div key={step.key} className="space-y-2 rounded border border-subtle p-3">
                  <Field label={`步骤 ${index + 1} · 操作 *`}>
                    <textarea
                      required
                      maxLength={4000}
                      rows={2}
                      className={fieldClass}
                      value={step.action}
                      onChange={(event) =>
                        setVerificationSteps(
                          verificationSteps.map((row, i) =>
                            i === index ? { ...row, action: event.target.value } : row
                          )
                        )
                      }
                    />
                  </Field>
                  <Field label="预期结果 *">
                    <textarea
                      required
                      maxLength={4000}
                      rows={2}
                      className={fieldClass}
                      value={step.expected}
                      onChange={(event) =>
                        setVerificationSteps(
                          verificationSteps.map((row, i) =>
                            i === index ? { ...row, expected: event.target.value } : row
                          )
                        )
                      }
                    />
                  </Field>
                  <Button
                    type="button"
                    variant="neutral-primary"
                    onClick={() => setVerificationSteps(verificationSteps.filter((_, i) => i !== index))}
                  >
                    移除此步骤
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                variant="neutral-primary"
                disabled={verificationSteps.length >= 100}
                onClick={() =>
                  setVerificationSteps([...verificationSteps, { key: crypto.randomUUID(), action: "", expected: "" }])
                }
              >
                添加验证步骤
              </Button>
              <p className="text-12 text-secondary">不添加时使用已审核方案的验证要求。</p>
            </div>
            <Field label="结构化环境（JSON对象）">
              <textarea
                name="environment_details"
                maxLength={20000}
                rows={4}
                className={fieldClass}
                placeholder={'{"devices":[{"name":"robot-a","sensors":["camera"]}],"software":{"daq":"v2"}}'}
              />
            </Field>
            <p className="text-12 text-secondary">
              支持设备列表、软件版本、网络与采集条件；申请内容与已审核验证依据一起固定保存。
            </p>
          </details>
          <p className="text-12 text-secondary">
            创建原生测试计划并固定方案与修复版本；经理分派后，测试员关联送测后新采集的数据，不填写任意采集时间。
          </p>
        </Modal>
      )}
    </section>
  );
}

type Evidence = {
  id: string;
  round_no: number;
  source_session_id: string;
  package_id: string;
  collected_at: string;
  snapshot: { deviceName?: string };
};
export function DataEvidencePanel({
  base,
  plan,
  context,
  onSaved,
}: {
  base: string;
  plan: Plan;
  context: Context;
  onSaved: () => Promise<unknown>;
}) {
  const isAdmin = [...(context.business_roles || []), context.business_role].includes("PLATFORM_ADMIN");
  const [adding, setAdding] = useState(false);
  const { data, error, mutate } = useSWR(
    plan.data_regression ? `${base}plans/${plan.id}/data-evidence/` : null,
    (url: string) => qualityApi.read<Evidence[]>(url)
  );
  if (!plan.data_regression) return null;
  return (
    <section className="space-y-3 rounded-md border border-subtle p-4">
      <div className="flex flex-wrap justify-between gap-3">
        <h3 className="text-14 font-medium">本轮新采集数据</h3>
        {plan.status === "running" && (isAdmin || context.user_id === plan.assignee_id) && can(context, "execute") && (
          <Button variant="neutral-primary" onClick={() => setAdding(true)}>
            关联新采集Session
          </Button>
        )}
      </div>
      <p className="text-12 text-secondary">
        采集时间须晚于 {renderNumericDateTime(plan.data_regression.round_started_at)}；平台会核对任务
        {plan.data_regression.task_id}的数据归属。
      </p>
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {!data?.length && (
        <p className="text-12 text-secondary">
          尚未关联新数据；可以如实反馈失败、阻塞或无法判定，标记通过前必须补齐本轮证据。
        </p>
      )}
      {data?.map((row) => (
        <div key={row.id} className="border-t border-subtle pt-2 text-12">
          <p>
            第{row.round_no}轮 · Session：{row.source_session_id}
          </p>
          <p className="mt-1 text-secondary">
            数据包：{row.package_id} · {renderNumericDateTime(row.collected_at)}
            {row.snapshot.deviceName && ` · ${row.snapshot.deviceName}`}
          </p>
        </div>
      ))}
      {adding && (
        <Modal
          title="关联本轮新采集数据"
          onClose={() => setAdding(false)}
          onSubmit={async (form) => {
            await qualityApi.write(`${base}plans/${plan.id}/data-evidence/`, {
              source_session_id: form.get("source_session_id"),
            });
            await mutate();
            await onSaved();
          }}
        >
          <Field label="新采集Session编号 *">
            <input required name="source_session_id" maxLength={255} className={fieldClass} />
          </Field>
          <p className="text-12 text-secondary">
            使用数据平台中的实际新Session，系统从平台读取数据包和采集时间；不会根据输入文字伪造验证成功。
          </p>
        </Modal>
      )}
    </section>
  );
}
