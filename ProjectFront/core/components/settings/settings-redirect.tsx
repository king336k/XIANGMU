// SPDX-License-Identifier: AGPL-3.0-only
import { Navigate, useLocation, useSearchParams } from "react-router";
import { useParams } from "next/navigation";
export function SettingsRedirect({
  section,
  accounts = false,
}: {
  section: "members" | "sources";
  accounts?: boolean;
}) {
  const { workspaceSlug, projectId } = useParams();
  const [params] = useSearchParams();
  const location = useLocation();
  const next = new URLSearchParams(params);
  if (projectId) next.set("project", projectId);
  if (accounts) next.set("view", "accounts");
  return (
    <Navigate replace to={`/${workspaceSlug}/settings/${section}/${next.size ? `?${next}` : ""}${location.hash}`} />
  );
}
