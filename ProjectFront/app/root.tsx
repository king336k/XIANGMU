/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ReactNode } from "react";
import Script from "next/script";
import { Links, Meta, Outlet, Scripts } from "react-router";
import type { LinksFunction } from "react-router";
import { ThemeProvider } from "next-themes";
// plane imports
import { SITE_DESCRIPTION, SITE_NAME } from "@plane/constants";
import { cn } from "@plane/utils";
// types
// assets
import favicon16 from "@/app/assets/favicon/favicon-16x16.png?url";
import favicon32 from "@/app/assets/favicon/favicon-32x32.png?url";
import faviconIco from "@/app/assets/favicon/favicon.ico?url";
import icon180 from "@/app/assets/icons/icon-180x180.png?url";
import icon512 from "@/app/assets/icons/icon-512x512.png?url";
import ogImage from "@/app/assets/og-image.png?url";
import globalStyles from "@/styles/globals.css?url";
import type { Route } from "./+types/root";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
// lib
import { isStaleAssetError, recoverFromStaleAsset } from "@/lib/stale-asset-error";
// local
import { CustomErrorComponent } from "./error";
import { AppProvider } from "./provider";
// fonts
import interFontStyles from "@fontsource-variable/inter/index.css?url";
import interVariableWoff2 from "@fontsource-variable/inter/files/inter-latin-wght-normal.woff2?url";
import symbolFontStyles from "@fontsource/material-symbols-rounded/index.css?url";
import monoFontStyles from "@fontsource/ibm-plex-mono/index.css?url";
import terminalStyles from "@xterm/xterm/css/xterm.css?url";

const APP_TITLE = "项目管理平台";

export const links: LinksFunction = () => [
  ...[interFontStyles, symbolFontStyles, monoFontStyles, terminalStyles].map((href) => ({ rel: "stylesheet", href })),
  { rel: "icon", type: "image/png", sizes: "32x32", href: `${favicon32}?brand=engram-20261107` },
  { rel: "icon", type: "image/png", sizes: "16x16", href: `${favicon16}?brand=engram-20261107` },
  { rel: "shortcut icon", href: `${faviconIco}?brand=engram-20261107` },
  { rel: "manifest", href: "/site.webmanifest.json" },
  { rel: "apple-touch-icon", href: icon512 },
  { rel: "apple-touch-icon", sizes: "180x180", href: icon180 },
  { rel: "apple-touch-icon", sizes: "512x512", href: icon512 },
  { rel: "manifest", href: "/manifest.json" },
  { rel: "stylesheet", href: globalStyles },
  {
    rel: "preload",
    href: interVariableWoff2,
    as: "font",
    type: "font/woff2",
    crossOrigin: "anonymous",
  },
];

export function Layout({ children }: { children: ReactNode }) {
  const isSessionRecorderEnabled = parseInt(process.env.VITE_ENABLE_SESSION_RECORDER || "0");
  const application = (
    <>
      <ThemeProvider themes={["light", "dark", "light-contrast", "dark-contrast", "custom"]} defaultTheme="system">
        {children}
      </ThemeProvider>
      {!!isSessionRecorderEnabled && process.env.VITE_SESSION_RECORDER_KEY && (
        <Script id="clarity-tracking">
          {`(function(c,l,a,r,i,t,y){
            c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
            t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
            y=l.getElementsByTagName(r)[0];if(y){y.parentNode.insertBefore(t,y);}
        })(window, document, "clarity", "script", "${process.env.VITE_SESSION_RECORDER_KEY}");`}
        </Script>
      )}
    </>
  );
  // Static SPA builds own the document shell; the browser mounts only the application subtree.
  if (typeof window !== "undefined") return application;
  return (
    <html lang="zh-CN">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="theme-color" content="#fff" />
        <meta name="application-name" content={SITE_NAME} />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content={SITE_NAME} />
        <meta name="format-detection" content="telephone=no" />
        <meta name="mobile-web-app-capable" content="yes" />
        <Meta />
        <Links />
      </head>
      <body>
        <div id="context-menu-portal" />
        <div id="editor-portal" />
        <div id="platform-root">{application}</div>
        <Scripts />
      </body>
    </html>
  );
}

export const meta: Route.MetaFunction = () => [
  { title: APP_TITLE },
  { name: "description", content: SITE_DESCRIPTION },
  { property: "og:title", content: APP_TITLE },
  {
    property: "og:description",
    content: "管理需求、任务、缺陷、测试与项目知识。",
  },
  { property: "og:image", content: ogImage },
  { property: "og:image:width", content: "1200" },
  { property: "og:image:height", content: "630" },
  { property: "og:image:alt", content: "项目管理平台" },
  {
    name: "keywords",
    content: "需求管理,任务管理,缺陷管理,测试管理,项目知识,研发协作",
  },
  { name: "twitter:card", content: "summary_large_image" },
  { name: "twitter:image", content: ogImage },
  { name: "twitter:image:width", content: "1200" },
  { name: "twitter:image:height", content: "630" },
  { name: "twitter:image:alt", content: "项目管理平台" },
];

export default function Root() {
  return (
    <AppProvider>
      <div className={cn("relative flex h-screen w-full flex-col overflow-hidden bg-canvas", "desktop-app-container")}>
        <main className="relative h-full w-full overflow-hidden">
          <Outlet />
        </main>
      </div>
    </AppProvider>
  );
}

export function HydrateFallback() {
  // The static document and first browser render must have identical markup.
  return (
    <div className="relative flex h-screen w-full items-center justify-center bg-canvas">
      <LogoSpinner />
    </div>
  );
}

export function ErrorBoundary({ error }: Route.ErrorBoundaryProps) {
  // A stale chunk failure surfaces here as React Router's own wrapper error
  // (the failed dynamic import itself never reaches a window event) — recover
  // the same way entry.client.tsx does instead of just showing the error page.
  if (import.meta.env.PROD && isStaleAssetError(error)) recoverFromStaleAsset();

  return <CustomErrorComponent error={error} />;
}
