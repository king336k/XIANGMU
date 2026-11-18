// SPDX-License-Identifier: AGPL-3.0-only
import { Navigate, useLocation, useParams } from "react-router";

export default function RemoteDiagnosticsPage() {
  const { workspaceSlug } = useParams();
  const { search } = useLocation();
  return <Navigate replace to={`/${workspaceSlug}/remote-diagnostics/${search}`} />;
}
