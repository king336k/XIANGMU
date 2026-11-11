// SPDX-License-Identifier: AGPL-3.0-only
type Location = { pathname: string; search: string; hash: string; state?: unknown };

export function notificationNavigation(workspaceSlug: string, location: Location) {
  const prefix = `/${workspaceSlug}/`;
  const inbox = `${prefix}notifications/`;
  const isNotification = (path: string) => path === inbox.slice(0, -1) || path.startsWith(inbox);
  const isInbox = isNotification(location.pathname);
  const state = location.state as { notificationReturnTo?: unknown } | null;
  let returnTo = `${prefix}projects/`;
  if (typeof state?.notificationReturnTo === "string") {
    try {
      const saved = new URL(state.notificationReturnTo, "https://platform.invalid");
      if (
        saved.origin === "https://platform.invalid" &&
        saved.pathname.startsWith(prefix) &&
        !isNotification(saved.pathname) &&
        !state.notificationReturnTo.includes("\\")
      )
        returnTo = saved.pathname + saved.search + saved.hash;
    } catch {
      // Invalid saved routes fall back to the current workspace's project list.
    }
  }
  return {
    isInbox,
    label: isInbox ? "返回原页面" : "通知",
    to: isInbox ? returnTo : inbox,
    state: isInbox ? undefined : { notificationReturnTo: location.pathname + location.search + location.hash },
  };
}
