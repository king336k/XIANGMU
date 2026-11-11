/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { startTransition, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HydratedRouter } from "react-router/dom";

import polyfills from "@/lib/polyfills";
import { isStaleAssetErrorMessage, recoverFromStaleAsset } from "@/lib/stale-asset-error";

void polyfills;

// Production-only: in dev these errors come from the dev server itself (restarts,
// stale optimized deps) and auto-reloading would mask them.
if (import.meta.env.PROD) {
  window.addEventListener("vite:preloadError", (event) => {
    if (recoverFromStaleAsset()) event.preventDefault();
  });

  window.addEventListener("error", (event) => {
    if (isStaleAssetErrorMessage(event.message || "")) recoverFromStaleAsset();
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason instanceof Error ? event.reason.message : String(event.reason ?? "");
    if (isStaleAssetErrorMessage(reason)) recoverFromStaleAsset();
  });
}

startTransition(() => {
  // This deployment uses React Router's static SPA mode (ssr: false).
  // Keep the static document shell outside React's client mount boundary.
  const container = document.getElementById("platform-root");
  if (!container) throw new Error("应用容器未加载，请刷新页面。");
  createRoot(container).render(
    <StrictMode>
      <HydratedRouter />
    </StrictMode>
  );
});
