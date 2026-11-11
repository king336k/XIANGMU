// SPDX-License-Identifier: AGPL-3.0-only
import { Navigate, useParams, useLocation } from "react-router";
export default function ProjectRoot() {
  const { workspaceSlug, projectId } = useParams();
  const location = useLocation();
  return (
    <Navigate
      replace
      to={`/${workspaceSlug}/p/${encodeURIComponent(projectId || "")}/issues/${location.search}${location.hash}`}
    />
  );
}
