/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { AnalyticsDetails } from "../analytics-details";
import { useMemo, useState } from "react";
import type { ColumnDef, Row, RowData } from "@tanstack/react-table";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { UserRound } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { Logo } from "@plane/propel/emoji-icon-picker";
import { ProjectIcon } from "@plane/propel/icons";
// plane package imports
import type { AnalyticsTableDataMap, WorkItemInsightColumns } from "@plane/types";
// plane web components
import { Avatar } from "@plane/ui";
import { getFileURL } from "@plane/utils";
// hooks
import { useAnalytics } from "@/hooks/store/use-analytics";
import { useProject } from "@/hooks/store/use-project";
import { AnalyticsService } from "@/services/analytics.service";
// plane web components
import { exportCSV } from "../export";
import { InsightTable } from "../insight-table";

const analyticsService = new AnalyticsService();

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    export: {
      key: string;
      value: (row: Row<TData>) => string | number;
      label?: string;
    };
  }
}

const WorkItemsInsightTable = observer(function WorkItemsInsightTable() {
  // router
  const params = useParams();
  const workspaceSlug = params.workspaceSlug.toString();
  const { t } = useTranslation();
  // store hooks
  const { getProjectById } = useProject();
  const { selectedDuration, selectedProjects, selectedCycle, selectedModule, isPeekView, isEpic } = useAnalytics();
  const [detail, setDetail] = useState<{ metric: string; title: string; projectId?: string; assigneeId?: string }>();
  const { data: workItemsData, isLoading } = useSWR(
    `insights-table-work-items-${workspaceSlug}-${selectedDuration}-${selectedProjects}-${selectedCycle}-${selectedModule}-${isPeekView}-${isEpic}`,
    () =>
      analyticsService.getAdvanceAnalyticsStats<WorkItemInsightColumns[]>(
        workspaceSlug,
        "work-items",
        {
          // date_filter: selectedDuration,
          ...(selectedProjects?.length > 0 ? { project_ids: selectedProjects.join(",") } : {}),
          ...(selectedCycle ? { cycle_id: selectedCycle } : {}),
          ...(selectedModule ? { module_id: selectedModule } : {}),
          ...(isEpic ? { epic: true } : {}),
        },
        isPeekView
      )
  );
  // derived values
  const columnsLabels: Record<keyof Omit<WorkItemInsightColumns, "project_id" | "avatar_url" | "assignee_id">, string> =
    useMemo(
      () => ({
        backlog_work_items: t("workspace_projects.state.backlog"),
        started_work_items: t("workspace_projects.state.started"),
        un_started_work_items: t("workspace_projects.state.unstarted"),
        completed_work_items: t("workspace_projects.state.completed"),
        cancelled_work_items: t("workspace_projects.state.cancelled"),
        project__name: t("common.project"),
        display_name: t("common.assignee"),
      }),
      [t]
    );
  const columns: ColumnDef<AnalyticsTableDataMap["work-items"]>[] = useMemo(
    () => [
      !isPeekView
        ? {
            accessorKey: "project__name",
            header: () => <div className="text-left">{columnsLabels["project__name"]}</div>,
            cell: ({ row }) => {
              const project = getProjectById(row.original.project_id);
              return (
                <div className="flex items-center gap-2">
                  {project?.logo_props ? (
                    <Logo logo={project.logo_props} size={18} />
                  ) : (
                    <ProjectIcon className="h-4 w-4" />
                  )}
                  {project?.name}
                </div>
              );
            },
            meta: {
              export: {
                key: columnsLabels["project__name"],
                value: (row) => row.original.project__name?.toString() ?? "",
              },
            },
          }
        : {
            accessorKey: "display_name",
            header: () => <div className="text-left">{columnsLabels["display_name"]}</div>,
            cell: ({ row }: { row: Row<WorkItemInsightColumns> }) => (
              <div className="text-left">
                <div className="flex items-center gap-2">
                  {row.original.avatar_url && row.original.avatar_url !== "" ? (
                    <Avatar
                      name={row.original.display_name}
                      src={getFileURL(row.original.avatar_url)}
                      size={24}
                      shape="circle"
                    />
                  ) : (
                    <div className="flex h-4 w-4 flex-shrink-0 items-center justify-center overflow-hidden rounded-full bg-layer-1 capitalize">
                      {row.original.display_name ? (
                        row.original.display_name?.[0]
                      ) : (
                        <UserRound className="text-secondary" size={12} />
                      )}
                    </div>
                  )}
                  <span className="break-words text-secondary">{row.original.display_name ?? "未指派"}</span>
                </div>
              </div>
            ),
            meta: {
              export: {
                key: columnsLabels["display_name"],
                value: (row) => row.original.display_name?.toString() ?? "",
              },
            },
          },
      {
        accessorKey: "backlog_work_items",
        header: () => <div className="text-right">{columnsLabels["backlog_work_items"]}</div>,
        cell: ({ row }) => (
          <button
            type="button"
            className="block w-full text-right text-accent-primary hover:underline"
            onClick={() =>
              setDetail({
                metric: "backlog_work_items",
                title: columnsLabels["backlog_work_items"],
                projectId: row.original.project_id,
                assigneeId: row.original.assignee_id,
              })
            }
          >
            {row.original.backlog_work_items}
          </button>
        ),
        meta: {
          export: {
            key: columnsLabels["backlog_work_items"],
            value: (row) => row.original.backlog_work_items.toString(),
          },
        },
      },
      {
        accessorKey: "started_work_items",
        header: () => <div className="text-right">{columnsLabels["started_work_items"]}</div>,
        cell: ({ row }) => (
          <button
            type="button"
            className="block w-full text-right text-accent-primary hover:underline"
            onClick={() =>
              setDetail({
                metric: "started_work_items",
                title: columnsLabels["started_work_items"],
                projectId: row.original.project_id,
                assigneeId: row.original.assignee_id,
              })
            }
          >
            {row.original.started_work_items}
          </button>
        ),
        meta: {
          export: {
            key: columnsLabels["started_work_items"],
            value: (row) => row.original.started_work_items.toString(),
          },
        },
      },
      {
        accessorKey: "un_started_work_items",
        header: () => <div className="text-right">{columnsLabels["un_started_work_items"]}</div>,
        cell: ({ row }) => (
          <button
            type="button"
            className="block w-full text-right text-accent-primary hover:underline"
            onClick={() =>
              setDetail({
                metric: "un_started_work_items",
                title: columnsLabels["un_started_work_items"],
                projectId: row.original.project_id,
                assigneeId: row.original.assignee_id,
              })
            }
          >
            {row.original.un_started_work_items}
          </button>
        ),
        meta: {
          export: {
            key: columnsLabels["un_started_work_items"],
            value: (row) => row.original.un_started_work_items.toString(),
          },
        },
      },
      {
        accessorKey: "completed_work_items",
        header: () => <div className="text-right">{columnsLabels["completed_work_items"]}</div>,
        cell: ({ row }) => (
          <button
            type="button"
            className="block w-full text-right text-accent-primary hover:underline"
            onClick={() =>
              setDetail({
                metric: "completed_work_items",
                title: columnsLabels["completed_work_items"],
                projectId: row.original.project_id,
                assigneeId: row.original.assignee_id,
              })
            }
          >
            {row.original.completed_work_items}
          </button>
        ),
        meta: {
          export: {
            key: columnsLabels["completed_work_items"],
            value: (row) => row.original.completed_work_items.toString(),
          },
        },
      },
      {
        accessorKey: "cancelled_work_items",
        header: () => <div className="text-right">{columnsLabels["cancelled_work_items"]}</div>,
        cell: ({ row }) => (
          <button
            type="button"
            className="block w-full text-right text-accent-primary hover:underline"
            onClick={() =>
              setDetail({
                metric: "cancelled_work_items",
                title: columnsLabels["cancelled_work_items"],
                projectId: row.original.project_id,
                assigneeId: row.original.assignee_id,
              })
            }
          >
            {row.original.cancelled_work_items}
          </button>
        ),
        meta: {
          export: {
            key: columnsLabels["cancelled_work_items"],
            value: (row) => row.original.cancelled_work_items.toString(),
          },
        },
      },
    ],
    [columnsLabels, getProjectById, isPeekView]
  );
  return (
    <>
      <InsightTable<"work-items">
        analyticsType="work-items"
        data={workItemsData}
        isLoading={isLoading}
        columns={columns}
        columnsLabels={columnsLabels}
        headerText={isPeekView ? t("common.assignee") : t("common.projects")}
        onExport={(rows) => workItemsData && exportCSV(rows, columns, workspaceSlug)}
      />
      {detail && (
        <AnalyticsDetails
          title={detail.title}
          metric={detail.metric}
          isPeekView={isPeekView}
          filters={{
            ...(detail.projectId
              ? { project_ids: detail.projectId }
              : selectedProjects?.length
                ? { project_ids: selectedProjects.join(",") }
                : {}),
            ...(isPeekView ? (detail.assigneeId ? { assignee_id: detail.assigneeId } : { unassigned: "true" }) : {}),
            ...(selectedCycle ? { cycle_id: selectedCycle } : {}),
            ...(selectedModule ? { module_id: selectedModule } : {}),
          }}
          onClose={() => setDetail(undefined)}
        />
      )}
    </>
  );
});

export default WorkItemsInsightTable;
