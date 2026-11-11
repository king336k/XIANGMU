// SPDX-License-Identifier: AGPL-3.0-only
export function canManageSettings(
  nativeAllowed: boolean,
  administrator: unknown,
  workspaceRole?: number,
  projectRole?: number
): boolean {
  return (
    nativeAllowed ||
    (administrator === true && Number(workspaceRole) >= 15 && (projectRole === undefined || Number(projectRole) >= 15))
  );
}
