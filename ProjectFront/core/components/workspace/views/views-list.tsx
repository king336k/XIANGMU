/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { NativeClientPagination, useNativeClientPagination } from "@/components/common/native-client-pagination";

import { useParams } from "next/navigation";
import useSWR from "swr";
// components
import { ViewListLoader } from "@/components/ui/loader/view-list-loader";
// hooks
import { useGlobalView } from "@/hooks/store/use-global-view";
// local imports
import { GlobalViewListItem } from "./view-list-item";

type Props = {
  searchQuery: string;
};

export const GlobalViewsList = observer(function GlobalViewsList(props: Props) {
  const { searchQuery } = props;
  // router
  const { workspaceSlug } = useParams();
  // store hooks
  const { fetchAllGlobalViews, currentWorkspaceViews, getSearchedViews } = useGlobalView();

  useSWR(
    workspaceSlug ? `GLOBAL_VIEWS_LIST_${workspaceSlug.toString()}` : null,
    workspaceSlug ? () => fetchAllGlobalViews(workspaceSlug.toString()) : null
  );

  const filteredViewsList = getSearchedViews(searchQuery);
  const pagination = useNativeClientPagination(filteredViewsList, JSON.stringify([workspaceSlug, searchQuery]));
  if (!currentWorkspaceViews) return <ViewListLoader />;

  return (
    <>
      {pagination.items.map((viewId) => (
        <GlobalViewListItem key={viewId} viewId={viewId} />
      ))}
      <NativeClientPagination label="工作区视图" pagination={pagination} />
    </>
  );
});
