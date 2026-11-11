import { useCollectionPagination } from "./use-collection-pagination";
// SPDX-License-Identifier: AGPL-3.0-only
import { can } from "./types";
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal, Paging } from "./shared";
import type { Context } from "./types";

type Revision = {
  id: string;
  version: number;
  snapshot: Record<string, string>;
  reviewer_ids: string[];
  required_count: number;
  reviews: { id: string; actor: string; decision: string; comment: string }[];
};
type Solution = {
  id: string;
  defect_id: string;
  title: string;
  status: string;
  edit_version: number;
  created_by_id: string;
  contributor_ids?: string[];
  revisions: Revision[];
  root_cause: string;
  steps: string;
  verification: string;
  risk: string;
  rollback: string;
  repository: string;
  commit_sha: string;
};
const fields = [
  { key: "root_cause", label: "根因分析", required: true },
  { key: "steps", label: "解决步骤", required: true },
  { key: "verification", label: "验证方法", required: true },
  { key: "risk", label: "影响与风险" },
  { key: "rollback", label: "回退方法" },
];
const names: Record<string, string> = { draft: "草稿", review: "待审核", approved: "已通过", rejected: "已退回" };

export function SolutionPanel({ base, defectId, context }: { base: string; defectId: string; context: Context }) {
  const pagination = useCollectionPagination(`${base}:solutions:${defectId}`);
  const { data, mutate } = useSWR(`${base}solutions/?defect_id=${defectId}&${pagination.query}`, (url: string) =>
    qualityApi.read<{ results: Solution[]; count: number }>(url)
  );
  const [editing, setEditing] = useState<Solution | null | undefined>(undefined);
  const [submitting, setSubmitting] = useState<Solution | null>(null);
  const [reviewing, setReviewing] = useState<Solution | null>(null);
  const [snapshot, setSnapshot] = useState<Revision | null>(null);
  const [error, setError] = useState("");
  const isAdministrator = context.is_administrator === true;
  const saved = async () => {
    await mutate();
  };
  return (
    <section className="space-y-3 border-t border-subtle pt-4">
      <div className="flex items-center justify-between">
        <h3 className="text-13 font-medium">技术方案与审核</h3>
        {can(context, "solution") && (
          <Button variant="neutral-primary" onClick={() => setEditing(null)}>
            新增方案
          </Button>
        )}
      </div>
      <p className="text-12 text-secondary">
        审核以提交时的方案版本为准；管理员可完成本人方案审核，其他作者须由审核人确认。审核通过后继续修复与回归。
      </p>
      {error && (
        <p role="alert" className="text-danger-primary">
          {error}
        </p>
      )}
      {!data?.results.length && <p className="text-12 text-secondary">尚无技术方案。</p>}
      {data?.results.map((solution) => (
        <article key={solution.id} className="space-y-2 rounded-md border border-subtle p-3">
          <div className="flex items-center justify-between gap-3">
            <h4 className="text-13 font-medium">{solution.title}</h4>
            <span className="text-11 text-secondary">
              {names[solution.status]} · 修订{solution.edit_version}
            </span>
          </div>
          <p className="line-clamp-3 text-12 whitespace-pre-wrap text-secondary">{solution.root_cause}</p>
          <div className="flex flex-wrap gap-2">
            {can(context, "solution") &&
              solution.status !== "review" &&
              (context.is_manager || context.user_id === solution.created_by_id) && (
                <Button variant="neutral-primary" onClick={() => setEditing(solution)}>
                  编辑方案
                </Button>
              )}
            {solution.status === "draft" &&
              can(context, "solution") &&
              (context.is_manager || context.user_id === solution.created_by_id) && (
                <Button onClick={() => setSubmitting(solution)}>送审</Button>
              )}
            {can(context, "review") &&
              solution.status === "review" &&
              solution.revisions[0]?.reviewer_ids.includes(context.user_id) &&
              (isAdministrator || solution.created_by_id !== context.user_id) && (
                <Button onClick={() => setReviewing(solution)}>提交审核意见</Button>
              )}
            {solution.revisions.map((revision) => (
              <Button key={revision.id} variant="neutral-primary" onClick={() => setSnapshot(revision)}>
                送审版本 v{revision.version}
              </Button>
            ))}
          </div>
        </article>
      ))}
      {editing !== undefined && (
        <Modal
          title={editing ? "编辑技术方案" : "新增技术方案"}
          onClose={() => setEditing(undefined)}
          onSubmit={async (form) => {
            await qualityApi.write(
              `${base}solutions/${editing ? `${editing.id}/` : ""}`,
              {
                defect_id: defectId,
                title: form.get("title"),
                ...Object.fromEntries(fields.map((f) => [f.key, form.get(f.key)])),
                repository: form.get("repository"),
                commit_sha: form.get("commit_sha"),
                ...(editing ? { expected_version: editing.edit_version } : {}),
              },
              editing ? "patch" : "post"
            );
            await saved();
          }}
        >
          <Field label="方案标题 *">
            <input name="title" required maxLength={255} defaultValue={editing?.title} className={fieldClass} />
          </Field>
          {fields.map((field) => (
            <Field key={field.key} label={`${field.label}${field.required ? " *" : ""}`}>
              <textarea
                name={field.key}
                required={field.required}
                rows={3}
                className={fieldClass}
                defaultValue={editing?.[field.key as keyof Solution] as string | undefined}
              />
            </Field>
          ))}
          <Field label="代码仓库">
            <input name="repository" maxLength={500} defaultValue={editing?.repository} className={fieldClass} />
          </Field>
          <Field label="提交版本">
            <input name="commit_sha" maxLength={120} defaultValue={editing?.commit_sha} className={fieldClass} />
          </Field>
        </Modal>
      )}
      {submitting && (
        <Modal
          title="提交方案审核"
          onClose={() => setSubmitting(null)}
          onSubmit={async (form) => {
            await qualityApi.write(`${base}solutions/${submitting.id}/submit/`, {
              expected_version: submitting.edit_version,
              reviewer_ids: form.getAll("reviewer_ids"),
              required_count: Number(form.get("required_count")),
            });
            await saved();
          }}
        >
          <fieldset className="space-y-2">
            <legend className="mb-2 text-13 font-medium">
              {isAdministrator ? "选择审核人（可选择本人）" : "选择审核人（不含作者）"}
            </legend>
            {context.members
              .filter(
                (m) =>
                  ((isAdministrator && m.id === context.user_id) ||
                    (m.id !== submitting.created_by_id &&
                      m.id !== context.user_id &&
                      !submitting.contributor_ids?.includes(m.id))) &&
                  (!context.business_roles_enabled ||
                    (m.business_roles || [m.business_role]).some(
                      (role) => typeof role === "string" && ["PLATFORM_ADMIN", "PROJECT_MANAGER"].includes(role)
                    ))
              )
              .map((m) => (
                <label key={m.id} className="flex items-center gap-3 text-13">
                  <input type="checkbox" name="reviewer_ids" value={m.id} />
                  {m.name}
                </label>
              ))}
          </fieldset>
          <Field label="需要通过人数 *">
            <input
              type="number"
              name="required_count"
              min={1}
              max={30}
              defaultValue={1}
              required
              className={fieldClass}
            />
          </Field>
        </Modal>
      )}
      {reviewing && (
        <Modal
          title="审核技术方案"
          onClose={() => setReviewing(null)}
          onSubmit={async (form) => {
            try {
              await qualityApi.write(`${base}solutions/${reviewing.id}/review/`, {
                revision_id: reviewing.revisions[0].id,
                decision: form.get("decision"),
                comment: form.get("comment"),
              });
              await saved();
            } catch (e) {
              setError(errorMessage(e));
              throw e;
            }
          }}
        >
          <div className="space-y-3">
            {fields.map((f) => (
              <div key={f.key}>
                <h4 className="text-12 font-medium">{f.label}</h4>
                <p className="text-13 whitespace-pre-wrap">{reviewing.revisions[0].snapshot[f.key] || "未填写"}</p>
              </div>
            ))}
          </div>
          <Field label="审核决定">
            <select name="decision" className={fieldClass}>
              <option value="approve">通过</option>
              <option value="reject">退回修改（须说明原因）</option>
            </select>
          </Field>
          <Field label="审核说明">
            <textarea name="comment" rows={3} className={fieldClass} />
          </Field>
        </Modal>
      )}
      {snapshot && (
        <Modal title={`送审版本 v${snapshot.version}`} onClose={() => setSnapshot(null)}>
          <h3 className="text-14 font-medium">{snapshot.snapshot.title}</h3>
          {fields.map((f) => (
            <div key={f.key}>
              <h4 className="text-12 font-medium">{f.label}</h4>
              <p className="text-13 whitespace-pre-wrap">{snapshot.snapshot[f.key] || "未填写"}</p>
            </div>
          ))}
          <p className="text-12 text-secondary">要求 {snapshot.required_count} 位审核人通过。</p>
          {snapshot.reviews.map((vote) => (
            <div key={vote.id} className="rounded-md border border-subtle p-3 text-12">
              {vote.actor || "成员"} · {vote.decision === "approve" ? "通过" : "退回"}
              <p>{vote.comment}</p>
            </div>
          ))}
        </Modal>
      )}
      {data && <Paging {...pagination.paging} count={data.count} />}
    </section>
  );
}
