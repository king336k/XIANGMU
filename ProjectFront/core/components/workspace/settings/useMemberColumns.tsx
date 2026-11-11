/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { useParams } from "next/navigation";
import { EUserPermissions, EUserPermissionsLevel, LOGIN_MEDIUM_LABELS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { renderFormattedDate } from "@plane/utils";
import { MemberHeaderColumn } from "@/components/project/member-header-column";
import type { RowData } from "@/components/workspace/settings/member-columns";
import { AccountTypeColumn, NameColumn } from "@/components/workspace/settings/member-columns";
import { useMember } from "@/hooks/store/use-member";
import { useUser, useUserPermissions } from "@/hooks/store/user";
import type { IMemberFilters } from "@/store/member/utils";
import { qualityApi } from "@/components/quality/api";

export const useMemberColumns = () => {
  // states
  const [removeMemberModal, setRemoveMemberModal] = useState<RowData | null>(null);

  const { workspaceSlug } = useParams();

  const { data: currentUser } = useUser();
  const { allowPermissions } = useUserPermissions();
  const {
    workspace: {
      filtersStore: { filters, updateFilters },
    },
  } = useMember();
  const { t } = useTranslation();

  // derived values
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);
  const { data: accountContext } = useSWR(
    isAdmin && workspaceSlug ? `/api/workspaces/${workspaceSlug}/member-context/` : null,
    (url: string) =>
      qualityApi.read<{
        members: Record<
          string,
          { username: string; business_roles: { project: string; role: string }[]; identity_mapped: boolean }
        >;
      }>(url)
  );

  // oxlint-disable-next-line unicorn/consistent-function-scoping
  const isSuspended = (rowData: RowData) => rowData.is_active === false;

  // handlers
  const handleDisplayFilterUpdate = (filterUpdates: Partial<IMemberFilters>) => {
    updateFilters(filterUpdates);
  };

  const columns = [
    {
      key: "Full name",
      content: t("workspace_settings.settings.members.details.full_name"),
      thClassName: "text-left",
      thRender: () => (
        <MemberHeaderColumn
          property="full_name"
          label="账号"
          displayFilters={filters}
          handleDisplayFilterUpdate={handleDisplayFilterUpdate}
        />
      ),
      tdRender: (rowData: RowData) => (
        <NameColumn
          rowData={rowData}
          workspaceSlug={workspaceSlug}
          isAdmin={isAdmin}
          currentUser={currentUser}
          setRemoveMemberModal={setRemoveMemberModal}
        />
      ),
    },

    {
      key: "Project responsibilities",
      content: "项目职责",
      tdRender: (rowData: RowData) => (
        <div className="max-w-56 space-y-1 text-12">
          {accountContext?.members[rowData.member.id]?.business_roles.length ? (
            accountContext.members[rowData.member.id].business_roles.map((item) => (
              <p key={`${item.project}-${item.role}`} className="truncate" title={`${item.project}：${item.role}`}>
                {item.role}
                <span className="ml-1 text-11 text-secondary">· {item.project}</span>
              </p>
            ))
          ) : (
            <span className="text-secondary">未分配或无可见项目</span>
          )}
        </div>
      ),
    },

    {
      key: "Account type",
      content: t("workspace_settings.settings.members.details.account_type"),
      thRender: () => (
        <MemberHeaderColumn
          property="role"
          label="工作空间权限"
          displayFilters={filters}
          handleDisplayFilterUpdate={handleDisplayFilterUpdate}
        />
      ),
      tdRender: (rowData: RowData) => <AccountTypeColumn rowData={rowData} workspaceSlug={workspaceSlug} />,
    },

    {
      key: "Authentication",
      content: "登录方式",
      tdRender: (rowData: RowData) => {
        if (isSuspended(rowData)) return null;
        const loginMedium = rowData.member.last_login_medium;
        if (!loginMedium) return null;
        return <div>{loginMedium === "email" ? "账号密码" : LOGIN_MEDIUM_LABELS[loginMedium]}</div>;
      },
    },

    {
      key: "Joining date",
      content: t("workspace_settings.settings.members.details.joining_date"),
      tdRender: (rowData: RowData) =>
        isSuspended(rowData) ? null : <div>{renderFormattedDate(rowData?.member?.joining_date)}</div>,
      thRender: () => (
        <MemberHeaderColumn
          property="joining_date"
          displayFilters={filters}
          handleDisplayFilterUpdate={handleDisplayFilterUpdate}
        />
      ),
    },
  ];
  return { columns, workspaceSlug, removeMemberModal, setRemoveMemberModal };
};
