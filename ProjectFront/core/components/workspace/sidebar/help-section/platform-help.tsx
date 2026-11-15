import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { useResolvedProjectParams } from "@/hooks/use-resolved-project-params";
// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import { movedSettingsPath } from "@/components/settings/management-paths";
import { Search } from "lucide-react";
import { Modal, fieldClass } from "@/components/quality/shared";
import { findGuideTopics, guideUpdatedAt, platformGuide } from "./platform-guide";
import type { GuideSection } from "./platform-guide";
import { GuideScreenshots } from "./guide-screenshots";

const sections = [
  { id: "all", label: "全部内容" },
  { id: "common", label: "公共操作" },
  { id: "roles", label: "角色指南" },
] as const;

export function guideLinkPath(workspace: string, project: string, path: string) {
  if (path.startsWith("/settings/")) {
    return `/${workspace}${path}?${new URLSearchParams({ project })}`;
  }
  const params = new URLSearchParams(path.split("?")[1]);
  return (
    movedSettingsPath(workspace, project, project, params.get("tab") || "", params) ||
    `/${workspace}/projects/${project}${path}`
  );
}

export function PlatformHelp({ onClose }: { onClose: () => void }) {
  const { workspaceSlug, projectId } = useResolvedProjectParams();
  const [query, setQuery] = useState("");
  const [section, setSection] = useState<GuideSection>("all");
  const [selected, setSelected] = useState("start");
  const topics = findGuideTopics(query, section);
  const current = topics.find((topic) => topic.id === selected) ?? topics[0];
  const contentRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    contentRef.current?.closest("dialog")?.scrollTo({ top: 0 });
  }, [current?.id, section]);
  const openTopic = (id: string) => {
    setQuery("");
    setSection("all");
    setSelected(id);
  };
  return (
    <Modal title="平台使用文档" width="wide" onClose={onClose}>
      <div ref={contentRef} className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="text-14 font-medium">先了解公共操作，再按角色完成自己的工作</p>
          <p className="text-12 text-secondary">操作步骤、交接关系与常见受阻原因，按当前平台功能整理。</p>
        </div>
        <span className="text-11 text-tertiary">更新于 {guideUpdatedAt}</span>
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="使用文档分类">
        {sections.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-pressed={section === item.id}
            onClick={() => setSection(item.id)}
            className={`focus-visible:outline-accent-primary rounded-md border px-3 py-2 text-13 focus-visible:outline-2 ${section === item.id ? "border-accent-subtle bg-accent-subtle font-medium text-accent-primary" : "border-subtle text-secondary hover:bg-layer-1"}`}
          >
            {item.label}
            <span className="ml-2 text-11">
              {platformGuide.filter((topic) => item.id === "all" || topic.section === item.id).length}
            </span>
          </button>
        ))}
      </div>
      <label className="flex items-center gap-2">
        <Search aria-hidden="true" className="size-4 shrink-0 text-secondary" />
        <span className="sr-only">搜索使用文档</span>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className={fieldClass}
          placeholder="搜索角色、按钮、流程或提示，例如：技术员、安排测试、阶段图…"
        />
      </label>
      <div className="grid min-w-0 gap-5 md:grid-cols-[12rem_minmax(0,1fr)]">
        <nav aria-label="使用文档目录" className="min-w-0 space-y-4">
          {sections
            .filter((item) => item.id !== "all")
            .map((group) => {
              const entries = topics.filter((topic) => topic.section === group.id);
              return entries.length ? (
                <section key={group.id} aria-label={group.label}>
                  <h3 className="px-3 pb-2 text-12 font-semibold text-secondary">{group.label}</h3>
                  <div className="flex flex-wrap gap-1 md:flex-col">
                    {entries.map((topic) => (
                      <button
                        type="button"
                        key={topic.id}
                        aria-current={current?.id === topic.id ? "page" : undefined}
                        onClick={() => setSelected(topic.id)}
                        className={`focus-visible:outline-accent-primary rounded-md px-3 py-2 text-left text-13 focus-visible:outline-2 ${current?.id === topic.id ? "bg-layer-1 font-medium text-primary" : "text-secondary hover:bg-layer-1"}`}
                      >
                        {topic.title}
                      </button>
                    ))}
                  </div>
                </section>
              ) : null;
            })}
          <p className="px-3 text-11 text-tertiary" role="status">
            找到 {topics.length} / {platformGuide.length} 个主题
          </p>
        </nav>
        {current ? (
          <article aria-label={current.title} className="min-w-0 space-y-5 break-words">
            <div className="space-y-2 border-b border-subtle pb-4">
              <p className="text-11 text-accent-primary">{current.section === "common" ? "公共操作" : "角色指南"}</p>
              <h3 className="text-18 font-semibold">{current.title}</h3>
              <p className="text-13 leading-6 text-secondary">{current.summary}</p>
            </div>
            {current.paragraphs.map((paragraph) => (
              <p key={paragraph} className="text-13 leading-6">
                {paragraph}
              </p>
            ))}
            <GuideScreenshots key={current.id} images={current.screenshots} />
            <section aria-label="操作顺序" className="space-y-3">
              <h4 className="text-14 font-medium">操作顺序</h4>
              <ol className="list-decimal space-y-2 pl-5 text-13 leading-6">
                {current.steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            </section>
            <aside aria-label="完成前核对" className="space-y-2 rounded-md border border-subtle bg-layer-1 p-4">
              <h4 className="text-14 font-medium">完成前核对</h4>
              <ul className="list-disc space-y-2 pl-4 text-13 leading-6">
                {current.checkpoints.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </aside>
            {!!current.related.length && (
              <section aria-label="继续阅读" className="space-y-2 border-t border-subtle pt-4">
                <h4 className="text-14 font-medium">继续阅读</h4>
                <div className="flex flex-wrap gap-2">
                  {current.related.map((id) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => openTopic(id)}
                      className="rounded border border-subtle px-3 py-2 text-12 text-accent-primary hover:bg-layer-1"
                    >
                      {platformGuide.find((topic) => topic.id === id)?.title} →
                    </button>
                  ))}
                </div>
              </section>
            )}
            {workspaceSlug && projectId ? (
              <div className="flex flex-wrap gap-3 border-t border-subtle pt-4">
                {current.links.map((item) => (
                  <Link
                    key={item.path}
                    to={guideLinkPath(String(workspaceSlug), String(projectId), item.path)}
                    onClick={onClose}
                    className="rounded-md border border-subtle px-3 py-2 text-13 text-accent-primary hover:bg-layer-1"
                  >
                    {item.label} →
                  </Link>
                ))}
              </div>
            ) : (
              <p className="border-t border-subtle pt-4 text-12 text-secondary">
                进入具体项目后，可从这里直接打开对应功能。操作入口会根据你的权限显示。
              </p>
            )}
          </article>
        ) : (
          <p role="status" className="py-8 text-13 text-secondary">
            未找到相关内容。试试“安排测试”“待分诊”或其他分类。
          </p>
        )}
      </div>
    </Modal>
  );
}
