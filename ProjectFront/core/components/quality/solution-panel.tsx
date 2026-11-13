// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal, Paging } from "./shared";
import { useCollectionPagination } from "./use-collection-pagination";
import { SolutionCard } from "./solution-card";
import { SolutionContent, SolutionReviewResult } from "./solution-content";
import { currentSolutionRevision, solutionFields } from "./solution-data";
import type { Solution, SolutionRevision } from "./solution-data";
import type { Context } from "./types";
export function SolutionPanel({ base, defectId, context }: { base: string; defectId: string; context: Context }) {
  const pagination = useCollectionPagination(`${base}:solutions:${defectId}`);
  const { data, error, mutate } = useSWR(`${base}solutions/?defect_id=${defectId}&${pagination.query}`, (url: string) =>
    qualityApi.read<{ results: Solution[]; count: number; can_create: boolean }>(url)
  );
  const [editing, setEditing] = useState<Solution | null | undefined>(undefined);
  const [submitting, setSubmitting] = useState<Solution | null>(null);
  const [reviewing, setReviewing] = useState<Solution | null>(null);
  const [snapshot, setSnapshot] = useState<SolutionRevision | null>(null);
  const [reviewDecision, setReviewDecision] = useState("");
  const saved = async () => {
    await mutate();
  };
  const administrator =
    context.is_administrator === true ||
    (context.is_administrator === undefined && (context.business_roles || []).includes("PLATFORM_ADMIN"));
  const ownSolution = (solution: Solution) =>
    administrator || Boolean(context.user_id && context.user_id === solution.created_by_id);
  const rejectAuthor = () => setToast({ type: TOAST_TYPE.INFO, title: "无法操作", message: "仅方案创建人可操作" });

  const candidates = submitting
    ? context.members.filter((member) => {
        const contributor =
          member.id === submitting.created_by_id ||
          member.id === context.user_id ||
          submitting.contributor_ids?.includes(member.id);
        const manager =
          member.is_administrator ||
          !context.business_roles_enabled ||
          (member.business_roles || [member.business_role]).some(
            (role) => role === "PLATFORM_ADMIN" || role === "PROJECT_MANAGER"
          );
        return manager && (!contributor || (administrator && member.id === context.user_id));
      })
    : [];
  const reviewRevision = reviewing ? currentSolutionRevision(reviewing) : null;
  return (
    <section className="space-y-4" aria-label="处理方案与审核">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-14 font-semibold">处理方案</h3>
        {data?.can_create && (
          <Button type="button" variant="neutral-primary" size="sm" onClick={() => setEditing(null)}>
            新增方案
          </Button>
        )}
      </div>
      {error ? (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      ) : !data ? (
        <p role="status" className="text-13 text-secondary">
          正在加载方案…
        </p>
      ) : !data.results.length ? (
        <p className="text-13 text-secondary">暂无处理方案。</p>
      ) : (
        data.results.map((solution) => (
          <SolutionCard
            key={solution.id}
            solution={solution}
            context={context}
            onEdit={() => {
              if (!ownSolution(solution)) {
                rejectAuthor();
                return;
              }
              if (solution.can_edit) setEditing(solution);
            }}
            onSubmit={() => {
              if (!ownSolution(solution)) {
                rejectAuthor();
                return;
              }
              if (solution.can_submit) setSubmitting(solution);
            }}
            onReview={() => {
              setReviewDecision("");
              setReviewing(solution);
            }}
            onSnapshot={setSnapshot}
          />
        ))
      )}
      {data && (data.count > pagination.perPage || pagination.page > 1) && (
        <Paging {...pagination.paging} count={data.count} />
      )}
      {editing !== undefined && (
        <Modal
          title={editing ? "编辑方案" : "新增方案"}
          submitLabel={editing?.status === "approved" ? "保存并选择审核人" : "保存草稿"}
          onClose={() => setEditing(undefined)}
          onSubmit={async (form) => {
            if (editing && !ownSolution(editing)) throw Error("仅方案创建人可操作");
            const result = await qualityApi.write<Solution>(
              `${base}solutions/${editing ? `${editing.id}/` : ""}`,
              {
                defect_id: defectId,
                title: form.get("title"),
                ...Object.fromEntries(solutionFields.map((f) => [f.key, form.get(f.key) || ""])),
                repository: form.get("repository") || "",
                commit_sha: form.get("commit_sha") || "",
                ...(editing ? { expected_version: editing.edit_version } : {}),
              },
              editing ? "patch" : "post"
            );
            await saved();
            if (editing?.status === "approved") setSubmitting(result);
          }}
        >
          {editing?.status === "approved" && <p className="text-12 text-secondary">修改后重新审核，已通过版本保留。</p>}
          <Field label="方案标题">
            <input required name="title" maxLength={255} className={fieldClass} defaultValue={editing?.title} />
          </Field>
          {solutionFields
            .filter((f) => f.required)
            .map((field) => (
              <Field key={field.key} label={field.label}>
                <textarea
                  required
                  name={field.key}
                  maxLength={20000}
                  rows={3}
                  className={fieldClass}
                  defaultValue={editing?.[field.key]}
                />
              </Field>
            ))}
          <details>
            <summary className="cursor-pointer text-12 text-secondary">风险、回退与代码信息（选填）</summary>
            <div className="mt-3 space-y-3">
              {solutionFields
                .filter((f) => !f.required)
                .map((field) => (
                  <Field key={field.key} label={field.label}>
                    <textarea
                      name={field.key}
                      maxLength={10000}
                      rows={2}
                      className={fieldClass}
                      defaultValue={editing?.[field.key]}
                    />
                  </Field>
                ))}
              <Field label="代码仓库">
                <input name="repository" maxLength={500} className={fieldClass} defaultValue={editing?.repository} />
              </Field>
              <Field label="提交版本">
                <input name="commit_sha" maxLength={120} className={fieldClass} defaultValue={editing?.commit_sha} />
              </Field>
            </div>
          </details>
        </Modal>
      )}
      {submitting && (
        <Modal
          title="提交方案审核"
          submitLabel="提交审核"
          onClose={() => setSubmitting(null)}
          onSubmit={async (form) => {
            if (!ownSolution(submitting)) throw Error("仅方案创建人可操作");
            const ids = form.getAll("reviewer_ids").map(String),
              count = Number(form.get("required_count"));
            if (!ids.length) throw Error("请选择审核人。");
            if (count > ids.length) throw Error("通过人数不能超过所选审核人数。");
            await qualityApi.write(`${base}solutions/${submitting.id}/submit/`, {
              expected_version: submitting.edit_version,
              reviewer_ids: ids,
              required_count: count,
            });
            await saved();
          }}
        >
          <p className="text-13 font-medium">{submitting.title}</p>
          <fieldset className="space-y-2">
            <legend className="mb-2 text-13 font-medium">审核人</legend>
            {candidates.map((member) => (
              <label key={member.id} className="flex items-center gap-2 text-13">
                <input type="checkbox" name="reviewer_ids" value={member.id} />
                {member.name}
              </label>
            ))}
            {!candidates.length && <p className="text-12 text-secondary">暂无可选审核人，请先分配项目经理或管理员。</p>}
          </fieldset>
          <Field label="需要通过人数">
            <input
              required
              type="number"
              name="required_count"
              min={1}
              max={candidates.length || 1}
              defaultValue={1}
              className={fieldClass}
            />
          </Field>
        </Modal>
      )}
      {reviewing && reviewRevision && (
        <Modal
          title={`审核方案 · v${reviewRevision.version}`}
          submitLabel="提交审核意见"
          onClose={() => setReviewing(null)}
          onSubmit={async (form) => {
            await qualityApi.write(`${base}solutions/${reviewing.id}/review/`, {
              revision_id: reviewRevision.id,
              decision: form.get("decision"),
              comment: form.get("comment") || "",
            });
            await saved();
          }}
        >
          <h3 className="text-14 font-semibold">{reviewRevision.snapshot.title || reviewing.title}</h3>
          <SolutionContent value={reviewRevision.snapshot} />
          <Field label="审核决定">
            <select
              aria-label="审核决定"
              required
              name="decision"
              value={reviewDecision}
              className={fieldClass}
              onChange={(event) => setReviewDecision(event.target.value)}
            >
              <option value="" disabled>
                选择审核决定
              </option>
              <option value="approve">通过</option>
              <option value="reject">退回修改</option>
            </select>
          </Field>
          <Field label={reviewDecision === "reject" ? "退回原因" : "审核意见（选填）"}>
            <textarea
              name="comment"
              required={reviewDecision === "reject"}
              maxLength={4000}
              rows={3}
              className={fieldClass}
            />
          </Field>
        </Modal>
      )}
      {snapshot && (
        <Modal title={`送审版本 v${snapshot.version}`} onClose={() => setSnapshot(null)}>
          <h3 className="text-14 font-semibold">{snapshot.snapshot.title}</h3>
          <SolutionContent value={snapshot.snapshot} />
          <SolutionReviewResult revision={snapshot} members={context.members} />
        </Modal>
      )}
    </section>
  );
}
