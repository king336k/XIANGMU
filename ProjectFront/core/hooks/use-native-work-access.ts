import { useCallback } from "react";
import useSWR from "swr";
import { qualityApi } from "@/components/quality/api";
import { nativeWorkAllowed } from "@/components/quality/native-work-access";
import type { NativeWorkRules } from "@/components/quality/native-work-access";
import { useIssues } from "@/hooks/store/use-issues";
import { useUser } from "@/hooks/store/user";
export function useNativeWorkAccess() {
  const { data: user } = useUser();
  const { issueMap } = useIssues();
  const { data } = useSWR(user ? "/api/quality-auth/work-access/" : null, (url: string) =>
    qualityApi.read<{ projects: NativeWorkRules }>(url)
  );
  const canArrangeWork = useCallback(
    (projectId: string | undefined) => nativeWorkAllowed(data?.projects, projectId, "arrange"),
    [data]
  );
  const canEditWork = useCallback(
    (projectId: string | undefined, issueId?: string) =>
      nativeWorkAllowed(
        data?.projects,
        projectId,
        "edit",
        user?.id,
        issueId ? issueMap[issueId]?.assignee_ids : undefined
      ),
    [data, user?.id, issueMap]
  );
  return { canArrangeWork, canEditWork };
}
