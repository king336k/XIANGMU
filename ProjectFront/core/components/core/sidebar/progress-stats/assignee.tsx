/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Avatar } from "@plane/ui";
import { getFileURL } from "@plane/utils";
// assets
import emptyMembers from "@/app/assets/empty-state/empty_members.svg?url";
import userImage from "@/app/assets/user.png?url";
// components
import { SingleProgressStats } from "@/components/core/sidebar/single-progress-stats";

export type TAssigneeData = {
  id: string | undefined;
  title: string | undefined;
  avatar_url: string | undefined;
  completed: number;
  total: number;
}[];

type TAssigneeStatComponent = {
  selectedAssigneeIds: string[];
  handleAssigneeFiltersUpdate: (assigneeId: string | undefined) => void;
  distribution: TAssigneeData;
  isEditable?: boolean;
  canView?: boolean;
  unit?: string;
  onOpenAssignee?: (id: string, name: string) => void;
};

export const AssigneeStatComponent = observer(function AssigneeStatComponent(props: TAssigneeStatComponent) {
  const {
    distribution,
    isEditable,
    canView = true,
    unit,
    onOpenAssignee,
    selectedAssigneeIds,
    handleAssigneeFiltersUpdate,
  } = props;
  const { t } = useTranslation();
  return (
    <div>
      {distribution && distribution.length > 0 ? (
        distribution.map((assignee) => {
          if (assignee?.id)
            return (
              <SingleProgressStats
                key={assignee?.id}
                title={
                  <div className="flex min-w-0 items-center gap-2">
                    <Avatar name={assignee?.title ?? undefined} src={getFileURL(assignee?.avatar_url ?? "")} />
                    <span className="truncate" title={assignee?.title}>
                      {assignee?.title ?? ""}
                    </span>
                  </div>
                }
                unit={unit}
                completed={assignee?.completed ?? 0}
                total={assignee?.total ?? 0}
                {...(canView &&
                  (onOpenAssignee || isEditable) && {
                    onClick: () =>
                      onOpenAssignee
                        ? onOpenAssignee?.(assignee.id || "unassigned", assignee.title || "未指派")
                        : handleAssigneeFiltersUpdate(assignee.id),
                    selected: assignee.id ? selectedAssigneeIds.includes(assignee.id) : false,
                  })}
              />
            );
          else
            return (
              <SingleProgressStats
                key="unassigned"
                onClick={
                  canView && onOpenAssignee ? () => onOpenAssignee?.(assignee.id || "unassigned", "未指派") : undefined
                }
                title={
                  <div className="flex items-center gap-2">
                    <div className="h-4 w-4 rounded-full border-2 border-subtle bg-layer-1">
                      <img src={userImage} className="h-full w-full rounded-full object-cover" alt="成员" />
                    </div>
                    <span>{t("no_assignee")}</span>
                  </div>
                }
                unit={unit}
                completed={assignee?.completed ?? 0}
                total={assignee?.total ?? 0}
              />
            );
        })
      ) : (
        <div className="flex h-full flex-col items-center justify-center gap-2">
          <div className="flex h-20 w-20 items-center justify-center rounded-full bg-layer-1">
            <img src={emptyMembers} className="h-12 w-12 object-contain" alt="暂无成员" />
          </div>
          <h6 className="text-14 text-tertiary">{t("no_assignee")}</h6>
        </div>
      )}
    </div>
  );
});
