/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import Link from "next/link";
import { Controller, useForm } from "react-hook-form";
import { CircleMinus } from "lucide-react";
import { Disclosure } from "@headlessui/react";
// plane imports
import { ROLE, ROLE_DETAILS, EUserPermissions, MEMBER_TRACKER_ELEMENTS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { EUserProjectRoles, IUser, IWorkspaceMember, TProjectMembership } from "@plane/types";
import { Avatar, CustomMenu, CustomSelect } from "@plane/ui";
import { getFileURL } from "@plane/utils";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { useUser, useUserPermissions } from "@/hooks/store/user";

export interface RowData extends Pick<TProjectMembership, "original_role"> {
  is_administrator?: boolean;
  member: IWorkspaceMember & { is_administrator?: boolean };
}

type NameProps = {
  rowData: RowData;
  workspaceSlug: string;
  isAdmin: boolean;
  currentUser: IUser | undefined;
  setRemoveMemberModal: (rowData: RowData) => void;
};

type AccountTypeProps = {
  rowData: RowData;
  currentProjectRole: EUserPermissions | undefined;
  workspaceSlug: string;
  projectId: string;
};

export function NameColumn(props: NameProps) {
  const { rowData, workspaceSlug, isAdmin, currentUser, setRemoveMemberModal } = props;
  // derived values
  const { avatar_url, display_name, first_name, id, username } = rowData.member;
  const accountName = username || display_name || first_name || "未命名账号";

  return (
    <Disclosure>
      {() => (
        <div className="group relative">
          <div className="flex w-72 items-center gap-2">
            <div className="flex flex-1 items-center gap-x-2 gap-y-2">
              {avatar_url && avatar_url.trim() !== "" ? (
                <Link href={`/${workspaceSlug}/profile/${id}`}>
                  <Avatar src={getFileURL(avatar_url)} name={accountName} size={24} />
                </Link>
              ) : (
                <Link href={`/${workspaceSlug}/profile/${id}`}>
                  <span className="relative flex size-6 items-center justify-center rounded-full bg-layer-3 text-11 text-on-color capitalize">
                    {accountName[0]}
                  </span>
                </Link>
              )}
              {accountName}
              {rowData.member.is_active === false && <span className="text-11 text-secondary">已停用</span>}
            </div>
            {(isAdmin || id === currentUser?.id) && (
              <CustomMenu
                ellipsis
                buttonClassName="p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                optionsClassName="p-1.5"
                placement="bottom-end"
              >
                <CustomMenu.MenuItem onClick={() => setRemoveMemberModal(rowData)}>
                  <div
                    className="flex cursor-pointer items-center gap-x-1 font-medium text-danger-primary"
                    data-ph-element={MEMBER_TRACKER_ELEMENTS.PROJECT_MEMBER_TABLE_CONTEXT_MENU}
                  >
                    <CircleMinus className="size-3.5 flex-shrink-0" />
                    {rowData.member?.id === currentUser?.id ? "退出" : "移除"}
                  </div>
                </CustomMenu.MenuItem>
              </CustomMenu>
            )}
          </div>
        </div>
      )}
    </Disclosure>
  );
}

export const AccountTypeColumn = observer(function AccountTypeColumn(props: AccountTypeProps) {
  const { rowData, projectId, workspaceSlug } = props;
  const { t } = useTranslation();
  // store hooks
  const {
    project: { updateMemberRole },
    workspace: { getWorkspaceMemberDetails },
  } = useMember();
  const { data: currentUser } = useUser();
  const { getProjectRoleByWorkspaceSlugAndProjectId } = useUserPermissions();
  // form info
  const {
    control,
    formState: { errors },
  } = useForm();
  // derived values
  const isAdministrator = rowData.is_administrator ?? rowData.member.is_administrator;
  const roleLabel = isAdministrator
    ? "管理员"
    : Number(rowData.original_role) === EUserPermissions.ADMIN
      ? "项目负责人"
      : t(ROLE_DETAILS[rowData.original_role ?? EUserPermissions.GUEST].i18n_title);
  const isCurrentUser = currentUser?.id === rowData.member.id;
  const isRowDataWorkspaceAdmin = [EUserPermissions.ADMIN].includes(
    Number(getWorkspaceMemberDetails(rowData.member.id)?.role ?? EUserPermissions.GUEST)
  );
  const isCurrentUserWorkspaceAdmin = currentUser
    ? [EUserPermissions.ADMIN].includes(
        Number(getWorkspaceMemberDetails(currentUser.id)?.role ?? EUserPermissions.GUEST)
      )
    : false;
  const currentProjectRole = getProjectRoleByWorkspaceSlugAndProjectId(workspaceSlug, projectId);

  const isCurrentUserProjectAdmin = Number(currentProjectRole) === EUserPermissions.ADMIN;

  // logic
  // Workspace admin can change his own role
  // Project admin can change any role except his own and workspace admin's role
  const isRoleEditable =
    !isAdministrator &&
    rowData.member.is_active !== false &&
    ((isCurrentUserWorkspaceAdmin && isCurrentUser) ||
      (isCurrentUserProjectAdmin && !isRowDataWorkspaceAdmin && !isCurrentUser));
  const checkCurrentOptionWorkspaceRole = (value: string) => {
    const currentMemberWorkspaceRole = getWorkspaceMemberDetails(value)?.role as EUserPermissions | undefined;
    if (!value || !currentMemberWorkspaceRole) return ROLE;

    const isGuest = [EUserPermissions.GUEST].includes(currentMemberWorkspaceRole);

    return Object.fromEntries(
      Object.entries(ROLE).filter(([key]) => !isGuest || parseInt(key) === EUserPermissions.GUEST)
    );
  };

  return (
    <>
      {isRoleEditable ? (
        <Controller
          name="role"
          control={control}
          rules={{ required: "角色为必填项。" }}
          render={() => (
            <CustomSelect
              value={rowData.original_role}
              onChange={async (value: EUserProjectRoles) => {
                if (!workspaceSlug) return;
                await updateMemberRole(workspaceSlug.toString(), projectId.toString(), rowData.member.id, value).catch(
                  (err) => {
                    console.log(err, "err");
                    const error = err.error;
                    const errorString = Array.isArray(error) ? error[0] : error;

                    setToast({
                      type: TOAST_TYPE.ERROR,
                      title: "暂时无法更改此角色。",
                      message: errorString ?? "成员角色更新失败，请重试。",
                    });
                  }
                );
              }}
              label={
                <div className="flex">
                  <span>{roleLabel}</span>
                </div>
              }
              buttonClassName={`!px-0 !justify-start hover:bg-surface-1 ${errors.role ? "border-danger-strong" : "border-none"}`}
              className="w-32 rounded-md p-0"
              input
            >
              {Object.entries(checkCurrentOptionWorkspaceRole(rowData.member.id)).map(([key]) => (
                <CustomSelect.Option key={key} value={key}>
                  {Number(key) === EUserPermissions.ADMIN
                    ? "项目负责人"
                    : t(ROLE_DETAILS[Number(key) as EUserPermissions].i18n_title)}
                </CustomSelect.Option>
              ))}
            </CustomSelect>
          )}
        />
      ) : (
        <div className="flex w-32">
          <span>{roleLabel}</span>
        </div>
      )}
    </>
  );
});
