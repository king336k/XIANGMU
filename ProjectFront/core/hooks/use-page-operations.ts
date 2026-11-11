/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTranslation } from "@plane/i18n";
import { useMemo } from "react";
// plane imports
import { IS_FAVORITE_MENU_OPEN } from "@plane/constants";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { EPageAccess } from "@plane/types";
import { copyUrlToClipboard } from "@plane/utils";
// hooks
import { useCollaborativePageActions } from "@/hooks/use-collaborative-page-actions";
// store types
import type { TPageInstance } from "@/store/pages/base-page";
// local storage
import useLocalStorage from "./use-local-storage";

export type TPageOperations = {
  toggleLock: () => void;
  toggleAccess: () => void;
  toggleFavorite: () => void;
  openInNewTab: () => void;
  copyLink: () => void;
  duplicate: () => void;
  toggleArchive: () => void;
};

type Props = {
  page: TPageInstance;
};

export const usePageOperations = (
  props: Props
): {
  pageOperations: TPageOperations;
} => {
  const { t } = useTranslation();
  const { page } = props;
  // derived values
  const {
    access,
    addToFavorites,
    archived_at,
    duplicate,
    is_favorite,
    is_locked,
    getRedirectionLink,
    removePageFromFavorites,
  } = page;
  // collaborative actions
  const { executeCollaborativeAction } = useCollaborativePageActions(props);
  // local storage
  const { setValue: toggleFavoriteMenu, storedValue: isFavoriteMenuOpen } = useLocalStorage<boolean>(
    IS_FAVORITE_MENU_OPEN,
    false
  );
  // page operations
  const pageOperations: TPageOperations = useMemo(() => {
    const pageLink = getRedirectionLink();

    return {
      copyLink: async () => {
        await copyUrlToClipboard(pageLink);
        setToast({
          type: TOAST_TYPE.SUCCESS,
          title: t("common.link_copied"),
          message: t("pages_workspace.toasts.link_copied"),
        });
      },
      duplicate: async () => {
        try {
          await duplicate();
          setToast({
            type: TOAST_TYPE.SUCCESS,
            title: t("common.success"),
            message: t("pages_workspace.toasts.duplicated"),
          });
        } catch (_error) {
          setToast({
            type: TOAST_TYPE.ERROR,
            title: t("common.error.label"),
            message: t("pages_workspace.toasts.duplicate_error"),
          });
        }
      },
      move: async () => {},
      openInNewTab: () => window.open(pageLink, "_blank"),
      toggleAccess: async () => {
        const changedPageType = access === EPageAccess.PUBLIC ? "private" : "public";
        try {
          if (access === EPageAccess.PUBLIC)
            await executeCollaborativeAction({ type: "sendMessageToServer", message: "make-private" });
          else await executeCollaborativeAction({ type: "sendMessageToServer", message: "make-public" });
          setToast({
            type: TOAST_TYPE.SUCCESS,
            title: t("common.success"),
            message: t("pages_workspace.toasts.access_updated", { access: t(`common.access.${changedPageType}`) }),
          });
        } catch (_error) {
          setToast({
            type: TOAST_TYPE.ERROR,
            title: t("common.error.label"),
            message: t("pages_workspace.toasts.access_error", { access: t(`common.access.${changedPageType}`) }),
          });
        }
      },
      toggleArchive: async () => {
        if (archived_at) {
          try {
            await executeCollaborativeAction({ type: "sendMessageToServer", message: "unarchive" });
            setToast({
              type: TOAST_TYPE.SUCCESS,
              title: t("common.success"),
              message: t("pages_workspace.toasts.restored"),
            });
          } catch (_error) {
            setToast({
              type: TOAST_TYPE.ERROR,
              title: t("common.error.label"),
              message: t("pages_workspace.toasts.restore_error"),
            });
          }
        } else {
          try {
            await executeCollaborativeAction({ type: "sendMessageToServer", message: "archive" });
            setToast({
              type: TOAST_TYPE.SUCCESS,
              title: t("common.success"),
              message: t("pages_workspace.toasts.archived"),
            });
          } catch (_error) {
            setToast({
              type: TOAST_TYPE.ERROR,
              title: t("common.error.label"),
              message: t("pages_workspace.toasts.archive_error"),
            });
          }
        }
      },
      toggleFavorite: async () => {
        if (is_favorite) {
          try {
            await removePageFromFavorites();
            setToast({
              type: TOAST_TYPE.SUCCESS,
              title: t("common.success"),
              message: t("pages_workspace.toasts.unfavorited"),
            });
          } catch (_error) {
            setToast({
              type: TOAST_TYPE.ERROR,
              title: t("common.error.label"),
              message: t("pages_workspace.toasts.unfavorite_error"),
            });
          }
        } else {
          try {
            await addToFavorites();
            if (!isFavoriteMenuOpen) toggleFavoriteMenu(true);
            setToast({
              type: TOAST_TYPE.SUCCESS,
              title: t("common.success"),
              message: t("pages_workspace.toasts.favorited"),
            });
          } catch (_error) {
            setToast({
              type: TOAST_TYPE.ERROR,
              title: t("common.error.label"),
              message: t("pages_workspace.toasts.favorite_error"),
            });
          }
        }
      },
      toggleLock: async () => {
        if (is_locked) {
          try {
            await executeCollaborativeAction({ type: "sendMessageToServer", message: "unlock" });
            setToast({
              type: TOAST_TYPE.SUCCESS,
              title: t("common.success"),
              message: t("pages_workspace.toasts.unlocked"),
            });
          } catch (_error) {
            setToast({
              type: TOAST_TYPE.ERROR,
              title: t("common.error.label"),
              message: t("pages_workspace.toasts.unlock_error"),
            });
          }
        } else {
          try {
            await executeCollaborativeAction({ type: "sendMessageToServer", message: "lock" });
            setToast({
              type: TOAST_TYPE.SUCCESS,
              title: t("common.success"),
              message: t("pages_workspace.toasts.locked"),
            });
          } catch (_error) {
            setToast({
              type: TOAST_TYPE.ERROR,
              title: t("common.error.label"),
              message: t("pages_workspace.toasts.lock_error"),
            });
          }
        }
      },
    };
  }, [
    t,
    access,
    addToFavorites,
    archived_at,
    duplicate,
    executeCollaborativeAction,
    getRedirectionLink,
    is_favorite,
    is_locked,
    isFavoriteMenuOpen,
    removePageFromFavorites,
    toggleFavoriteMenu,
  ]);
  return {
    pageOperations,
  };
};
