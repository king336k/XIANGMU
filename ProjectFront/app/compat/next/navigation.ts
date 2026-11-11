/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useMemo } from "react";
import { useLocation, useNavigate, useParams as useParamsRR, useSearchParams as useSearchParamsRR } from "react-router";
import { ensureTrailingSlash } from "./helper";
import { useProject } from "@/hooks/store/use-project";
import { useWorkspace } from "@/hooks/store/use-workspace";
import { internalProjectPath, shortProjectPath, resolveProjectRouteParams } from "@/helpers/project-route";

export function useProjectRoutePaths() {
  const params = useParamsRR();
  const { projectMap } = useProject();
  const { getWorkspaceBySlug } = useWorkspace();
  const workspaceId = getWorkspaceBySlug(params.workspaceSlug || "")?.id;
  const resolved = resolveProjectRouteParams(params, Object.values(projectMap), workspaceId);
  const resolvedParams = useMemo(() => resolved, [params, resolved.projectId]);
  const shortPath = useCallback(
    (path: string) => shortProjectPath(path, Object.values(projectMap), workspaceId),
    [projectMap, workspaceId]
  );
  const internalPath = useCallback(
    (path: string) => internalProjectPath(path, Object.values(projectMap), workspaceId),
    [projectMap, workspaceId]
  );
  return { params: resolvedParams, shortPath, internalPath };
}

export function useRouter() {
  const navigate = useNavigate();
  const { shortPath } = useProjectRoutePaths();
  return useMemo(
    () => ({
      push: (to: string) => {
        // Defer navigation to avoid state updates during render
        setTimeout(() => navigate(ensureTrailingSlash(shortPath(to))), 0);
      },
      replace: (to: string) => {
        // Defer navigation to avoid state updates during render
        setTimeout(() => navigate(ensureTrailingSlash(shortPath(to)), { replace: true }), 0);
      },
      back: () => {
        setTimeout(() => navigate(-1), 0);
      },
      forward: () => {
        setTimeout(() => navigate(1), 0);
      },
      refresh: () => {
        location.reload();
      },
      prefetch: async (_to: string) => {
        // no-op in this shim
      },
    }),
    [navigate, shortPath]
  );
}

export function usePathname(): string {
  const { pathname } = useLocation();
  return useProjectRoutePaths().internalPath(pathname);
}

export function useSearchParams(): URLSearchParams {
  const [searchParams] = useSearchParamsRR();
  return searchParams;
}

export function useParams() {
  return useProjectRoutePaths().params;
}
