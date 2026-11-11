// SPDX-License-Identifier: AGPL-3.0-only
export function profileSidebarWidth(startWidth: number, startX: number, currentX: number, availableWidth: number) {
  const width = Number.isFinite(startWidth) ? startWidth : 300;
  const available = Number.isFinite(availableWidth) ? availableWidth : 1200;
  const max = Math.max(240, Math.min(440, available - 480));
  return Math.round(Math.max(240, Math.min(max, width + startX - currentX)));
}
