// SPDX-License-Identifier: AGPL-3.0-only
// Presentation paths only. API callers continue to use the resolved immutable project ID.
export function movedSettingsPath(
  workspace: string,
  projectCode: string,
  projectId: string,
  tab: string,
  params: URLSearchParams
) {
  const next = new URLSearchParams(params);
  next.delete("tab");
  let path: string;
  if (tab === "roles" || tab === "integrations") {
    path = `/${workspace}/settings/${tab === "roles" ? "members" : "sources"}/`;
    next.set("project", projectId);
  } else if (tab === "settings") {
    path = `/${workspace}/settings/models/`;
    next.set("project", projectId);
  } else if (tab === "releases") {
    path = `/${workspace}/p/${encodeURIComponent(projectCode)}/versions/`;
    next.set("tab", "acceptance");
  } else return undefined;
  return `${path}${next.size ? `?${next}` : ""}`;
}
