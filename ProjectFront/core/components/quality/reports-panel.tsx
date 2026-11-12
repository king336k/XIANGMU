import { v4 as uuidv4 } from "uuid";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { ListFilters } from "./list-filters";
import { SavedViewControls } from "./saved-view-controls";
import { can, reasonNames } from "./types";
import { ReportDeliveryPanel } from "./report-delivery-panel";
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal, Empty, Badge, Paging } from "./shared";
import { pageSize } from "./pagination";
import type { Context, Page, Plan, Summary } from "./types";

type SavedReport = {
  code?: string;
  number?: number;
  id: string;
  name: string;
  plan_id: string | null;
  edit_version: number;
  created_at: string;
  conclusion?: { result: string; summary: string; risks: string; reviewer: string; reviewed_at: string } | null;
  snapshot?: {
    project_name: string;
    summary: Summary;
    manual_verification?: Summary;
    manual_execution_count?: number;
    plans: Plan[];
    definitions: string;
  };
};

export function ReportsPanel({ base, context }: { base: string; context: Context }) {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState(new URLSearchParams());
  const { data, error, mutate } = useSWR(`${base}reports/?${filters}&page=${page}`, (url: string) =>
    qualityApi.read<Page<SavedReport>>(url)
  );
  const { data: plans } = useSWR(`${base}plans/all`, () => qualityApi.all<Plan>(`${base}plans/`));
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<SavedReport>();
  const [requestId, setRequestId] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [concluding, setConcluding] = useState(false);
  const {
    data: detail,
    error: detailError,
    mutate: refreshDetail,
  } = useSWR(selected ? `${base}reports/${selected.id}/` : null, (url: string) => qualityApi.read<SavedReport>(url));
  const report = detail || selected;
  const download = async (value: SavedReport) => {
    setBusy(true);
    setActionError("");
    try {
      await qualityApi.download(`${base}reports/${value.id}/download/`, `quality-report-${value.id}.md`);
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-16 font-semibold">已保存的报告</h2>
        {can(context, "manage_test_plan") && (
          <Button
            onClick={() => {
              setRequestId(uuidv4());
              setCreating(true);
            }}
          >
            生成测试报告
          </Button>
        )}
      </div>
      {(error || actionError) && (
        <p role="alert" className="text-13 text-danger-primary">
          {actionError || errorMessage(error)}
        </p>
      )}
      {!data && !error && (
        <p role="status" className="text-13 text-secondary">
          正在加载报告…
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        <SavedViewControls
          kind="reports"
          params={filters}
          onApply={(next) => {
            setFilters(next);
            setPage(1);
          }}
        />
        <ListFilters
          compact
          kind="reports"
          context={context}
          params={filters}
          onApply={(next) => {
            setFilters(next);
            setPage(1);
          }}
        />
      </div>
      {data?.count === 0 && <Empty>尚无已保存报告。选择测试计划或项目汇总，保存首份报告。</Empty>}
      {data?.results.map((item) => (
        <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 border-b border-subtle py-3">
          <button className="text-left" onClick={() => setSelected(item)}>
            <p className="platform-record-link text-13">
              {item.code && <span className="mr-2 text-11 text-secondary">{item.code}</span>}
              {item.name}
            </p>
            <span className="mt-1.5 inline-flex">
              <Badge
                value={item.conclusion?.result || "review"}
                label={
                  item.conclusion
                    ? { passed: "通过", failed: "不通过", blocked: "阻塞", inconclusive: "无法判定" }[
                        item.conclusion.result
                      ] || item.conclusion.result
                    : "待验收"
                }
              />
            </span>
            <p className="mt-1 text-12 text-secondary">
              {renderNumericDateTime(item.created_at)} · {item.plan_id ? "单计划报告" : "项目汇总"}
            </p>
          </button>
          <Button variant="neutral-primary" disabled={busy} onClick={() => void download(item)}>
            下载报告
          </Button>
        </div>
      ))}
      {data && (
        <Paging
          page={page}
          count={data.count}
          perPage={pageSize(filters)}
          onChange={setPage}
          onPageSizeChange={(size) => {
            const next = new URLSearchParams(filters);
            next.set("per_page", String(size));
            setFilters(next);
            setPage(1);
          }}
        />
      )}
      {creating && (
        <Modal
          title="生成测试报告"
          onClose={() => setCreating(false)}
          onSubmit={async (form) => {
            await qualityApi.write(`${base}reports/`, {
              name: form.get("name"),
              plan_id: form.get("plan_id") || null,
              request_id: requestId,
            });
            await mutate();
          }}
        >
          <Field label="报告名称 *">
            <input name="name" required maxLength={255} className={fieldClass} />
          </Field>
          <Field label="报告范围">
            <select name="plan_id" className={fieldClass}>
              <option value="">当前项目全部测试计划</option>
              {plans?.map((plan) => (
                <option key={plan.id} value={plan.id}>
                  {plan.name} · {plan.build}
                </option>
              ))}
            </select>
          </Field>
          <p className="text-12 text-secondary">保存时固定当前用例版本、执行结果和相关缺陷状态。</p>
        </Modal>
      )}
      {report && (
        <Modal
          title="报告详情与下载"
          onClose={() => setSelected(undefined)}
          onSubmit={
            can(context, "manage_test_plan") && detail
              ? async (form) => {
                  await qualityApi.write(
                    `${base}reports/${report.id}/`,
                    { name: form.get("name"), expected_version: report.edit_version },
                    "patch"
                  );
                  await mutate();
                  await refreshDetail();
                }
              : undefined
          }
          submitLabel="保存名称"
        >
          <Field label="报告名称 *">
            <input
              name="name"
              required
              maxLength={255}
              defaultValue={report.name}
              key={report.id}
              className={fieldClass}
              readOnly={!can(context, "manage_test_plan")}
            />
          </Field>
          {detailError && (
            <p role="alert" className="text-13 text-danger-primary">
              {errorMessage(detailError)}
            </p>
          )}
          {!detail && !detailError && (
            <p role="status" className="text-13 text-secondary">
              正在加载报告内容…
            </p>
          )}
          {detail?.snapshot && (
            <>
              {detail.conclusion ? (
                <section className="space-y-2 rounded-md border border-subtle p-3 text-13">
                  <h3 className="font-medium">
                    经理最终结论 ·{" "}
                    <Badge
                      value={detail.conclusion.result}
                      label={
                        { passed: "通过", failed: "不通过", blocked: "阻塞", inconclusive: "无法判定" }[
                          detail.conclusion.result
                        ]
                      }
                    />
                  </h3>
                  <p className="whitespace-pre-wrap">{detail.conclusion.summary}</p>
                  {detail.conclusion.risks && (
                    <p className="whitespace-pre-wrap">风险与后续事项：{detail.conclusion.risks}</p>
                  )}
                  <p className="text-12 text-secondary">
                    {detail.conclusion.reviewer} · {renderNumericDateTime(detail.conclusion.reviewed_at)} ·
                    已签署，不可改写
                  </p>
                  <p className="text-12 text-secondary">此结论不代替发布准入检查；新增测试后应生成新报告。</p>
                </section>
              ) : can(context, "review") ? (
                <Button type="button" variant="neutral-primary" onClick={() => setConcluding(true)}>
                  记录经理最终结论
                </Button>
              ) : (
                <p className="text-12 text-secondary">尚无经理最终结论。</p>
              )}
              <p className="text-13">
                {detail.snapshot.project_name} · {renderNumericDateTime(detail.created_at)}
              </p>
              <div className="flex flex-wrap items-center gap-3 text-12">
                <span>执行率 {detail.snapshot.summary.execution_rate}%</span>
                <span className={detail.snapshot.summary.pass_rate ? "text-success-primary" : "text-secondary"}>
                  通过率 {detail.snapshot.summary.pass_rate}%
                </span>
                <Badge value="pending" variant="plain" label={`未执行 ${detail.snapshot.summary.pending} 条`} />
                <Badge
                  value={detail.snapshot.summary.inconclusive ? "inconclusive" : "neutral"}
                  variant="plain"
                  label={`无法判定 ${detail.snapshot.summary.inconclusive || 0} 条`}
                />
              </div>
              {detail.snapshot.manual_verification && (
                <div className="space-y-2 rounded border border-subtle p-3">
                  <h3 className="text-13 font-medium">人工验证快照</h3>
                  <div className="flex flex-wrap gap-2">
                    <Badge value="neutral" label={`共 ${detail.snapshot.manual_verification.total} 轮`} />
                    <Badge value="passed" label={`通过 ${detail.snapshot.manual_verification.passed}`} />
                    <Badge value="failed" label={`失败 ${detail.snapshot.manual_verification.failed}`} />
                    <Badge value="pending" label={`未执行 ${detail.snapshot.manual_verification.pending}`} />
                  </div>
                </div>
              )}
              {detail.snapshot.plans.map((plan) => (
                <div key={plan.id} className="space-y-2 rounded-md border border-subtle p-3 text-13">
                  <h3 className="font-medium">
                    {plan.name} · {plan.build} · {plan.environment}
                  </h3>
                  {plan.items.map((item) => (
                    <div key={item.id} className="flex flex-wrap justify-between gap-2 text-12">
                      <span>
                        {item.revision.title} · v{item.revision.version}
                      </span>
                      <Badge value={item.latest_execution?.result || "pending"} />
                      {item.latest_execution?.reason_category && (
                        <p className="w-full text-secondary">
                          原因：{reasonNames[item.latest_execution.reason_category]} · 下一步：
                          {item.latest_execution.next_action}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              ))}
              <p className="text-12 text-secondary">{detail.snapshot.definitions}</p>
              {context.is_manager && (
                <ReportDeliveryPanel base={base} reportId={detail.id} reportVersion={detail.edit_version} />
              )}
              <Button type="button" variant="neutral-primary" disabled={busy} onClick={() => void download(detail)}>
                下载此报告
              </Button>
              {actionError && (
                <p role="alert" className="text-13 text-danger-primary">
                  {actionError}
                </p>
              )}
            </>
          )}
        </Modal>
      )}
      {concluding && detail && (
        <Modal
          title="签署报告最终结论"
          onClose={() => setConcluding(false)}
          submitLabel="确认并签署结论"
          onSubmit={async (form) => {
            await qualityApi.write(`${base}reports/${detail.id}/conclusion/`, {
              expected_version: detail.edit_version,
              result: form.get("result"),
              summary: form.get("summary"),
              risks: form.get("risks"),
            });
            await refreshDetail();
          }}
        >
          <p className="text-12 text-secondary">
            结论针对这份固定快照，签署后不可覆盖。未执行、失败、阻塞、跳过、待经理验收或未关闭缺陷的报告，不能签为通过。补测后请生成新报告。
          </p>
          <Field label="最终结论 *">
            <select required name="result" className={fieldClass}>
              <option value="blocked">环境阻塞</option>
              <option value="inconclusive">无法判定，需补充验证</option>
              <option value="failed">不通过</option>
              <option value="passed">通过</option>
            </select>
          </Field>
          <Field label="结论与依据 *">
            <textarea required name="summary" maxLength={10000} rows={4} className={fieldClass} />
          </Field>
          <Field label="风险与后续事项">
            <textarea name="risks" maxLength={10000} rows={3} className={fieldClass} />
          </Field>
        </Modal>
      )}
    </section>
  );
}
