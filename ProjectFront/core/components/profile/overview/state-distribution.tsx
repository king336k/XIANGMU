/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { profileStateLabels, profileWorkItemsHref } from "./links";

// plane imports
import { STATE_GROUPS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { PieChart } from "@plane/propel/charts/pie-chart";
import { EmptyStateCompact } from "@plane/propel/empty-state";
import type { IUserProfileData, IUserStateDistribution } from "@plane/types";
import { Card } from "@plane/ui";

type Props = {
  stateDistribution: IUserStateDistribution[];
  userProfile: IUserProfileData | undefined;
};

export function ProfileStateDistribution({ stateDistribution, userProfile }: Props) {
  const { t } = useTranslation();
  const { workspaceSlug, userId } = useParams();
  if (!userProfile) return null;

  return (
    <div className="flex flex-col space-y-2">
      <h3 className="text-16 font-medium">{t("profile.stats.state_distribution.title")}</h3>
      <Card className="h-full">
        {userProfile.state_distribution.length > 0 ? (
          <div className="grid h-[300px] w-full grid-cols-1 gap-x-6 md:grid-cols-2">
            <PieChart
              className="size-full"
              dataKey="value"
              margin={{
                top: 0,
                right: -10,
                bottom: 12,
                left: -10,
              }}
              data={
                userProfile.state_distribution.map((group) => ({
                  id: group.state_group,
                  key: group.state_group,
                  value: group.state_count,
                  name: profileStateLabels[group.state_group] || "其他",
                  color: STATE_GROUPS[group.state_group]?.color,
                })) ?? []
              }
              cells={userProfile.state_distribution.map((group) => ({
                key: group.state_group,
                fill: STATE_GROUPS[group.state_group]?.color,
              }))}
              showTooltip
              tooltipLabel="工作项数"
              paddingAngle={5}
              cornerRadius={4}
              innerRadius="50%"
              showLabel={false}
            />
            <div className="flex items-center">
              <div className="w-full space-y-4">
                {stateDistribution.map((group) => (
                  <Link
                    key={group.state_group}
                    href={profileWorkItemsHref(workspaceSlug, userId, "assigned", { state_group: group.state_group })}
                    className="flex items-center justify-between gap-2 rounded px-2 py-1 text-12 hover:bg-layer-1 hover:text-accent-primary"
                  >
                    <div className="flex items-center gap-1.5">
                      <div
                        className="h-2.5 w-2.5 rounded-xs"
                        style={{
                          backgroundColor:
                            STATE_GROUPS[group.state_group]?.color ?? "var(--background-color-accent-primary)",
                        }}
                      />
                      <div className="whitespace-nowrap">{profileStateLabels[group.state_group] || "其他"}</div>
                    </div>
                    <div className="font-medium tabular-nums">{group.state_count}</div>
                  </Link>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <EmptyStateCompact
            assetKey="priority"
            assetClassName="size-20"
            title={t("workspace_empty_state.your_work_by_priority.title")}
          />
        )}
      </Card>
    </div>
  );
}
