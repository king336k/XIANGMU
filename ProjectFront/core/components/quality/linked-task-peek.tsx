// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef } from "react";
import { observer } from "mobx-react";
import { IssuePeekOverview } from "@/components/issues/peek-overview";
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useResolvedProjectParams } from "@/hooks/use-resolved-project-params";
export const LinkedTaskPeek = observer(function LinkedTaskPeek({ id, onClosed }: { id: string; onClosed: () => void }) {
  const { workspaceSlug, projectId } = useResolvedProjectParams();
  const { peekIssue, setPeekIssue } = useIssueDetail();
  const wasVisible = useRef(false);
  const visible = peekIssue?.issueId === id;
  useEffect(() => {
    if (!workspaceSlug || !projectId) return;
    setPeekIssue({ workspaceSlug, projectId, issueId: id });
    return () => setPeekIssue(undefined);
  }, [workspaceSlug, projectId, id, setPeekIssue]);
  useEffect(() => {
    if (visible) wasVisible.current = true;
    else if (wasVisible.current) onClosed();
  }, [visible, onClosed]);
  return visible ? <IssuePeekOverview /> : null;
});
