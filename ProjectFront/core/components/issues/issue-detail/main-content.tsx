import { useNativeWorkAccess } from "@/hooks/use-native-work-access";
import { recordDutyLabels, compactRecordDuty } from "@/components/quality/duty-summary";
// oxlint-disable no-shadow
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { observer } from "mobx-react";
// plane imports
import type { EditorRefApi } from "@plane/editor";
import type { TNameDescriptionLoader } from "@plane/types";
import { EFileAssetType, EIssueServiceType } from "@plane/types";
// components
import { DescriptionVersionsRoot } from "@/components/core/description-versions";
import { DescriptionInput } from "@/components/editor/rich-text/description-input";
import { IssueTypeSwitcher } from "@/components/issues/issue-type-switcher";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useMember } from "@/hooks/store/use-member";
import { useUser } from "@/hooks/store/user";
import useReloadConfirmations from "@/hooks/use-reload-confirmation";
// services
import { WorkItemVersionService } from "@/services/issue";
// local imports
import { IssueDetailWidgets } from "../issue-detail-widgets";
import { NameDescriptionUpdateStatus } from "../issue-update-status";
import { IssueTitleInput } from "../title-input";
import { IssueActivity } from "./issue-activity";
import { IssueParentDetail } from "./parent";
import { IssueReaction } from "./reactions";
import type { TIssueOperations } from "./root";
// services init
const workItemVersionService = new WorkItemVersionService();

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  issueOperations: TIssueOperations;
  isEditable: boolean;
  isArchived: boolean;
  propertiesPanel: ReactNode;
};

export const IssueMainContent = observer(function IssueMainContent(props: Props) {
  const { workspaceSlug, projectId, issueId, issueOperations, isEditable, isArchived, propertiesPanel } = props;
  // refs
  const editorRef = useRef<EditorRefApi>(null);
  // states
  const [isSubmitting, setIsSubmitting] = useState<TNameDescriptionLoader>("saved");
  // hooks
  const { data: currentUser } = useUser();
  const { canArrangeWork } = useNativeWorkAccess();
  const { getUserDetails } = useMember();
  const {
    issue: { getIssueById },
    peekIssue,
  } = useIssueDetail();
  const { setShowAlert } = useReloadConfirmations(isSubmitting === "submitting");
  // derived values
  const issue = issueId ? getIssueById(issueId) : undefined;

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    if (isSubmitting === "submitted") {
      setShowAlert(false);
      timer = setTimeout(() => setIsSubmitting("saved"), 2000);
    } else if (isSubmitting === "submitting") setShowAlert(true);
    return () => clearTimeout(timer);
  }, [isSubmitting, setShowAlert, setIsSubmitting]);

  if (!issue || !issue.project_id) return <></>;

  const isPeekModeActive = Boolean(peekIssue);

  return (
    <div className="work-item-detail-grid">
      <article className="work-item-detail-content space-y-4">
        <div className="space-y-3">
          {issue.parent_id && (
            <IssueParentDetail
              workspaceSlug={workspaceSlug}
              projectId={projectId}
              issueId={issueId}
              issue={issue}
              issueOperations={issueOperations}
            />
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <IssueTypeSwitcher issueId={issueId} disabled={isArchived || !isEditable} />
              {currentUser && (
                <span className="text-11 text-secondary">
                  {compactRecordDuty(
                    recordDutyLabels({
                      userId: currentUser.id,
                      assigneeId: issue.assignee_ids?.includes(currentUser.id) ? currentUser.id : undefined,
                      authorId: issue.created_by,
                      canArrange: canArrangeWork(projectId),
                    })
                  )}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3">
              <NameDescriptionUpdateStatus isSubmitting={isSubmitting} />
            </div>
          </div>

          <IssueTitleInput
            workspaceSlug={workspaceSlug}
            projectId={issue.project_id}
            issueId={issue.id}
            isSubmitting={isSubmitting}
            setIsSubmitting={(value) => setIsSubmitting(value)}
            issueOperations={issueOperations}
            disabled={isArchived || !isEditable}
            value={issue.name}
            containerClassName="-ml-3"
          />

          <DescriptionInput
            issueSequenceId={issue.sequence_id}
            containerClassName="-ml-6 border-none p-0! pl-6!"
            disabled={isArchived || !isEditable}
            editorRef={editorRef}
            entityId={issue.id}
            fileAssetType={EFileAssetType.ISSUE_DESCRIPTION}
            initialValue={issue.description_html}
            key={issue.id}
            onSubmit={async (value, isMigrationUpdate) => {
              if (!issue.id || !issue.project_id) return;
              await issueOperations.update(workspaceSlug, issue.project_id, issue.id, {
                description_html: value.description_html,
                ...(isMigrationUpdate ? { skip_activity: "true" } : {}),
              });
            }}
            projectId={issue.project_id}
            setIsSubmitting={(value) => setIsSubmitting(value)}
            workspaceSlug={workspaceSlug}
          />

          <div className="flex flex-wrap items-center gap-3">
            {currentUser && (
              <IssueReaction
                className="flex-shrink-0"
                workspaceSlug={workspaceSlug}
                projectId={projectId}
                issueId={issueId}
                currentUser={currentUser}
                disabled={isArchived}
              />
            )}
            {isEditable && (
              <DescriptionVersionsRoot
                className="flex-shrink-0"
                entityInformation={{
                  createdAt: issue.created_at ? new Date(issue.created_at) : new Date(),
                  createdByDisplayName: getUserDetails(issue.created_by ?? "")?.display_name ?? "",
                  id: issueId,
                  isRestoreDisabled: !isEditable || isArchived,
                }}
                fetchHandlers={{
                  listDescriptionVersions: (issueId) =>
                    workItemVersionService.listDescriptionVersions(workspaceSlug, projectId, issueId),
                  retrieveDescriptionVersion: (issueId, versionId) =>
                    workItemVersionService.retrieveDescriptionVersion(workspaceSlug, projectId, issueId, versionId),
                }}
                handleRestore={(descriptionHTML) => editorRef.current?.setEditorValue(descriptionHTML, true)}
                projectId={projectId}
                workspaceSlug={workspaceSlug}
              />
            )}
          </div>
        </div>

        <IssueDetailWidgets
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          issueId={issueId}
          disabled={!isEditable || isArchived}
          renderWidgetModals={!isPeekModeActive}
          issueServiceType={EIssueServiceType.ISSUES}
        />
      </article>
      <aside className="work-item-detail-properties" aria-label="工作项属性">
        {propertiesPanel}
      </aside>
      <div className="work-item-detail-activity">
        <IssueActivity workspaceSlug={workspaceSlug} projectId={projectId} issueId={issueId} disabled={isArchived} />
      </div>
    </div>
  );
});
