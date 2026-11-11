import useSWR from "swr";
import { useParams } from "next/navigation";
import { useCycle } from "@/hooks/store/use-cycle";
import { useModule } from "@/hooks/store/use-module";
export function issueGroupLookupKinds(group?: string | null, subgroup?: string | null) {
  return [...new Set([group, subgroup].filter((value) => value === "cycle" || value === "module"))];
}
export function useIssueGroupLookups(group?: string | null, subgroup?: string | null) {
  const { workspaceSlug, projectId } = useParams();
  const { fetchAllCycles } = useCycle();
  const { fetchModules } = useModule();
  const kinds = issueGroupLookupKinds(group, subgroup).join(",");
  return useSWR(
    workspaceSlug && projectId && kinds ? `group-options:${workspaceSlug}:${projectId}:${kinds}` : null,
    () =>
      Promise.all(
        kinds
          .split(",")
          .map((kind) =>
            kind === "cycle"
              ? fetchAllCycles(String(workspaceSlug), String(projectId))
              : fetchModules(String(workspaceSlug), String(projectId))
          )
      ),
    { revalidateOnFocus: false }
  );
}
