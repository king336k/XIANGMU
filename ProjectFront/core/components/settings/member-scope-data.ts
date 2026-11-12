// SPDX-License-Identifier: AGPL-3.0-only
export type ScopeRow = {
  kind: "workspace" | "project";
  id: string;
  name: string;
  slug?: string;
  identifier?: string;
  workspace_id?: string;
  workspace_name?: string;
  inherited_access?: boolean;
  project_count?: number;
  access_role: number;
  roles: string[];
  inherited_roles?: string[];
  revision: string;
};
export type ScopeChange = {
  kind: ScopeRow["kind"];
  id: string;
  access_role: number;
  roles?: string[];
  expected_revision: string;
  workspace_id?: string;
};
export type ScopeChanges = Record<string, ScopeChange>;
const sameRoles = (left: string[], right: string[]) =>
  left.length === right.length && left.every((value) => right.includes(value));
export const scopeKey = (row: Pick<ScopeRow, "kind" | "id">) => `${row.kind}:${row.id}`;
export function updateScopeChanges(
  pending: ScopeChanges,
  row: ScopeRow,
  accessRole: number,
  roles = row.roles
): ScopeChanges {
  if (accessRole < 15) roles = [];
  const next = { ...pending };
  const key = scopeKey(row);
  if (accessRole === row.access_role && sameRoles(roles, row.roles)) delete next[key];
  else
    next[key] = {
      kind: row.kind,
      id: row.id,
      access_role: accessRole,
      expected_revision: pending[key]?.expected_revision || row.revision,
      roles: [...roles],
      ...(row.kind === "project" ? { workspace_id: row.workspace_id } : {}),
    };
  if (row.kind === "workspace" && accessRole === 0) {
    for (const [otherKey, change] of Object.entries(next)) {
      if (change.kind === "project" && change.workspace_id === row.id) delete next[otherKey];
    }
  }
  return next;
}
export const buildScopePayload = (pending: ScopeChanges) => ({
  changes: Object.values(pending).map(({ workspace_id: _workspaceId, ...change }) => change),
});
