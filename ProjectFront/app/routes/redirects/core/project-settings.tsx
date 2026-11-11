/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { redirect } from "react-router";
import type { Route } from "./+types/project-settings";

export const clientLoader = ({ params, request }: Route.ClientLoaderArgs) => {
  const { workspaceSlug, projectId } = params;
  const splat = params["*"] || "";
  const destination = `/${workspaceSlug}/settings/projects/${projectId}${splat ? `/${splat}` : ""}/`;
  const url = new URL(request.url);
  const browserHash =
    typeof window !== "undefined" && window.location.pathname === url.pathname && window.location.search === url.search
      ? window.location.hash
      : "";
  const hash = url.hash || browserHash;
  throw redirect(`${destination}${url.search}${hash}`);
};

export default function ProjectSettings() {
  return null;
}
