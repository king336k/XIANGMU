import { ThemeShortcuts } from "@/components/appearance/theme-shortcuts";
import { projectDutySummary } from "@/components/quality/duty-summary";
import { useResolvedProjectParams } from "@/hooks/use-resolved-project-params";
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState, useEffect } from "react";
import { observer } from "mobx-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useWorkspace } from "@/hooks/store/use-workspace";
import useSWR from "swr";
import { LogOut, Settings, UserRound } from "lucide-react";
// plane imports
import { GOD_MODE_URL } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { Avatar, CustomMenu } from "@plane/ui";
import { getFileURL } from "@plane/utils";
// components
import { qualityApi } from "@/components/quality/api";
// hooks
import { useAppTheme } from "@/hooks/store/use-app-theme";
import { useCommandPalette } from "@/hooks/store/use-command-palette";
import { useUser } from "@/hooks/store/user";

export const UserMenuRoot = observer(function UserMenuRoot() {
  // states
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  // router
  const router = useRouter();
  // store hooks
  const { toggleAnySidebarDropdown } = useAppTheme();
  const { data: currentUser } = useUser();
  const { signOut } = useUser();
  const { workspaceSlug, projectId } = useResolvedProjectParams();
  const query = useSearchParams();
  const { currentWorkspace } = useWorkspace();
  const settingsWorkspace = workspaceSlug || currentWorkspace?.slug;
  const settingsProject = projectId || query.get("project");
  const { data: roleContext } = useSWR(
    projectId && workspaceSlug ? `/api/workspaces/${workspaceSlug}/projects/${projectId}/quality/context/` : null,
    (url: string) => qualityApi.read<{ business_roles_enabled: boolean; business_role_name: string }>(url)
  );
  const userName =
    currentUser?.display_name ||
    [currentUser?.first_name, currentUser?.last_name].filter(Boolean).join(" ") ||
    currentUser?.username ||
    "账号";
  const generatedUsername = /^[a-f0-9]{32}$/i.test(currentUser?.username || "");
  const { toggleProfileSettingsModal } = useCommandPalette();
  // derived values
  const isUserInstanceAdmin = false;
  // translation
  const { t } = useTranslation();

  const handleSignOut = () => {
    signOut().catch(() =>
      setToast({
        type: TOAST_TYPE.ERROR,
        title: t("auth.sign_out.toast.error.title"),
        message: t("auth.sign_out.toast.error.message"),
      })
    );
  };

  // Toggle sidebar dropdown state when menu is open
  useEffect(() => {
    if (isUserMenuOpen) toggleAnySidebarDropdown(true);
    else toggleAnySidebarDropdown(false);
  }, [isUserMenuOpen, toggleAnySidebarDropdown]);

  return (
    <CustomMenu
      className="flex items-center"
      customButton={
        <span
          className="inline-flex max-w-36 items-center gap-1.5 rounded px-1.5 py-1 text-12 text-primary"
          title={`当前账号：${userName}`}
        >
          {currentUser?.avatar_url ? (
            <Avatar
              name={currentUser?.display_name}
              src={getFileURL(currentUser?.avatar_url ?? "")}
              size={20}
              shape="circle"
            />
          ) : (
            <UserRound className="size-4 shrink-0 text-secondary" />
          )}
          <span className="hidden max-w-24 truncate sm:inline">{userName}</span>
        </span>
      }
      menuButtonOnClick={() => !isUserMenuOpen && setIsUserMenuOpen(true)}
      onMenuClose={() => setIsUserMenuOpen(false)}
      placement="bottom-end"
      maxHeight="2xl"
      optionsClassName="w-72 p-3 flex flex-col gap-y-3"
      closeOnSelect
    >
      <div className="flex items-start gap-3 border-b border-subtle pb-3">
        <Avatar
          name={currentUser?.display_name}
          src={getFileURL(currentUser?.avatar_url ?? "")}
          size={40}
          shape="circle"
          className="text-18 font-medium"
        />
        <div className="min-w-0 space-y-1">
          <p className="text-13 font-medium break-words">{userName}</p>
          {!generatedUsername && <p className="text-11 break-all text-secondary">账号：{currentUser?.username}</p>}
          <p className="truncate text-11 text-secondary" title={currentUser?.email}>
            {currentUser?.email}
          </p>
          {roleContext?.business_roles_enabled && (
            <p className="text-11 text-secondary">
              项目职责：{projectDutySummary(roleContext.business_role_name.split("、")).label}
            </p>
          )}
          {generatedUsername && (
            <details className="text-11 text-secondary">
              <summary className="cursor-pointer">账号详情</summary>
              <p className="mt-1 break-all">内部标识：{currentUser?.username}</p>
            </details>
          )}
        </div>
      </div>
      <div>
        <CustomMenu.MenuItem
          onClick={() =>
            settingsWorkspace
              ? router.push(
                  `/${settingsWorkspace}/settings/members/${settingsProject ? `?project=${encodeURIComponent(String(settingsProject))}` : ""}`
                )
              : toggleProfileSettingsModal({ activeTab: "general", isOpen: true })
          }
          className="flex items-center gap-2"
        >
          <Settings className="size-3.5 shrink-0" />
          {t("settings")}
        </CustomMenu.MenuItem>
        <CustomMenu.MenuItem
          onClick={() => toggleProfileSettingsModal({ activeTab: "general", isOpen: true })}
          className="flex items-center gap-2"
        >
          <UserRound className="size-3.5 shrink-0" />
          个人资料
        </CustomMenu.MenuItem>
      </div>
      <div className="border-t border-subtle pt-3">
        <ThemeShortcuts onOpen={() => toggleProfileSettingsModal({ activeTab: "preferences", isOpen: true })} />
      </div>
      <CustomMenu.MenuItem onClick={handleSignOut} className="flex items-center gap-2">
        <LogOut className="size-3.5 shrink-0" />
        {t("sign_out")}
      </CustomMenu.MenuItem>
      {isUserInstanceAdmin && (
        <CustomMenu.MenuItem
          onClick={() => router.push(GOD_MODE_URL)}
          className="bg-accent-primary/20 text-accent-primary hover:bg-accent-primary/30 hover:text-accent-secondary"
        >
          {t("enter_god_mode")}
        </CustomMenu.MenuItem>
      )}
    </CustomMenu>
  );
});
