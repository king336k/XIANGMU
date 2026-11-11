import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { Badge } from "@/components/quality/record-badge";
import { observer } from "mobx-react";
import { Clock } from "lucide-react";
// plane imports
import { Avatar, Row } from "@plane/ui";
import {
  cn,
  generateWorkItemLink,
  calculateTimeAgo,
  renderFormattedDate,
  renderFormattedTime,
  getFileURL,
} from "@plane/utils";
// hooks
import { useNotification } from "@/hooks/store/notifications/use-notification";
import { useWorkspace } from "@/hooks/store/use-workspace";
// local imports
import { NotificationContent } from "./content";
import { NotificationOption } from "./options";

type TNotificationItem = {
  workspaceSlug: string;
  notificationId: string;
};

export const NotificationItem = observer(function NotificationItem(props: TNotificationItem) {
  const { workspaceSlug, notificationId } = props;
  // hooks
  const { asJson: notification, markNotificationAsRead } = useNotification(notificationId);
  const { getWorkspaceBySlug } = useWorkspace();
  // states
  const [isSnoozeStateModalOpen, setIsSnoozeStateModalOpen] = useState(false);
  const [customSnoozeModal, setCustomSnoozeModal] = useState(false);

  // derived values
  const projectId = notification?.project || undefined;
  const issueId = notification?.data?.issue?.id || undefined;
  const workspace = getWorkspaceBySlug(workspaceSlug);

  const notificationTriggeredBy = notification.triggered_by_details || undefined;

  const nativeHref = notification.is_inbox_issue
    ? `/${workspaceSlug}/projects/${projectId}/intake/${issueId}/`
    : generateWorkItemLink({
        workspaceSlug,
        projectId,
        issueId,
        projectIdentifier: notification.data?.issue?.identifier,
        sequenceId: notification.data?.issue?.sequence_id,
      });
  const markRead = () => {
    if (!notification.read_at) void markNotificationAsRead(workspaceSlug).catch(() => undefined);
  };

  const currentRecord = notification?.data?.current_record;
  const recordKindNames: Record<string, string> = {
    defect: "缺陷",
    plan: "测试计划",
    requirement: "需求",
    task: "任务",
  };
  const currentState = currentRecord ? (
    <Badge
      variant="plain"
      value={currentRecord.status}
      label={`${recordKindNames[currentRecord.kind] ? `${recordKindNames[currentRecord.kind]} · ` : ""}${currentRecord.label}`}
    />
  ) : null;
  const quality = notification?.data?.quality;
  if (
    notification?.entity_name === "quality" &&
    quality &&
    projectId &&
    quality.url.startsWith(`/${workspaceSlug}/projects/${projectId}/`)
  ) {
    return (
      <div
        className={`flex items-center justify-between gap-3 border-b border-subtle p-4 ${notification.read_at ? "" : "bg-accent-primary/5"}`}
      >
        <Link
          className="min-w-0 flex-1 text-13 text-primary hover:text-accent-primary"
          to={quality.url}
          onClick={() => {
            if (!notification.read_at) void markNotificationAsRead(workspaceSlug).catch(() => undefined);
          }}
        >
          <p className="text-13 leading-5 font-medium break-words">{quality.title}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-11 text-tertiary">
            <span className={notification.read_at ? "text-tertiary" : "font-medium text-accent-primary"}>
              {notification.read_at ? "已读" : "未读"}
            </span>
            <span>{notification.created_at && calculateTimeAgo(notification.created_at)}</span>
            {currentState}
          </div>
        </Link>
        <NotificationOption
          workspaceSlug={workspaceSlug}
          notificationId={notificationId}
          isSnoozeStateModalOpen={isSnoozeStateModalOpen}
          setIsSnoozeStateModalOpen={setIsSnoozeStateModalOpen}
          customSnoozeModal={customSnoozeModal}
          setCustomSnoozeModal={setCustomSnoozeModal}
        />
      </div>
    );
  }
  if (!workspaceSlug || !notificationId || !notification?.id || !issueId || !workspace?.id || !projectId) return <></>;

  return (
    <Row
      className={cn(
        "group relative flex cursor-pointer items-center gap-2 border-b border-subtle py-4 transition-all",
        {
          "bg-accent-primary/5": notification.read_at === null,
        }
      )}
    >
      {notification.read_at === null && (
        <div className="absolute top-[50%] left-2 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-accent-primary" />
      )}

      <Link to={nativeHref} onClick={markRead} className="relative flex min-w-0 flex-1 gap-2">
        <div className="relative flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-layer-1">
          {notificationTriggeredBy && (
            <Avatar
              name={notificationTriggeredBy.display_name || notificationTriggeredBy?.first_name}
              src={getFileURL(notificationTriggeredBy.avatar_url)}
              size={42}
              shape="circle"
              className="bg-layer-1 text-body-sm-medium"
            />
          )}
        </div>

        <div className="min-w-0 flex-1 space-y-1">
          <div className="text-13 leading-5 font-medium break-words text-primary">
            <NotificationContent
              notification={notification}
              workspaceId={workspace.id}
              workspaceSlug={workspaceSlug}
              projectId={projectId}
            />
          </div>
          <p className="text-12 break-words text-secondary">
            {notification?.data?.issue?.identifier}-{notification?.data?.issue?.sequence_id}{" "}
            {notification?.data?.issue?.name}
          </p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-11 text-tertiary">
            <span className={notification.read_at ? "text-tertiary" : "font-medium text-accent-primary"}>
              {notification.read_at ? "已读" : "未读"}
            </span>
            {notification.snoozed_till ? (
              <span className="inline-flex items-center gap-1">
                <Clock className="size-3" />
                截至 {renderFormattedDate(notification.snoozed_till)} {renderFormattedTime(notification.snoozed_till)}
              </span>
            ) : (
              <span>{notification.created_at && calculateTimeAgo(notification.created_at)}</span>
            )}
            {currentState}
          </div>
        </div>
      </Link>
      <NotificationOption
        workspaceSlug={workspaceSlug}
        notificationId={notification?.id}
        isSnoozeStateModalOpen={isSnoozeStateModalOpen}
        setIsSnoozeStateModalOpen={setIsSnoozeStateModalOpen}
        customSnoozeModal={customSnoozeModal}
        setCustomSnoozeModal={setCustomSnoozeModal}
      />
    </Row>
  );
});
