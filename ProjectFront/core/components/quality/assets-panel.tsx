import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { RecordLifecycleActions } from "./record-lifecycle-actions";
import { DocumentImportForm } from "./document-import-form";
import { can } from "./types";
import { ExternalReleasePlans } from "./external-release-plans";
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Empty, Field, fieldClass, Modal } from "./shared";
import type { Context, Plan, Revision } from "./types";
import { CasePicker } from "./case-picker";
import type { CaseOption } from "./case-selection";
import type { RecordLayout } from "./layout-controls";
import { RecordPresentation } from "./record-presentation";

export type Suite = {
  code?: string;
  number?: number;
  created_by_name?: string;
  trashed_at: string | null;
  archived_at: string | null;
  id: string;
  name: string;
  description: string;
  published: boolean;
  edit_version: number;
  source_suite_id: string | null;
  items: { id: string; case_id: string; revision: Revision }[];
};
export type Release = {
  code?: string;
  number?: number;
  created_by_name?: string;
  id: string;
  name: string;
  version: string;
  description: string;
  status: string;
  edit_version: number;
  admitted_at: string | null;
  readiness: {
    ready: boolean;
    blockers: string[];
    plans: { id: string; name: string; build: string; status: string }[];
    open_defects: number;
  };
  admission_snapshot: object;
};

export function AssetsPanel({
  base,
  kind,
  rows,
  context,
  onSaved,
  layout = "list",
}: {
  base: string;
  kind: "suites" | "releases";
  rows: (Suite | Release)[];
  context: Context;
  onSaved: () => Promise<unknown>;
  layout?: RecordLayout;
}) {
  const [form, setForm] = useState(false);
  const [importing, setImporting] = useState(false);
  const [editingSuite, setEditingSuite] = useState<Suite>();
  const [editingRelease, setEditingRelease] = useState<Release>();
  const [copyingRelease, setCopyingRelease] = useState<Release>();
  const [copyingSuite, setCopyingSuite] = useState<Suite>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedCases, setSelectedCases] = useState<CaseOption[]>([]);
  const [detail, setDetail] = useState<Release | Suite | null>(null);
  const { data: plans } = useSWR(form && kind === "releases" ? `${base}plans/all` : null, () =>
    qualityApi.all<Plan>(`${base}plans/`)
  );
  const act = async (row: Suite | Release) => {
    setBusy(true);
    setError("");
    try {
      await qualityApi.write(
        `${base}${kind}/${row.id}/${kind === "suites" ? "publish" : "admit"}/`,
        "edit_version" in row ? { expected_version: row.edit_version } : {}
      );
      await onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <details className="text-12 text-secondary">
          <summary className="cursor-pointer">{kind === "suites" ? "用例集说明" : "发布验收条件"}</summary>
          <p className="mt-2 max-w-2xl leading-6">
            {kind === "suites"
              ? "用例集是可选的常用用例组合，例如冒烟测试、登录回归。草稿可调整，发布后固定用例版本；需要修改时复制为新草稿。普通计划也可直接选择用例。"
              : "按版本关联测试计划；本轮全部用例通过、经理确认结果且关联缺陷关闭后，才能通过发布验收。通过检查后仍需安排实际发布。"}
          </p>
        </details>
        {can(context, kind === "suites" ? "manage_case" : "manage_test") && (
          <Button
            onClick={() => {
              setEditingSuite(undefined);
              setSelectedCases([]);
              setEditingRelease(undefined);
              setForm(true);
            }}
          >
            {kind === "suites" ? "新建用例集" : "新建发布验收"}
          </Button>
        )}
      </div>
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
      {!rows.length && layout !== "table" ? (
        <Empty>
          {kind === "suites"
            ? "还没有用例集。将常用用例组织为固定版本资产。"
            : "还没有发布版本。选择被测版本与测试计划，检查发布准备情况。"}
        </Empty>
      ) : layout !== "list" ? (
        <RecordPresentation
          kind={kind}
          context={context}
          layout={layout}
          columns={["版本", "用例/计划", "说明"]}
          rows={rows.map((row) => ({
            id: row.id,
            title: row.name,
            code: row.code,
            subtitle: `创建人：${row.created_by_name || "未记录"}`,
            status: "published" in row ? (row.published ? "published" : "draft") : row.status,
            statusName:
              "published" in row
                ? row.published
                  ? "已发布"
                  : "草稿"
                : row.status === "admitted"
                  ? "检查通过"
                  : "待检查",
            values: [
              "published" in row ? `v${row.edit_version}` : row.version,
              "published" in row ? `${row.items.length} 条用例` : `${row.readiness.plans.length} 个计划`,
              row.description,
            ],
          }))}
          onOpen={(id) => setDetail(rows.find((row) => row.id === id) || null)}
        />
      ) : (
        <div className="divide-y divide-subtle rounded-md border border-subtle">
          {rows.map((row) => (
            <article key={row.id} className="space-y-3 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-14 font-medium">
                    {row.code && <span className="mr-2 text-11 text-secondary">{row.code}</span>}
                    {row.name}
                    {"published" in row && (row.archived_at || row.trashed_at) && (
                      <span className="ml-2 rounded bg-layer-1 px-2 py-0.5 text-11 text-secondary">
                        {row.trashed_at ? "已删除" : "已归档"}
                      </span>
                    )}
                    {"version" in row && <span className="ml-2 text-12 text-secondary">{row.version}</span>}
                  </h2>
                  <p className="mt-1 text-12 text-secondary">
                    创建人：{row.created_by_name || "未记录"} ·{" "}
                    {"published" in row
                      ? `${row.items.length} 条用例 · ${row.trashed_at ? "回收站" : row.archived_at ? "归档记录" : row.published ? "已发布，版本固定" : "草稿，可编辑"} · v${row.edit_version}`
                      : row.status === "admitted"
                        ? "发布验收已确认，保留当时的测试依据"
                        : row.readiness.ready
                          ? "检查通过，待项目经理确认"
                          : "还有待解决的问题"}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="neutral-primary" onClick={() => setDetail(row)}>
                    查看详情
                  </Button>
                  {"published" in row && can(context, "manage_case") && (
                    <RecordLifecycleActions base={base} resource="suites" row={row} onSaved={onSaved} />
                  )}
                  {"published" in row &&
                    !row.trashed_at &&
                    can(context, kind === "suites" ? "manage_case" : "manage_test") && (
                      <>
                        {!row.published && !row.archived_at && (
                          <Button
                            variant="neutral-primary"
                            onClick={() => {
                              setEditingSuite(row);
                              setSelectedCases(
                                row.items.map((item) => ({
                                  ...item.revision.snapshot,
                                  id: item.case_id,
                                  title: item.revision.title,
                                  version: item.revision.version,
                                }))
                              );
                              setForm(true);
                            }}
                          >
                            编辑草稿
                          </Button>
                        )}
                        <Button variant="neutral-primary" onClick={() => setCopyingSuite(row)}>
                          复制为新草稿
                        </Button>
                      </>
                    )}
                  {"readiness" in row && context.is_manager && (
                    <>
                      {row.status === "draft" && (
                        <Button
                          variant="neutral-primary"
                          onClick={() => {
                            setEditingRelease(row);
                            setEditingSuite(undefined);
                            setForm(true);
                          }}
                        >
                          编辑发布计划
                        </Button>
                      )}
                      <Button variant="neutral-primary" onClick={() => setCopyingRelease(row)}>
                        复制为新版本
                      </Button>
                    </>
                  )}
                  {(kind === "suites" ? can(context, "manage_case") : context.is_manager) &&
                    (("published" in row && !row.published && !row.archived_at && !row.trashed_at) ||
                      ("status" in row && row.status !== "admitted")) && (
                      <Button disabled={busy} onClick={() => void act(row)}>
                        {kind === "suites" ? "发布用例集" : "确认发布验收"}
                      </Button>
                    )}
                </div>
              </div>
              {"readiness" in row && row.readiness.blockers.length > 0 && (
                <ul className="list-disc space-y-1 pl-5 text-12 text-secondary">
                  {row.readiness.blockers.map((blocker) => (
                    <li key={blocker}>{blocker}</li>
                  ))}
                </ul>
              )}
            </article>
          ))}
        </div>
      )}
      {kind === "releases" && context.is_manager && <ExternalReleasePlans base={base} />}
      {kind === "releases" && context.is_manager && (
        <Button variant="neutral-primary" onClick={() => setImporting(true)}>
          导入版本清单
        </Button>
      )}
      {importing && (
        <DocumentImportForm base={base} resource="versions" onClose={() => setImporting(false)} onSaved={onSaved} />
      )}
      {form && (
        <Modal
          title={kind === "suites" ? (editingSuite ? "编辑用例集草稿" : "新建用例集") : "新建发布验收"}
          width={kind === "suites" ? "wide" : "standard"}
          onClose={() => setForm(false)}
          onSubmit={async (data) => {
            await qualityApi.write(
              `${base}${kind}/${editingSuite ? `${editingSuite.id}/` : editingRelease ? `${editingRelease.id}/` : ""}`,
              {
                name: data.get("name"),
                description: data.get("description"),
                ...(kind === "suites"
                  ? {
                      case_ids: selectedCases.map((item) => item.id),
                      ...(editingSuite ? { expected_version: editingSuite.edit_version } : {}),
                    }
                  : {
                      version: data.get("version"),
                      plan_ids: data.getAll("selected_ids"),
                      ...(editingRelease ? { expected_version: editingRelease.edit_version } : {}),
                    }),
              },
              editingSuite || editingRelease ? "patch" : "post"
            );
            await onSaved();
          }}
        >
          <Field label="名称 *">
            <input
              name="name"
              required
              maxLength={255}
              defaultValue={editingSuite?.name || editingRelease?.name}
              className={fieldClass}
            />
          </Field>
          {kind === "releases" && (
            <Field label="发布版本 *">
              <input
                name="version"
                defaultValue={editingRelease?.version}
                required
                maxLength={120}
                className={fieldClass}
                placeholder="须与测试计划中的被测版本一致"
              />
            </Field>
          )}
          <Field label="说明">
            <textarea
              name="description"
              rows={3}
              defaultValue={editingSuite?.description || editingRelease?.description}
              className={fieldClass}
            />
          </Field>
          {kind === "suites" ? (
            <CasePicker base={base} selected={selectedCases} onChange={setSelectedCases} />
          ) : (
            <fieldset className="space-y-2">
              <legend className="mb-2 text-13 font-medium">关联测试计划</legend>
              {plans ? (
                plans.map((p) => (
                  <label className="flex items-center gap-3 text-13" key={p.id}>
                    <input
                      type="checkbox"
                      name="selected_ids"
                      value={p.id}
                      defaultChecked={editingRelease?.readiness.plans.some((plan) => plan.id === p.id)}
                    />
                    {p.name} · {p.build}
                  </label>
                ))
              ) : (
                <p>正在读取计划…</p>
              )}
            </fieldset>
          )}
        </Modal>
      )}
      {copyingRelease && (
        <Modal
          title="复制为新的发布计划"
          onClose={() => setCopyingRelease(undefined)}
          onSubmit={async (data) => {
            await qualityApi.write(`${base}releases/${copyingRelease.id}/copy/`, {
              name: data.get("name"),
              version: data.get("version"),
              expected_version: copyingRelease.edit_version,
            });
            await onSaved();
          }}
        >
          <Field label="新发布名称 *">
            <input
              required
              name="name"
              defaultValue={`${copyingRelease.name}（下一版）`}
              maxLength={255}
              className={fieldClass}
            />
          </Field>
          <Field label="新版本号 *">
            <input required name="version" maxLength={120} className={fieldClass} />
          </Field>
          <p className="text-12 text-secondary">新计划为草稿，不继承原准入结论；需更新关联测试版本并重新检查。</p>
        </Modal>
      )}
      {copyingSuite && (
        <Modal
          title="复制为用例集草稿"
          onClose={() => setCopyingSuite(undefined)}
          onSubmit={async (data) => {
            await qualityApi.write(`${base}suites/${copyingSuite.id}/copy/`, {
              name: data.get("name"),
              use_latest: data.get("use_latest") === "latest",
              expected_version: copyingSuite.edit_version,
            });
            await onSaved();
          }}
        >
          <Field label="新用例集名称 *">
            <input
              required
              name="name"
              maxLength={255}
              defaultValue={`${copyingSuite.name}（下一版）`}
              className={fieldClass}
            />
          </Field>
          <Field label="用例版本">
            <select name="use_latest" className={fieldClass}>
              <option value="frozen">保留原用例集中的固定版本</option>
              <option value="latest">使用用例库的最新版本</option>
            </select>
          </Field>
          <p className="text-12 text-secondary">新建独立草稿，可以调整用例后重新发布；原用例集及其已生成计划不变。</p>
        </Modal>
      )}
      {detail && (
        <Modal title={detail.name} onClose={() => setDetail(null)}>
          {"published" in detail && can(context, "manage_case") && (
            <div className="flex justify-end">
              <RecordLifecycleActions
                base={base}
                resource="suites"
                row={detail}
                onSaved={async () => {
                  setDetail(null);
                  await onSaved();
                }}
              />
            </div>
          )}
          <p className="text-13 text-secondary">{detail.description}</p>
          {can(context, kind === "suites" ? "manage_case" : "manage_test") && (
            <div className="flex flex-wrap gap-2">
              {"published" in detail && !detail.published && !detail.archived_at && !detail.trashed_at && (
                <Button
                  variant="neutral-primary"
                  onClick={() => {
                    setEditingSuite(detail);
                    setSelectedCases(
                      detail.items.map((item) => ({
                        ...item.revision.snapshot,
                        id: item.case_id,
                        title: item.revision.title,
                        version: item.revision.version,
                      }))
                    );
                    setDetail(null);
                    setForm(true);
                  }}
                >
                  编辑草稿
                </Button>
              )}
              {"published" in detail && !detail.trashed_at && (
                <Button
                  variant="neutral-primary"
                  onClick={() => {
                    setCopyingSuite(detail);
                    setDetail(null);
                  }}
                >
                  复制为新草稿
                </Button>
              )}
              {"status" in detail && detail.status === "draft" && (
                <Button
                  variant="neutral-primary"
                  onClick={() => {
                    setEditingRelease(detail);
                    setDetail(null);
                    setForm(true);
                  }}
                >
                  编辑发布计划
                </Button>
              )}
              {(("published" in detail && !detail.published && !detail.archived_at && !detail.trashed_at) ||
                ("status" in detail && detail.status !== "admitted")) && (
                <Button
                  disabled={busy}
                  onClick={async () => {
                    await act(detail);
                    setDetail(null);
                  }}
                >
                  {"published" in detail ? "发布用例集" : "确认发布验收"}
                </Button>
              )}
            </div>
          )}
          {"items" in detail ? (
            <div className="space-y-3">
              {detail.items.map((item) => (
                <div key={item.id} className="rounded-md border border-subtle p-3">
                  <h3 className="text-13 font-medium">
                    {item.revision.title} · v{item.revision.version}
                  </h3>
                  <p className="mt-1 text-12 text-secondary">
                    {item.revision.snapshot.module || "未分模块"} · {item.revision.snapshot.steps.length} 步
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <>
              <p className="text-13">
                版本：{detail.version} · {detail.status === "admitted" ? "发布验收已通过" : "待检查"}
              </p>
              {detail.readiness.plans.map((plan) => (
                <p key={plan.id} className="text-13">
                  {plan.name} · {plan.build}
                </p>
              ))}
              {detail.admitted_at && (
                <p className="text-12 text-secondary">确认时间：{renderNumericDateTime(detail.admitted_at)}</p>
              )}
              <p className="text-12 text-secondary">此处确认测试是否满足发布条件，不会自动执行生产发布。</p>
            </>
          )}
        </Modal>
      )}
    </section>
  );
}
