/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useRef } from "react";
import { X } from "lucide-react";
import { observer } from "mobx-react";
// plane imports
import { PROFILE_SETTINGS_TABS } from "@plane/constants";
import { IconButton } from "@plane/propel/icon-button";
import type { TProfileSettingsTabs } from "@plane/types";
import { EModalPosition, EModalWidth, ModalCore } from "@plane/ui";
// hooks
import { useCommandPalette } from "@/hooks/store/use-command-palette";
// local imports
import { ProfileSettingsContent } from "./content";
import { ProfileSettingsSidebarRoot } from "./sidebar";
import { PreferencesProfileSettings } from "./content/pages/preferences/root";

export const ProfileSettingsModal = observer(function ProfileSettingsModal() {
  // store hooks
  const { profileSettingsModal, toggleProfileSettingsModal } = useCommandPalette();
  // derived values
  const activeTab = PROFILE_SETTINGS_TABS.includes(profileSettingsModal.activeTab || "general")
    ? profileSettingsModal.activeTab || "general"
    : "general";
  const returnTab = useRef<TProfileSettingsTabs | null>(null);

  const handleClose = useCallback(() => {
    if (activeTab === "preferences" && returnTab.current) {
      toggleProfileSettingsModal({ activeTab: returnTab.current });
      returnTab.current = null;
      return;
    }
    toggleProfileSettingsModal({
      isOpen: false,
    });
    setTimeout(() => {
      toggleProfileSettingsModal({
        activeTab: null,
      });
    }, 300);
  }, [activeTab, toggleProfileSettingsModal]);

  if (activeTab === "preferences")
    return (
      <ModalCore
        isOpen={profileSettingsModal.isOpen}
        handleClose={handleClose}
        position={EModalPosition.CENTER}
        width={EModalWidth.XL}
        className="max-h-[85vh] overflow-y-auto"
      >
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-subtle bg-surface-1 px-5 py-4">
          <h2 className="text-16 font-semibold">主题</h2>
          <IconButton aria-label="关闭主题" size="base" variant="tertiary" icon={X} onClick={handleClose} />
        </header>
        <div className="p-5">
          <PreferencesProfileSettings />
        </div>
      </ModalCore>
    );

  return (
    <ModalCore
      isOpen={profileSettingsModal.isOpen}
      handleClose={handleClose}
      position={EModalPosition.CENTER}
      width={EModalWidth.VIXL}
      className="h-175"
    >
      <div className="@container relative size-full">
        <div className="flex size-full">
          <ProfileSettingsSidebarRoot
            activeTab={activeTab}
            className="w-[250px] rounded-l-xl"
            updateActiveTab={(tab) => {
              if (tab === "preferences") returnTab.current = activeTab;
              toggleProfileSettingsModal({ activeTab: tab });
            }}
          />
          <ProfileSettingsContent activeTab={activeTab} className="flex-1 rounded-r-xl" />
        </div>
        <div className="absolute top-3.5 right-3.5">
          <IconButton size="base" variant="tertiary" icon={X} onClick={handleClose} />
        </div>
      </div>
    </ModalCore>
  );
});
