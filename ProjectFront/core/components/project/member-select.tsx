/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { Ban } from "lucide-react";
import { EUserProjectRoles } from "@plane/types";
// plane ui
import { Avatar, CustomSearchSelect } from "@plane/ui";
// helpers
import { getFileURL } from "@plane/utils";
// hooks
import { useMember } from "@/hooks/store/use-member";

type Props = {
  value: any;
  onChange: (val: string) => void;
  isDisabled?: boolean;
  projectId?: string;
  members?: { id: string; name: string }[];
};

export const MemberSelect = observer(function MemberSelect(props: Props) {
  const { value, onChange, isDisabled = false } = props;
  // router
  const { projectId: routeProjectId } = useParams();
  const projectId = props.projectId || routeProjectId;
  // store hooks
  const {
    project: { projectMemberIds, getProjectMemberDetails },
  } = useMember();

  if (props.members) {
    const scopedOptions = [
      { value: "none", query: "无", content: <span>无</span> },
      ...props.members.map((person) => ({ value: person.id, query: person.name, content: <span>{person.name}</span> })),
    ];
    return (
      <CustomSearchSelect
        value={value}
        label={<span>{props.members.find((person) => person.id === value)?.name || "无"}</span>}
        buttonClassName="!px-3 !py-2 bg-surface-1"
        options={scopedOptions}
        onChange={onChange}
        disabled={isDisabled}
      />
    );
  }
  const options = projectMemberIds
    ?.map((userId) => {
      const memberDetails = projectId ? getProjectMemberDetails(userId, projectId.toString()) : null;

      if (!memberDetails?.member || memberDetails.member.is_active === false) return;
      const isGuest = memberDetails.role === EUserProjectRoles.GUEST;
      if (isGuest) return;

      return {
        value: `${memberDetails?.member.id}`,
        query: `${memberDetails?.member.display_name}`,
        content: (
          <div className="flex items-center gap-2">
            <Avatar name={memberDetails?.member.display_name} src={getFileURL(memberDetails?.member.avatar_url)} />
            {memberDetails?.member.display_name}
          </div>
        ),
      };
    })
    .filter((option) => !!option) as
    | {
        value: string;
        query: string;
        content: React.ReactNode;
      }[]
    | undefined;
  const selectedOption = projectId ? getProjectMemberDetails(value, projectId.toString()) : null;

  return (
    <CustomSearchSelect
      value={value}
      label={
        <div className="flex h-3.5 items-center gap-2">
          {selectedOption && (
            <Avatar name={selectedOption.member?.display_name} src={getFileURL(selectedOption.member?.avatar_url)} />
          )}
          {selectedOption ? (
            selectedOption.member?.display_name
          ) : (
            <div className="flex items-center gap-2">
              <Ban className="h-3.5 w-3.5 rotate-90 text-placeholder" />
              <span className="text-13 text-placeholder">无</span>
            </div>
          )}
        </div>
      }
      buttonClassName="!px-3 !py-2 bg-surface-1"
      options={
        options && [
          ...options,
          {
            value: "none",
            query: "none",
            content: (
              <div className="flex items-center gap-2">
                <Ban className="h-3.5 w-3.5 rotate-90 text-placeholder" />
                <span className="py-0.5 text-13 text-placeholder">无</span>
              </div>
            ),
          },
        ]
      }
      maxHeight="md"
      onChange={onChange}
      disabled={isDisabled}
    />
  );
});
