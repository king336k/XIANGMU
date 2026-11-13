// SPDX-License-Identifier: AGPL-3.0-only
import { useLocation, useSearchParams } from "react-router";
import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
export function statisticsReturnPath(value: string | null, current: string) {
  if (
    !value ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    Array.from(value).some((character) => character.charCodeAt(0) < 32)
  )
    return null;
  const target = new URL(value, "https://local.invalid");
  if (target.origin !== "https://local.invalid" || target.pathname.split("/")[1] !== current.split("/")[1]) return null;
  target.searchParams.delete("return_to");
  return target.pathname + target.search + target.hash;
}
export function StatisticsReturnLink() {
  const [params] = useSearchParams(),
    location = useLocation();
  const target = statisticsReturnPath(params.get("return_to"), location.pathname);
  return target ? (
    <div className="shrink-0 border-b border-subtle bg-surface-1 px-4 py-2 text-12">
      <Link to={target} className="text-accent-primary hover:underline">
        ← 返回统计
      </Link>
    </div>
  ) : null;
}
