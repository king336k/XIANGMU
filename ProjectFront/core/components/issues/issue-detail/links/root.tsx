/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useMemo, useState } from "react";

import { PlusIcon } from "@plane/propel/icons";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TIssueLink } from "@plane/types";
import { EIssueServiceType } from "@plane/types";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
// local imports
import { IssueLinkCreateUpdateModal } from "./create-update-link-modal";
import { IssueLinkList } from "./links";

export type TLinkOperations = {
  create: (data: Partial<TIssueLink>) => Promise<void>;
  update: (linkId: string, data: Partial<TIssueLink>) => Promise<void>;
  remove: (linkId: string) => Promise<void>;
};

export type TIssueLinkRoot = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled?: boolean;
};

export function IssueLinkRoot(props: TIssueLinkRoot) {
  // props
  const { workspaceSlug, projectId, issueId, disabled = false } = props;
  // hooks
  const { toggleIssueLinkModal: toggleIssueLinkModalStore, createLink, updateLink, removeLink } = useIssueDetail();
  // state
  const [isIssueLinkModal, setIsIssueLinkModal] = useState(false);
  const toggleIssueLinkModal = useCallback(
    (modalToggle: boolean) => {
      toggleIssueLinkModalStore(modalToggle);
      setIsIssueLinkModal(modalToggle);
    },
    [toggleIssueLinkModalStore]
  );

  const handleLinkOperations: TLinkOperations = useMemo(
    () => ({
      create: async (data: Partial<TIssueLink>) => {
        try {
          if (!workspaceSlug || !projectId || !issueId) throw new Error("Missing required fields");
          await createLink(workspaceSlug, projectId, issueId, data);
          setToast({
            message: "链接创建成功",
            type: TOAST_TYPE.SUCCESS,
            title: "链接已创建",
          });
          toggleIssueLinkModal(false);
        } catch (error: any) {
          setToast({
            message: error?.data?.error ?? "无法创建链接",
            type: TOAST_TYPE.ERROR,
            title: "链接创建失败",
          });
          throw error;
        }
      },
      update: async (linkId: string, data: Partial<TIssueLink>) => {
        try {
          if (!workspaceSlug || !projectId || !issueId) throw new Error("Missing required fields");
          await updateLink(workspaceSlug, projectId, issueId, linkId, data);
          setToast({
            message: "链接更新成功",
            type: TOAST_TYPE.SUCCESS,
            title: "链接已更新",
          });
          toggleIssueLinkModal(false);
        } catch (error) {
          setToast({
            message: "无法更新链接",
            type: TOAST_TYPE.ERROR,
            title: "链接更新失败",
          });
          throw error;
        }
      },
      remove: async (linkId: string) => {
        try {
          if (!workspaceSlug || !projectId || !issueId) throw new Error("Missing required fields");
          await removeLink(workspaceSlug, projectId, issueId, linkId);
          setToast({
            message: "链接移除成功",
            type: TOAST_TYPE.SUCCESS,
            title: "链接已移除",
          });
          toggleIssueLinkModal(false);
        } catch {
          setToast({
            message: "无法移除链接",
            type: TOAST_TYPE.ERROR,
            title: "链接移除失败",
          });
        }
      },
    }),
    [workspaceSlug, projectId, issueId, createLink, updateLink, removeLink, toggleIssueLinkModal]
  );

  const handleOnClose = () => {
    toggleIssueLinkModal(false);
  };

  return (
    <>
      <IssueLinkCreateUpdateModal
        isModalOpen={isIssueLinkModal}
        handleOnClose={handleOnClose}
        linkOperations={handleLinkOperations}
        issueServiceType={EIssueServiceType.ISSUES}
      />

      <div className="py-1 text-11">
        <div className="flex items-center justify-between gap-2">
          <h4>链接</h4>
          {!disabled && (
            <button
              type="button"
              className={`grid h-7 w-7 place-items-center rounded-sm p-1 duration-300 outline-none hover:bg-surface-2 ${
                disabled ? "cursor-not-allowed" : "cursor-pointer"
              }`}
              onClick={() => toggleIssueLinkModal(true)}
              disabled={disabled}
            >
              <PlusIcon className="h-4 w-4" />
            </button>
          )}
        </div>

        <div>
          <IssueLinkList issueId={issueId} linkOperations={handleLinkOperations} disabled={disabled} />
        </div>
      </div>
    </>
  );
}
