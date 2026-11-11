/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { boardInitialCount, boardLayoutRows, orderedBoardGroups } from "./arrangement";
import { useColumnMotion } from "./use-column-motion";
import type { BoardDropPlacement } from "./arrangement";
import { useBoardArrangement } from "./use-arrangement";
import { SortableKanbanColumn } from "./sortable-column";
import type { MutableRefObject } from "react";
import { observer } from "mobx-react";
import type {
  GroupByColumnTypes,
  IGroupByColumn,
  TGroupedIssues,
  TIssue,
  IIssueDisplayProperties,
  IIssueMap,
  TSubGroupedIssues,
  TIssueKanbanFilters,
  TIssueGroupByOptions,
  TIssueOrderByOptions,
} from "@plane/types";
// constants
import { ContentWrapper } from "@plane/ui";
// components
import RenderIfVisible from "@/components/core/render-if-visible-HOC";
import { KanbanColumnLoader } from "@/components/ui/loader/layouts/kanban-layout-loader";
// hooks
import { useKanbanView } from "@/hooks/store/use-kanban-view";
import { useIssueStoreType } from "@/hooks/use-issue-layout-store";
// types
// parent components
import { useWorkFlowFDragNDrop } from "@/components/workflow";
import type { TRenderQuickActions } from "../list/list-view-types";
import type { GroupDropLocation } from "../utils";
import { getGroupByColumns, isWorkspaceLevel, getApproximateCardHeight } from "../utils";
// components
import { HeaderGroupByCard } from "./headers/group-by-card";
import { KanbanGroup } from "./kanban-group";

export interface IKanBan {
  issuesMap: IIssueMap;
  groupedIssueIds: TGroupedIssues | TSubGroupedIssues;
  getGroupIssueCount: (
    groupId: string | undefined,
    subGroupId: string | undefined,
    isSubGroupCumulative: boolean
  ) => number | undefined;
  displayProperties: IIssueDisplayProperties | undefined;
  sub_group_by: TIssueGroupByOptions | undefined;
  group_by: TIssueGroupByOptions | undefined;
  orderBy: TIssueOrderByOptions | undefined;
  isDropDisabled?: boolean;
  dropErrorMessage?: string | undefined;
  sub_group_id?: string;
  sub_group_index?: number;
  updateIssue: ((projectId: string | null, issueId: string, data: Partial<TIssue>) => Promise<void>) | undefined;
  quickActions: TRenderQuickActions;
  collapsedGroups: TIssueKanbanFilters;
  handleCollapsedGroups: (toggle: "group_by" | "sub_group_by", value: string) => void;
  loadMoreIssues: (groupId?: string, subGroupId?: string) => void | Promise<unknown>;
  enableQuickIssueCreate?: boolean;
  quickAddCallback?: (projectId: string | null | undefined, data: TIssue) => Promise<TIssue | undefined>;
  disableIssueCreation?: boolean;
  addIssuesToView?: (issueIds: string[]) => Promise<TIssue>;
  canEditProperties: (projectId: string | undefined, issueId?: string) => boolean;
  scrollableContainerRef?: MutableRefObject<HTMLDivElement | null>;
  handleOnDrop: (source: GroupDropLocation, destination: GroupDropLocation) => Promise<void>;
  showEmptyGroup?: boolean;
  subGroupIndex?: number;
  isEpic?: boolean;
}

export const KanBan = observer(function KanBan(props: IKanBan) {
  const {
    issuesMap,
    groupedIssueIds,
    getGroupIssueCount,
    displayProperties,
    sub_group_by,
    group_by,
    sub_group_id = "null",
    updateIssue,
    quickActions,
    collapsedGroups,
    handleCollapsedGroups,
    enableQuickIssueCreate,
    quickAddCallback,
    loadMoreIssues,
    disableIssueCreation,
    addIssuesToView,
    canEditProperties,
    scrollableContainerRef,
    handleOnDrop,
    showEmptyGroup = true,
    orderBy,
    isDropDisabled,
    dropErrorMessage,
    subGroupIndex = 0,
    isEpic = false,
  } = props;
  // i18n
  // store hooks
  const storeType = useIssueStoreType();
  const issueKanBanView = useKanbanView();
  // derived values
  const isDragDisabled = !issueKanBanView?.getCanUserDragDrop(group_by, sub_group_by);

  const { getIsWorkflowWorkItemCreationDisabled } = useWorkFlowFDragNDrop(group_by, sub_group_by);

  const list = getGroupByColumns({
    groupBy: group_by as GroupByColumnTypes,
    includeNone: true,
    isWorkspaceLevel: isWorkspaceLevel(storeType),
    isEpic: isEpic,
  });

  const arrangement = useBoardArrangement(group_by);
  const orderedList = useMemo(
    () => (sub_group_by ? list || [] : orderedBoardGroups(list || [], arrangement.order)),
    [list, arrangement.order, sub_group_by]
  );
  const groupIds = useMemo(() => orderedList.map((group) => group.id), [orderedList]);
  const initialCount = sub_group_by ? undefined : boardInitialCount(arrangement);
  const grid = !sub_group_by && arrangement.layout !== "horizontal";
  const rows = boardLayoutRows(groupIds, arrangement.layout, arrangement.rowStarts || []);
  const columnMotion = useColumnMotion(groupIds, arrangement.layout + JSON.stringify(arrangement.rowStarts));
  const onPlace = useCallback(
    (source: string, target: string, placement: BoardDropPlacement) =>
      columnMotion.commit(() => arrangement.place(groupIds, source, target, placement)),
    [columnMotion.commit, arrangement.place, groupIds]
  );
  const [boardWidth, setBoardWidth] = useState(0);
  useEffect(() => {
    const node = scrollableContainerRef?.current;
    if (!node) return;
    const measure = () => setBoardWidth(node.clientWidth);
    measure();
    const resize = new ResizeObserver(measure);
    resize.observe(node);
    return () => resize.disconnect();
  }, [scrollableContainerRef]);
  const custom = !sub_group_by && arrangement.layout === "custom-rows" && boardWidth >= 640;
  const maxColumns = Math.max(1, ...rows.map((row) => row.length));
  if (!list) return null;

  const visibilityGroupBy = (_list: IGroupByColumn): { showGroup: boolean; showIssues: boolean } => {
    if (sub_group_by) {
      const groupVisibility = {
        showGroup: true,
        showIssues: true,
      };
      if (!showEmptyGroup) {
        groupVisibility.showGroup = (getGroupIssueCount(_list.id, undefined, false) ?? 0) > 0;
      }
      return groupVisibility;
    } else {
      const groupVisibility = {
        showGroup: true,
        showIssues: true,
      };
      if (!showEmptyGroup) {
        if ((getGroupIssueCount(_list.id, undefined, false) ?? 0) > 0) groupVisibility.showGroup = true;
        else groupVisibility.showGroup = false;
      }
      if (collapsedGroups?.group_by.includes(_list.id)) groupVisibility.showIssues = false;
      return groupVisibility;
    }
  };

  const isGroupByCreatedBy = group_by === "created_by";
  const approximateCardHeight = getApproximateCardHeight(displayProperties);
  const isSubGroup = !!sub_group_id && sub_group_id !== "null";

  return (
    <ContentWrapper
      ref={columnMotion.rootRef}
      style={
        custom ? { gridTemplateColumns: `repeat(${maxColumns},minmax(0,1fr))`, minWidth: maxColumns * 300 } : undefined
      }
      className={`relative gap-4 !pt-2 !pb-3 ${!sub_group_by ? "!h-auto !items-start !overflow-visible" : ""} ${grid ? `!grid grid-cols-1 ${arrangement.layout === "two-columns" ? "@2xl:grid-cols-2" : ""}` : "flex-row"}`}
    >
      {list &&
        list.length > 0 &&
        orderedList.map((subList: IGroupByColumn, groupIndex) => {
          const groupByVisibilityToggle = visibilityGroupBy(subList);

          if (groupByVisibilityToggle.showGroup === false) return <></>;

          const issueIds = isSubGroup
            ? ((groupedIssueIds as TSubGroupedIssues)?.[subList.id]?.[sub_group_id] ?? [])
            : ((groupedIssueIds as TGroupedIssues)?.[subList.id] ?? []);
          const issueLength = issueIds?.length;
          const groupHeight = Math.min(issueLength, initialCount || issueLength) * approximateCardHeight;

          return (
            <SortableKanbanColumn
              key={subList.id}
              id={subList.id}
              title={subList.name}
              boardKey={arrangement.key}
              ids={groupIds}
              onPlace={onPlace}
              onPreview={columnMotion.showPreview}
              style={
                custom
                  ? {
                      gridRowStart: rows.findIndex((row) => row.includes(subList.id)) + 1,
                      gridColumnStart: (rows.find((row) => row.includes(subList.id))?.indexOf(subList.id) || 0) + 1,
                    }
                  : undefined
              }
              enabled={!sub_group_by}
              className={`group relative flex min-w-0 shrink-0 flex-col ${grid ? "h-auto self-start rounded-lg border border-subtle bg-surface-2 p-2" : groupByVisibilityToggle.showIssues ? "w-[min(350px,calc(100vw-56px))]" : ""}`}
            >
              {(dragHandle) => (
                <>
                  {!sub_group_by && (
                    <div className="sticky top-0 z-[2] w-full flex-shrink-0 bg-surface-2 py-1">
                      <HeaderGroupByCard
                        dragHandle={dragHandle}
                        gridLayout={grid}
                        sub_group_by={sub_group_by}
                        group_by={group_by}
                        column_id={subList.id}
                        icon={subList.icon}
                        title={subList.name}
                        count={getGroupIssueCount(subList.id, undefined, false) ?? 0}
                        issuePayload={subList.payload}
                        disableIssueCreation={
                          disableIssueCreation ||
                          isGroupByCreatedBy ||
                          getIsWorkflowWorkItemCreationDisabled(subList.id, sub_group_id)
                        }
                        addIssuesToView={addIssuesToView}
                        collapsedGroups={collapsedGroups}
                        handleCollapsedGroups={handleCollapsedGroups}
                        isEpic={isEpic}
                      />
                    </div>
                  )}

                  {groupByVisibilityToggle.showIssues && (
                    <RenderIfVisible
                      verticalOffset={100}
                      horizontalOffset={100}
                      root={scrollableContainerRef}
                      classNames={sub_group_by ? "h-full min-h-[120px]" : "h-auto"}
                      forceRender={!sub_group_by}
                      defaultHeight={`${groupHeight}px`}
                      placeholderChildren={
                        <KanbanColumnLoader
                          ignoreHeader
                          cardHeight={approximateCardHeight}
                          cardsInColumn={issueLength !== undefined && issueLength < 3 ? issueLength : 3}
                          shouldAnimate={false}
                        />
                      }
                      defaultValue={groupIndex < 5 && subGroupIndex < 2}
                      useIdleTime
                    >
                      <KanbanGroup
                        initialVisibleCount={initialCount}
                        groupTitle={subList.name}
                        groupId={subList.id}
                        issuesMap={issuesMap}
                        groupedIssueIds={groupedIssueIds}
                        displayProperties={displayProperties}
                        sub_group_by={sub_group_by}
                        group_by={group_by}
                        orderBy={orderBy}
                        sub_group_id={sub_group_id}
                        isDragDisabled={isDragDisabled}
                        isDropDisabled={!!subList.isDropDisabled || !!isDropDisabled}
                        dropErrorMessage={subList.dropErrorMessage ?? dropErrorMessage}
                        updateIssue={updateIssue}
                        quickActions={quickActions}
                        enableQuickIssueCreate={enableQuickIssueCreate}
                        quickAddCallback={quickAddCallback}
                        disableIssueCreation={disableIssueCreation}
                        canEditProperties={canEditProperties}
                        scrollableContainerRef={scrollableContainerRef}
                        loadMoreIssues={loadMoreIssues}
                        handleOnDrop={handleOnDrop}
                        isEpic={isEpic}
                      />
                    </RenderIfVisible>
                  )}
                </>
              )}
            </SortableKanbanColumn>
          );
        })}
    </ContentWrapper>
  );
});
