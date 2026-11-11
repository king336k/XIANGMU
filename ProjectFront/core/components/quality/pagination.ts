// SPDX-License-Identifier: AGPL-3.0-only
export const PAGE_SIZES = [20, 50, 100] as const;
export function pageSize(params: URLSearchParams) {
  const value = Number(params.get("per_page"));
  return PAGE_SIZES.some((size) => size === value) ? value : 50;
}
export function pageNumbers(current: number, total: number): (number | string)[] {
  const pages = [1];
  for (let value = Math.max(2, current - 1); value <= Math.min(total - 1, current + 1); value++) pages.push(value);
  if (total > 1) pages.push(total);
  return pages.flatMap<number | string>((n, index) =>
    index && n - pages[index - 1] > 1 ? [`gap-before-${n}`, n] : [n]
  );
}

export function normalizedPageParams(params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params);
  next.set("per_page", String(pageSize(params)));
  const page = Number(params.get("page") || 1);
  next.set("page", String(Number.isInteger(page) && page > 0 ? page : 1));
  return next;
}
