// SPDX-License-Identifier: AGPL-3.0-only
import useSWR from "swr";
import { useParams } from "react-router";
import { qualityApi } from "./api";

export type WorkItemKinds = {
  total: number;
  requirements: number;
  tasks: number;
  requirement_sequences: number[];
  requirement_numbers: Record<string, number>;
};
export function useWorkItemKinds(projectId?: string) {
  const { workspaceSlug } = useParams();
  return useSWR(
    workspaceSlug && projectId
      ? `/api/workspaces/${workspaceSlug}/projects/${projectId}/quality/work-item-kinds/`
      : null,
    (url: string) => qualityApi.read<WorkItemKinds>(url)
  );
}

export function WorkItemKind({ projectId, sequence }: { projectId: string; sequence?: number | string | null }) {
  const { data } = useWorkItemKinds(projectId);
  if (!data || sequence == null) return null;
  const requirement = data.requirement_sequences.includes(Number(sequence));
  return (
    <span
      title={requirement ? "正式需求，内容与审核在需求中维护" : "研发任务，在任务中安排与跟踪"}
      className={`font-normal inline-flex shrink-0 items-center rounded border border-subtle px-1.5 py-0.5 text-10 leading-none ${requirement ? "bg-accent-primary/5 text-accent-primary" : "bg-layer-1 text-secondary"}`}
    >
      {requirement ? "需求" : "任务"}
    </span>
  );
}
