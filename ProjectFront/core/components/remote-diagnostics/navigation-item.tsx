// SPDX-License-Identifier: AGPL-3.0-only
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { Monitor } from "lucide-react";
import useSWR from "swr";
import { qualityApi } from "@/components/quality/api";
import { SidebarNavItem } from "@/components/sidebar/sidebar-navigation";
import { useAppTheme } from "@/hooks/store/use-app-theme";

export function RemoteDiagnosticsNavigationItem() {
  const { workspaceSlug } = useParams();
  const pathname = usePathname();
  const { toggleSidebar, toggleExtendedSidebar } = useAppTheme();
  const { data } = useSWR("/api/quality-auth/accounts/?per_page=1", (url: string) =>
    qualityApi.read<{ can_manage_administrators?: boolean }>(url)
  );
  if (!workspaceSlug || data?.can_manage_administrators !== true) return null;
  const href = `/${workspaceSlug}/remote-diagnostics/`;
  const active = pathname.replace(/\/$/, "") === href.replace(/\/$/, "");
  return (
    <SidebarNavItem isActive={active}>
      <Link
        href={href}
        aria-current={active ? "page" : undefined}
        className="min-w-0 flex-1"
        onClick={() => {
          if (window.innerWidth < 768) toggleSidebar();
          toggleExtendedSidebar(false);
        }}
      >
        <div className="flex items-center gap-1.5 py-[1px]">
          <Monitor className="size-4 shrink-0" aria-hidden="true" />
          <p className="text-13 leading-5 font-medium">远程诊断</p>
        </div>
      </Link>
    </SidebarNavItem>
  );
}
