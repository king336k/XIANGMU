import { Button } from "@plane/ui";
import { renderNumericDateTime } from "@plane/utils";
import { Badge } from "./shared";
import { SolutionContent, SolutionReviewResult } from "./solution-content";
import { currentSolutionRevision, solutionStatus, solutionTone } from "./solution-data";
import type { Solution, SolutionRevision } from "./solution-data";
import type { Context } from "./types";
export function SolutionCard({
  solution,
  context,
  onEdit,
  onSubmit,
  onReview,
  onSnapshot,
}: {
  solution: Solution;
  context: Context;
  onEdit: () => void;
  onSubmit: () => void;
  onReview: () => void;
  onSnapshot: (revision: SolutionRevision) => void;
}) {
  const current = currentSolutionRevision(solution);
  const version = solution.status === "draft" ? "草稿" : `v${current?.version || solution.submitted_version || "—"}`;
  const fields = {
    title: solution.title,
    root_cause: solution.root_cause,
    steps: solution.steps,
    verification: solution.verification,
    risk: solution.risk,
    rollback: solution.rollback,
    repository: solution.repository,
    commit_sha: solution.commit_sha,
  };
  return (
    <article className="space-y-5 rounded-md border border-subtle p-4 sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-15 font-semibold break-words">{solution.title}</h3>
            <Badge
              value={solutionTone[solution.status] || "neutral"}
              label={solutionStatus[solution.status] || solution.status}
            />
            <span className="text-12 text-secondary">{version}</span>
          </div>
          <p className="text-11 text-secondary">
            {solution.created_by_name ||
              context.members.find((m) => m.id === solution.created_by_id)?.name ||
              "方案作者"}
            {solution.created_at ? ` · ${renderNumericDateTime(solution.created_at)}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {solution.can_edit && (
            <Button type="button" size="sm" variant="neutral-primary" onClick={onEdit}>
              {solution.status === "approved" ? "修改并重新送审" : "编辑方案"}
            </Button>
          )}
          {solution.can_submit && (
            <Button type="button" size="sm" onClick={onSubmit}>
              提交审核
            </Button>
          )}
          {solution.can_review && (
            <Button type="button" size="sm" onClick={onReview}>
              审核方案
            </Button>
          )}
        </div>
      </header>
      <SolutionContent value={solution.status === "review" && current ? current.snapshot : fields} />
      {current && solution.status !== "draft" && <SolutionReviewResult revision={current} members={context.members} />}
      {!!solution.revisions.length && (
        <details className="border-t border-subtle pt-3">
          <summary className="cursor-pointer text-12 text-secondary">
            审核记录与历史版本（{solution.revisions.length}）
          </summary>
          <div className="mt-3 divide-y divide-subtle">
            {solution.revisions.map((revision) => (
              <div key={revision.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-12">
                <span>
                  送审版本 v{revision.version}
                  <span className="ml-3 text-secondary">
                    {revision.created_by_name}
                    {revision.created_at ? ` · ${renderNumericDateTime(revision.created_at)}` : ""}
                  </span>
                </span>
                <Button type="button" variant="neutral-primary" size="sm" onClick={() => onSnapshot(revision)}>
                  查看版本
                </Button>
              </div>
            ))}
          </div>
        </details>
      )}
    </article>
  );
}
