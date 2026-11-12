/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import { observer } from "mobx-react";
import { useParams, usePathname } from "next/navigation";
// plane imports
import type { EIssuesStoreType, TIssue } from "@plane/types";
// local imports
import { CreateUpdateIssueModalBase } from "./base";
import { IssueModalProvider } from "./provider";

export interface IssuesModalProps {
  data?: Partial<TIssue>;
  isOpen: boolean;
  onClose: () => void;
  beforeFormSubmit?: () => Promise<void>;
  onSubmit?: (res: TIssue) => Promise<void>;
  withDraftIssueWrapper?: boolean;
  storeType?: EIssuesStoreType;
  isDraft?: boolean;
  fetchIssueDetails?: boolean;
  moveToIssue?: boolean;
  modalTitle?: string;
  primaryButtonText?: {
    default: string;
    loading: string;
  };
  isProjectSelectionDisabled?: boolean;
  templateId?: string;
  allowedProjectIds?: string[];
  showActionItemsOnUpdate?: boolean;
}

export const CreateUpdateIssueModal = observer(function CreateUpdateIssueModal(props: IssuesModalProps) {
  // router params
  const { cycleId, moduleId } = useParams();
  const pathname = usePathname();
  const creatingTask =
    !props.data?.id &&
    !props.data?.is_epic &&
    !props.isDraft &&
    /^\/[^/]+\/(?:p|projects)\/[^/]+\/issues\/?$/.test(pathname);
  // derived values
  const dataForPreload = {
    ...props.data,
    cycle_id: props.data?.cycle_id ? props.data?.cycle_id : cycleId ? cycleId.toString() : null,
    module_ids: props.data?.module_ids ? props.data?.module_ids : moduleId ? [moduleId.toString()] : null,
  };

  if (!props.isOpen) return null;
  return (
    <IssueModalProvider
      templateId={props.templateId}
      dataForPreload={dataForPreload}
      allowedProjectIds={props.allowedProjectIds}
    >
      <CreateUpdateIssueModalBase
        {...props}
        modalTitle={props.modalTitle ?? (creatingTask ? "新建任务" : undefined)}
        primaryButtonText={
          props.primaryButtonText ?? (creatingTask ? { default: "新建任务", loading: "正在创建…" } : undefined)
        }
      />
    </IssueModalProvider>
  );
});
