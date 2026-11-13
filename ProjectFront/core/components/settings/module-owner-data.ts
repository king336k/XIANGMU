// SPDX-License-Identifier: AGPL-3.0-only
import type { ScopeChanges } from "./member-scope-data";
export type ModuleBinding = { workspace_id: string; module_key: string; module_name?: string; eligible?: boolean };
export type ModuleOption = { key: string; name: string; user_id?: string | null; display_name?: string };
export type ModuleWorkspace = { workspace_id: string; workspace_name: string; modules: ModuleOption[] };
export function technicianWorkspaces(mode: "none" | "workspace" | "project", pending: ScopeChanges): string[] {
  if (mode === "none") return [];
  return [
    ...new Set(
      Object.values(pending)
        .filter((row) => row.access_role >= 15 && row.roles?.includes("TECHNICIAN"))
        .map((row) => (mode === "workspace" ? row.id : row.workspace_id))
        .filter((id): id is string => !!id)
    ),
  ];
}
export const validModuleBindings = (bindings: ModuleBinding[], workspaces: string[]) =>
  bindings.filter((row) => workspaces.includes(row.workspace_id));
export function toggleModuleOwner(bindings: ModuleBinding[], workspace: string, module: string, selected: boolean) {
  const exists = bindings.some((row) => row.workspace_id === workspace && row.module_key === module);
  if (!selected) return bindings.filter((row) => row.workspace_id !== workspace || row.module_key !== module);
  return exists ? bindings : [...bindings, { workspace_id: workspace, module_key: module }];
}
