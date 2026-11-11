import { recordDutyLabels, compactRecordDuty } from "./duty-summary";
import type { Context } from "./types";
export function RecordResponsibility({
  context,
  assigneeId,
  authorId,
  collaboratorIds,
  kind,
}: {
  context: Context;
  assigneeId?: string | null;
  authorId?: string | null;
  collaboratorIds?: string[];
  kind: string;
}) {
  const labels = recordDutyLabels({
    userId: context.user_id,
    assigneeId,
    authorId,
    collaboratorIds,
    canArrange: context.is_manager,
    kind,
  });
  const label = compactRecordDuty(labels);
  return label ? (
    <span className="inline-flex rounded bg-layer-1 px-2 py-0.5 text-11 text-secondary" title={labels.join(" · ")}>
      {label}
    </span>
  ) : null;
}
