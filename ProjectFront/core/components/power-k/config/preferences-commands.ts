/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback } from "react";
import { useTheme } from "next-themes";
import { Palette } from "lucide-react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
// components
import type { TPowerKCommandConfig } from "@/components/power-k/core/types";
// hooks
import { useUserProfile } from "@/hooks/store/user";

/**
 * Preferences commands - Preferences related commands
 */
export const usePowerKPreferencesCommands = (): TPowerKCommandConfig[] => {
  // store hooks
  const { setTheme } = useTheme();
  const { updateUserTheme } = useUserProfile();
  // translation
  const { t } = useTranslation();

  const handleUpdateTheme = useCallback(
    async (newTheme: string) => {
      setTheme(newTheme);
      return updateUserTheme({ theme: newTheme })
        .then(() => {
          setToast({
            type: TOAST_TYPE.SUCCESS,
            title: "主题已更新",
            message: "正在重新加载…",
          });
          // reload the page after showing the toast
          window.location.reload();
          return;
        })
        .catch(() => {
          setToast({
            type: TOAST_TYPE.ERROR,
            title: t("toast.error"),
            message: t("power_k.preferences_actions.toast.theme.error"),
          });
          return;
        });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setTheme, updateUserTheme]
  );

  return [
    {
      id: "update_interface_theme",
      group: "preferences",
      type: "change-page",
      page: "update-theme",
      i18n_title: "power_k.preferences_actions.update_theme",
      icon: Palette,
      onSelect: (data) => {
        const theme = data as string;
        void handleUpdateTheme(theme);
      },
      isEnabled: () => true,
      isVisible: () => true,
      closeOnSelect: true,
    },
  ];
};
