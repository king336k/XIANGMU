import { useState } from "react";
import useSWR from "swr";
import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { PagedRecordSelect } from "./paged-record-select";
import type { Context, Defect, TestCase, Execution } from "./types";

export function DefectVerificationScope({
  base,
  value,
  context,
  onChanged,
  projectUrl,
}: {
  base: string;
  value: Defect;
  context: Context;
  projectUrl: string;
  onChanged: (value: Defect) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [method, setMethod] = useState(value.case_id ? "case" : "manual");
  const { data: executions } = useSWR(verifying && value.case_id ? `${base}executions/all` : null, () =>
    qualityApi.all<Execution>(`${base}executions/`)
  );
  const candidates = executions?.filter(
    (row) =>
      row.result === "passed" &&
      row.case_id === value.case_id &&
      row.build === value.fixed_build &&
      !!value.resolved_at &&
      new Date(row.created_at) > new Date(value.resolved_at)
  );
  const testUrl = `${projectUrl}/quality/?tab=`;
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-subtle bg-layer-1 px-3 py-3">
        <div>
          <p className="text-13 font-medium">{value.case_id ? "测试用例回归" : "人工功能验证"}</p>
          <p className="mt-1 text-12 text-secondary">
            {value.case_id
              ? `已关联：${value.case_title || value.case_id}`
              : "适用于界面、操作和现场联调；填写步骤、预期、实际结果及证据。"}
          </p>
        </div>
        {context.is_manager && value.status !== "closed" && (
          <button
            type="button"
            className="text-12 text-accent-primary"
            onClick={() => {
              setMethod(value.case_id ? "case" : "manual");
              setEditing(true);
            }}
          >
            设置验证方式
          </button>
        )}
      </div>
      <ol className="grid gap-3 text-12 sm:grid-cols-3">
        <li className="rounded-md border border-subtle p-3">
          <strong>1. 明确验证内容</strong>
          <p className="mt-2 text-secondary">记录操作步骤与预期结果，或关联可重复执行的测试用例。</p>
          <Link className="mt-2 inline-block text-accent-primary" to={`${testUrl}cases`}>
            管理 / 新增测试用例
          </Link>
        </li>
        <li className="rounded-md border border-subtle p-3">
          <strong>2. 执行并留证</strong>
          <p className="mt-2 text-secondary">在修复版本执行，记录实际结果、日志、截图或 Session；未通过时继续处理。</p>
          <Link className="mt-2 inline-block text-accent-primary" to={`${testUrl}plans`}>
            创建计划 / 执行用例
          </Link>
        </li>
        <li className="rounded-md border border-subtle p-3">
          <strong>3. 确认验收</strong>
          <p className="mt-2 text-secondary">
            先更新为“已修复，待回归”并填写修复版本，再由经理确认人工结果或选择修复后的通过执行。
          </p>
        </li>
      </ol>
      {value.status === "resolved" && context.is_manager && (
        <button
          type="button"
          className="rounded-md bg-accent-primary px-3 py-2 text-12 text-on-color"
          onClick={() => setVerifying(true)}
        >
          记录验证并关闭
        </button>
      )}
      {value.status === "closed" && <p className="text-12 text-secondary">已完成验收，验证记录保存在操作记录中。</p>}
      {editing && (
        <Modal
          title="设置验证方式"
          onClose={() => setEditing(false)}
          onSubmit={async (form) => {
            const saved = await qualityApi.write<Defect>(
              `${base}defects/${value.id}/`,
              {
                expected_version: value.edit_version,
                verification_scope: "functional",
                verification_scope_reason: form.get("reason"),
                ...(!value.source_execution ? { case_id: method === "case" ? form.get("case_id") : null } : {}),
              },
              "patch"
            );
            await onChanged(saved);
            setEditing(false);
          }}
        >
          <Field label="验证方式">
            <select
              className={fieldClass}
              value={method}
              disabled={!!value.source_execution}
              onChange={(event) => setMethod(event.target.value)}
            >
              <option value="manual">人工功能验证</option>
              <option value="case">测试用例回归</option>
            </select>
          </Field>
          {method === "case" && (
            <Field label="关联测试用例">
              <PagedRecordSelect<TestCase>
                url={`${base}cases/`}
                name="case_id"
                placeholder="选择测试用例"
                defaultValue={value.case_id || ""}
                defaultLabel={value.case_title || "已选用例"}
                getLabel={(row) => row.title}
              />
            </Field>
          )}
          {value.source_execution && (
            <p className="text-12 text-secondary">此缺陷由用例执行产生，沿用原用例进行回归。</p>
          )}
          <Field label="验证范围与原因">
            <textarea
              name="reason"
              required
              rows={3}
              maxLength={1000}
              className={fieldClass}
              placeholder="需要验证哪些操作、预期结果及影响范围"
            />
          </Field>
        </Modal>
      )}
      {verifying && (
        <Modal
          title="记录验证并关闭"
          submitLabel="确认验收并关闭"
          onClose={() => setVerifying(false)}
          onSubmit={async (form) => {
            const saved = await qualityApi.write<Defect>(
              `${base}defects/${value.id}/`,
              {
                expected_version: value.edit_version,
                status: "closed",
                verification_method: value.case_id ? "regression" : "manual",
                ...(value.case_id
                  ? { regression_execution_id: form.get("execution") }
                  : {
                      verification_note: `验证版本：${value.fixed_build}\n验证环境：${form.get("environment")}\n操作步骤：${form.get("steps")}\n预期结果：${form.get("expected")}\n实际结果：${form.get("actual")}\n证据：${form.get("evidence")}`,
                    }),
              },
              "patch"
            );
            await onChanged(saved);
            setVerifying(false);
          }}
        >
          <p className="text-12 text-secondary">
            修复版本：{value.fixed_build || "未填写"}。仅在实际验证通过后确认关闭。
          </p>
          {value.case_id ? (
            <Field label="修复后通过的执行记录">
              <select required name="execution" className={fieldClass} defaultValue="">
                <option value="">选择本次修复后通过的执行</option>
                {candidates?.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.plan_name} · {row.build} · {row.created_at}
                  </option>
                ))}
              </select>
              {candidates?.length === 0 && (
                <p className="mt-2 text-12 text-secondary">暂无符合条件的记录，请先在测试计划中执行关联用例。</p>
              )}
            </Field>
          ) : (
            <>
              {[
                ["environment", "验证环境"],
                ["steps", "操作步骤"],
                ["expected", "预期结果"],
                ["actual", "实际结果"],
                ["evidence", "证据 / Session / 附件说明"],
              ].map(([name, label]) => (
                <Field key={name} label={label}>
                  <textarea name={name} required rows={2} maxLength={600} className={fieldClass} />
                </Field>
              ))}
            </>
          )}
        </Modal>
      )}
    </section>
  );
}
