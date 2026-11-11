import { ProjectRouteLink as Link } from "@/components/common/project-route-link";

import { cn } from "@plane/utils";

type Props = {
  workspaceSlug: string;
  projectId: string;
  active: "pages" | "knowledge" | "assistant";
};

export function DocumentWorkspaceNav({ workspaceSlug, projectId, active }: Props) {
  const projectPath = `/${workspaceSlug}/projects/${projectId}`;
  const items = [
    { key: "pages", label: "项目文档", href: `${projectPath}/pages/` },
    { key: "knowledge", label: "知识库", href: `${projectPath}/knowledge?tab=search` },
    { key: "assistant", label: "知识问答", href: `${projectPath}/knowledge?tab=assistant` },
  ];

  return (
    <nav
      aria-label="文档与知识"
      className="flex shrink-0 flex-wrap items-center gap-2 border-b border-subtle px-5 py-3"
    >
      {items.map((item) => (
        <Link
          key={item.key}
          to={item.href}
          aria-current={active === item.key ? "page" : undefined}
          className={cn("rounded-md px-3 py-1.5 text-13 font-medium text-secondary hover:bg-layer-1", {
            "bg-accent-primary/10 text-accent-primary": active === item.key,
          })}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
