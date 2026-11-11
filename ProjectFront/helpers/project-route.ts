// SPDX-License-Identifier: AGPL-3.0-only
// Project codes are presentation paths; services continue to receive immutable IDs.
type RouteProject = { id: string; identifier: string; workspace: string | { id: string } };
export function resolveProjectRouteParams<T extends Record<string, string | undefined>>(
  params: T,
  projects: RouteProject[],
  workspaceId?: string
) {
  const token = params.projectId || params.projectCode;
  if (!token) return params;
  if (/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(token)) return { ...params, projectId: token };
  const candidates = projects.filter(
    (row) =>
      (typeof row.workspace === "string" ? row.workspace : row.workspace.id) === workspaceId &&
      (row.id === token || row.identifier.toLowerCase() === token.toLowerCase())
  );
  return { ...params, projectId: candidates.length === 1 ? candidates[0].id : undefined };
}
export function shortProjectPath(path: string, projects: RouteProject[], workspaceId?: string) {
  const match = path.match(/^\/([^/]+)\/(settings\/)?projects\/([^/?#]+)(.*)$/);
  if (!match) return path;
  const project = projects.find(
    (row) =>
      (typeof row.workspace === "string" ? row.workspace : row.workspace.id) === workspaceId && row.id === match[3]
  );
  if (!project) return path;
  return `/${match[1]}/p/${encodeURIComponent(project.identifier)}${match[2] ? "/settings" : ""}${match[4] || "/"}`;
}
export function internalProjectPath(path: string, projects: RouteProject[], workspaceId?: string) {
  const match = path.match(/^\/([^/]+)\/p\/([^/?#]+)(.*)$/);
  if (!match) return path;
  let code: string;
  try {
    code = decodeURIComponent(match[2]);
  } catch {
    return path;
  }
  const candidates = projects.filter(
    (row) =>
      (typeof row.workspace === "string" ? row.workspace : row.workspace.id) === workspaceId &&
      row.identifier.toLowerCase() === code.toLowerCase()
  );
  if (candidates.length !== 1) return path;
  const tail = match[3] || "/",
    settings = /^\/settings(?:[/?#]|$)/.test(tail);
  return `/${match[1]}/${settings ? "settings/" : ""}projects/${candidates[0].id}${settings ? tail.slice(9) || "/" : tail}`;
}
