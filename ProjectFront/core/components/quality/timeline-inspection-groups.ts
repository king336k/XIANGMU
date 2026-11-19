// SPDX-License-Identifier: AGPL-3.0-only
import type { RemoteProcess } from "./types";
export function groupSuccessfulInspections<T>(
  rows: T[],
  processOf: (row: T) => RemoteProcess | null | undefined
): { grouped: boolean; items: T[] }[] {
  const groups: { runId: string | null; items: T[] }[] = [];
  for (const row of rows) {
    const process = processOf(row);
    const eligible =
      process?.stage === "inspect" &&
      process.command?.status === "done" &&
      process.command.ok === true &&
      process.command.exit_code === 0 &&
      !!process.run_id;
    const runId = eligible ? process.run_id! : null;
    const previous = groups.at(-1);
    if (runId && previous?.runId === runId) previous.items.push(row);
    else groups.push({ runId, items: [row] });
  }
  return groups.map((group) => ({ grouped: group.runId !== null && group.items.length >= 2, items: group.items }));
}
