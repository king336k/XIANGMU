import { renderNumericDateTime } from "@plane/utils";
import { Badge } from "./shared";
import { solutionFields } from "./solution-data";
import type { SolutionRevision } from "./solution-data";
import type { Context } from "./types";
export function SolutionContent({ value }: { value: Record<string, string> }) {
  return (
    <div className="space-y-5">
      {solutionFields
        .filter((field) => field.required)
        .map((field) => (
          <section key={field.key} className="space-y-2">
            <h4 className="text-13 font-medium text-secondary">{field.label}</h4>
            <p className="text-13 leading-7 break-words whitespace-pre-wrap">{value[field.key] || "未填写"}</p>
          </section>
        ))}
      {(value.risk || value.rollback || value.repository || value.commit_sha) && (
        <details className="border-t border-subtle pt-3">
          <summary className="cursor-pointer text-12 text-secondary">风险、回退与代码信息</summary>
          <div className="mt-3 space-y-3">
            {[
              ...solutionFields.filter((field) => !field.required),
              { key: "repository", label: "代码仓库" },
              { key: "commit_sha", label: "提交版本" },
            ]
              .filter((field) => value[field.key])
              .map((field) => (
                <div key={field.key}>
                  <h4 className="text-12 text-secondary">{field.label}</h4>
                  <p className="mt-1 text-13 break-words whitespace-pre-wrap">{value[field.key]}</p>
                </div>
              ))}
          </div>
        </details>
      )}
    </div>
  );
}
export function SolutionReviewResult({
  revision,
  members,
}: {
  revision: SolutionRevision;
  members: Context["members"];
}) {
  const approved = revision.reviews.filter((vote) => vote.decision === "approve").length;
  const rejected = revision.reviews.some((vote) => vote.decision === "reject");
  return (
    <section className="space-y-3 border-t border-subtle pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-13 font-medium">审核结果</h4>
        <Badge
          value={rejected ? "failed" : approved >= revision.required_count ? "passed" : "review"}
          label={rejected ? "已退回" : `已通过 ${approved}/${revision.required_count} 人`}
        />
      </div>
      <div className="space-y-2">
        {revision.reviewer_ids.map((id) => {
          const vote = revision.reviews.find((item) => item.created_by_id === id);
          const name = vote?.actor || members.find((member) => member.id === id)?.name || "审核人";
          return (
            <div key={id} className="rounded-md border border-subtle px-3 py-3 text-13">
              <div className="flex flex-wrap items-center gap-2">
                <span>{name}</span>
                <Badge
                  value={vote ? (vote.decision === "approve" ? "passed" : "failed") : "pending"}
                  label={vote ? (vote.decision === "approve" ? "通过" : "退回") : "待审核"}
                />
                {vote?.created_at && (
                  <span className="text-11 text-secondary">{renderNumericDateTime(vote.created_at)}</span>
                )}
              </div>
              {vote?.comment && <p className="mt-2 break-words whitespace-pre-wrap">{vote.comment}</p>}
            </div>
          );
        })}
      </div>
    </section>
  );
}
