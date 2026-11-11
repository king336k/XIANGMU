// SPDX-License-Identifier: AGPL-3.0-only
export type CaseOption = {
  code?: string;
  number?: number;
  id: string;
  title: string;
  module: string;
  priority: string;
  version: number;
  requirement_title?: string | null;
};

export function mergeCaseSelection<T extends { id: string }>(current: T[], rows: T[], checked: boolean): T[] {
  const ids = new Set(rows.map((row) => row.id));
  if (!checked) return current.filter((row) => !ids.has(row.id));
  const merged = new Map(current.map((row) => [row.id, row]));
  for (const row of rows) if (!merged.has(row.id)) merged.set(row.id, row);
  if (merged.size > 500) throw new Error("最多选择500条用例，请缩小范围或分成多个计划/用例集。");
  return [...merged.values()];
}
