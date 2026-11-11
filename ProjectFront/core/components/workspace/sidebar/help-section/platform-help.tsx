import { ProjectRouteLink as Link } from "@/components/common/project-route-link";
import { useResolvedProjectParams } from "@/hooks/use-resolved-project-params";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { movedSettingsPath } from "@/components/settings/management-paths";

import { Search } from "lucide-react";
import { Modal, fieldClass } from "@/components/quality/shared";
import { findGuideTopics, platformGuide } from "./platform-guide";
import { GuideScreenshots } from "./guide-screenshots";

export function PlatformHelp({ onClose }: { onClose: () => void }) {
  const { workspaceSlug, projectId } = useResolvedProjectParams();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("start");
  const topics = findGuideTopics(query);
  const current = topics.find((topic) => topic.id === selected) ?? topics[0];
  return (
    <Modal title="平台使用文档" width="wide" onClose={onClose}>
      <p className="text-13 text-secondary">项目管理平台使用指南</p>
      <label className="flex items-center gap-2">
        <Search aria-hidden="true" className="size-4 shrink-0 text-secondary" />
        <span className="sr-only">搜索使用文档</span>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className={fieldClass}
          placeholder="搜索需求、测试、日志、角色或模型配置…"
        />
      </label>
      <div className="grid min-w-0 gap-5 md:grid-cols-[12rem_minmax(0,1fr)]">
        <nav aria-label="使用文档目录" className="flex flex-wrap content-start gap-1 md:flex-col">
          {topics.map((topic) => (
            <button
              type="button"
              key={topic.id}
              aria-current={current?.id === topic.id ? "page" : undefined}
              onClick={() => setSelected(topic.id)}
              className={`rounded-md px-3 py-2 text-left text-13 ${current?.id === topic.id ? "bg-layer-1 font-medium text-primary" : "text-secondary hover:bg-layer-1"}`}
            >
              {topic.title}
            </button>
          ))}
          <p className="w-full px-3 pt-3 text-11 text-tertiary">共 {platformGuide.length} 个主题</p>
        </nav>
        {current ? (
          <article aria-label={current.title} className="min-w-0 space-y-4 break-words">
            <div>
              <h3 className="text-18 font-semibold">{current.title}</h3>
              <p className="mt-2 text-13 text-secondary">{current.summary}</p>
            </div>
            <GuideScreenshots images={current.screenshots} />
            {current.paragraphs.map((paragraph) => (
              <p key={paragraph} className="text-13 leading-6">
                {paragraph}
              </p>
            ))}
            <h4 className="text-14 font-medium">操作顺序</h4>
            <ol className="list-decimal space-y-2 pl-5 text-13 leading-6">
              {current.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
            {workspaceSlug && projectId ? (
              <div className="flex flex-wrap gap-3 border-t border-subtle pt-4">
                {current.links.map((item) => (
                  <Link
                    key={item.path}
                    to={
                      item.path.includes("?tab=roles") ||
                      item.path.includes("?tab=integrations") ||
                      item.path.includes("?tab=settings")
                        ? movedSettingsPath(
                            String(workspaceSlug),
                            String(projectId),
                            String(projectId),
                            new URLSearchParams(item.path.split("?")[1]).get("tab") || "",
                            new URLSearchParams(item.path.split("?")[1])
                          ) || `/${workspaceSlug}/settings/members/?project=${projectId}`
                        : `/${workspaceSlug}/projects/${projectId}${item.path}`
                    }
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
            未找到相关内容，请尝试“日志”“用例”或“模型”等关键词。
          </p>
        )}
      </div>
    </Modal>
  );
}
