// SPDX-License-Identifier: AGPL-3.0-only
const defaultNames: Record<string, string> = {
  Backlog: "待排期",
  Todo: "待开始",
  "In Progress": "进行中",
  Done: "已完成",
  Cancelled: "已取消",
  Canceled: "已取消",
  Triage: "待分拣",
};
export const displayStateName = (name: string | undefined | null) => (name ? defaultNames[name] || name : "未设置");
