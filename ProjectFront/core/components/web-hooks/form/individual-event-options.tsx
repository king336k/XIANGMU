/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { Control } from "react-hook-form";
import { Controller } from "react-hook-form";
import type { IWebhook } from "@plane/types";
import { Checkbox } from "@plane/ui";

export const INDIVIDUAL_WEBHOOK_OPTIONS: {
  key: keyof IWebhook;
  label: string;
  description: string;
}[] = [
  {
    key: "project",
    label: "项目",
    description: "项目创建、更新或删除时触发",
  },
  {
    key: "cycle",
    label: "迭代",
    description: "迭代创建、更新或删除时触发",
  },
  {
    key: "issue",
    label: "工作项",
    description: "工作项创建、更新、删除或加入迭代、模块时触发",
  },
  {
    key: "module",
    label: "模块",
    description: "模块创建、更新或删除时触发",
  },
  {
    key: "issue_comment",
    label: "工作项评论",
    description: "评论发布、更新或删除时触发",
  },
];

type Props = {
  control: Control<IWebhook, any>;
};

export function WebhookIndividualEventOptions({ control }: Props) {
  return (
    <div className="grid grid-cols-1 gap-x-4 gap-y-8 px-6 lg:grid-cols-2">
      {INDIVIDUAL_WEBHOOK_OPTIONS.map((option) => (
        <Controller
          key={option.key}
          control={control}
          name={option.key}
          render={({ field: { onChange, value } }) => (
            <div>
              <div className="flex items-center gap-2">
                <Checkbox id={option.key} onChange={() => onChange(!value)} checked={value === true} />
                <label className="text-13" htmlFor={option.key}>
                  {option.label}
                </label>
              </div>
              <p className="mt-0.5 ml-6 text-11 text-tertiary">{option.description}</p>
            </div>
          )}
        />
      ))}
    </div>
  );
}
