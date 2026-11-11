import { useParams } from "next/navigation";
// SPDX-License-Identifier: AGPL-3.0-only
import { can, canOpenKnowledgeTab } from "@/components/quality/types";
import { useState } from "react";
import useSWR from "swr";
import { useSearchParams, Navigate, useLocation } from "react-router";
import { BookOpen, Search, Plus, RefreshCw } from "lucide-react";
import { Button } from "@plane/ui";
import { AppSidebarToggleButton } from "@/components/sidebar/sidebar-toggle-button";
import { ListFilters } from "../quality/list-filters";
import { pageSize } from "../quality/pagination";
import { PageHead } from "@/components/core/page-title";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { Empty, fieldClass, Paging } from "@/components/quality/shared";
import type { Context, Page } from "@/components/quality/types";
import type { Article, Publication } from "./types";
import { articleStatusNames } from "./types";
import { ArticleEditor } from "./article-editor";
import { ArticleDetail } from "./article-detail";
import { PublicationDetail } from "./publication-detail";
import { DocumentImportForm } from "../quality/document-import-form";
import { GovernancePanel } from "./governance-panel";
import { movedSettingsPath } from "@/components/settings/management-paths";
import { AssistantPanel } from "./assistant-panel";
import { DocumentWorkspaceNav } from "@/components/documentation/workspace-nav";

export function KnowledgeWorkbench() {
  const { workspaceSlug, projectId } = useParams();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const tab = ["search", "editorial", "assistant", "settings", "governance"].includes(params.get("tab") ?? "")
    ? params.get("tab")!
    : "search";
  const page = Math.max(1, Number(params.get("page")) || 1);
  const query = params.get("q") ?? "";
  const [queryInput, setQueryInput] = useState(query);
  const [editing, setEditing] = useState<Article | null | undefined>(undefined);
  const [importing, setImporting] = useState(false);
  const [article, setArticle] = useState<Article | null>(null);
  const [publication, setPublication] = useState<Publication | null>(null);
  const base = `/api/workspaces/${workspaceSlug}/projects/${projectId}/knowledge/`;
  const { data: context, error: contextError } = useSWR(
    `/api/workspaces/${workspaceSlug}/projects/${projectId}/quality/context/`,
    (url: string) => qualityApi.read<Context>(url)
  );
  const canReview = !!context?.can_review_knowledge;
  const canEdit = !!context && (canReview || can(context, "knowledge_write"));
  const tabAllowed = canOpenKnowledgeTab(context, tab);
  const url =
    tab === "search"
      ? `${base}search/?q=${encodeURIComponent(query)}&page=${page}&per_page=${pageSize(params)}`
      : tab === "editorial" && canEdit
        ? `${base}articles/?${params.toString()}`
        : null;
  const { data, error, isLoading, mutate } = useSWR(url, (u: string) =>
    qualityApi.read<Page<Article | Publication>>(u)
  );
  const saved = async () => {
    await mutate();
  };
  const tabs = [
    { key: "search", name: "知识库" },
    ...(canEdit ? [{ key: "editorial", name: "知识维护" }] : []),
    { key: "assistant", name: "知识问答" },
    ...(canEdit ? [{ key: "governance", name: "知识管理" }] : []),
  ];
  const movedTo =
    tab === "settings" && workspaceSlug && projectId && context?.identifier
      ? movedSettingsPath(workspaceSlug, context.identifier, projectId, tab, params)
      : undefined;
  if (movedTo && tabAllowed) return <Navigate replace to={`${movedTo}${location.hash}`} />;
  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-1">
      <PageHead title={`${context?.project_name ?? "项目"} · 文档与知识`} />
      {workspaceSlug && projectId && (
        <DocumentWorkspaceNav
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          active={tab === "assistant" ? "assistant" : "knowledge"}
        />
      )}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2">
          <AppSidebarToggleButton onlyWhenCollapsed />
          <span className="text-13 text-secondary">{context?.project_name ?? "项目"} /</span>
          <BookOpen className="size-4" />
          <h1 className="platform-page-title">文档与知识</h1>
        </div>
        <div className="flex gap-2">
          {canReview && (
            <Button variant="neutral-primary" onClick={() => setParams({ tab: "editorial", status: "review" })}>
              待审核
            </Button>
          )}
          {canEdit && (
            <Button variant="neutral-primary" onClick={() => setImporting(true)}>
              导入文档
            </Button>
          )}
          <Button variant="neutral-primary" aria-label="刷新知识" onClick={() => void saved()}>
            <RefreshCw className="size-4" />
          </Button>
          {canEdit && (
            <Button onClick={() => setEditing(null)}>
              <Plus className="mr-1 size-4" />
              新建知识草稿
            </Button>
          )}
        </div>
      </header>
      <nav aria-label="知识管理导航" className="flex gap-5 overflow-auto border-b border-subtle px-5">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setParams({ tab: t.key })}
            aria-current={tab === t.key ? "page" : undefined}
            className={`shrink-0 border-b-2 py-3 text-13 ${tab === t.key ? "border-accent-primary text-accent-primary" : "border-transparent text-secondary"}`}
          >
            {t.name}
          </button>
        ))}
      </nav>
      <main
        className={
          tab === "assistant"
            ? "flex min-h-0 flex-1 flex-col overflow-hidden p-3 sm:p-5"
            : "min-h-0 flex-1 space-y-4 overflow-auto p-5"
        }
      >
        {(error || contextError) && (
          <p role="alert" className="rounded-md border border-subtle p-3 text-13 text-danger-primary">
            {errorMessage(error || contextError)}
          </p>
        )}
        {!context ? (
          !contextError && (
            <p role="status" className="text-13 text-secondary">
              正在加载项目权限…
            </p>
          )
        ) : !tabAllowed ? (
          <p role="alert" className="text-13 text-secondary">
            当前账号没有此功能权限。
          </p>
        ) : tab === "governance" ? (
          <GovernancePanel base={base} isManager={canReview} />
        ) : tab === "assistant" ? (
          context && (
            <AssistantPanel
              base={base}
              canWrite={can(context, "chat")}
              canConfigure={!!context.can_configure_model}
              onNavigate={(nextTab) => setParams({ tab: nextTab })}
            />
          )
        ) : (
          <>
            {tab === "editorial" && context && (
              <ListFilters kind="articles" context={context} params={params} onApply={setParams} />
            )}
            {tab === "search" && (
              <form
                className="flex flex-wrap gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  setParams({ tab, q: queryInput });
                }}
              >
                <label htmlFor="knowledge-search" className="sr-only">
                  知识关键词
                </label>
                <input
                  id="knowledge-search"
                  type="search"
                  maxLength={2000}
                  className={`${fieldClass} max-w-xl`}
                  value={queryInput}
                  onChange={(e) => setQueryInput(e.target.value)}
                  placeholder="输入现象、错误码、设备或版本…"
                />
                <Button type="submit">
                  <Search className="mr-1 size-4" />
                  检索
                </Button>
              </form>
            )}
            <details className="text-12 text-secondary">
              <summary className="cursor-pointer">{tab === "search" ? "检索范围" : "发布流程"}</summary>
              <p className="mt-2 leading-6">
                {tab === "search"
                  ? "仅检索当前项目可见的已发布版本。引用绑定具体版本，内容更新仍可追溯。"
                  : "有审核权限：草稿 → 脱敏检查 → 发布。其他成员提交审核，由审核人员发布。"}
              </p>
            </details>
            {isLoading ? (
              <p role="status" className="text-13 text-secondary">
                正在加载知识…
              </p>
            ) : !data?.results.length ? (
              <Empty>
                {tab === "search"
                  ? "未找到已发布知识，请调整关键词，或先整理并发布项目知识。"
                  : "还没有知识草稿。可以整理技术经验，或从已有工作项关联来源。"}
              </Empty>
            ) : (
              <div className="divide-y divide-subtle rounded-md border border-subtle">
                {data.results.map((row) =>
                  "reference" in row ? (
                    <button
                      type="button"
                      key={row.id}
                      className="block w-full p-4 text-left hover:bg-layer-1"
                      onClick={() => setPublication(row)}
                    >
                      <h2 className="platform-record-link text-14">
                        {row.title}
                        <span className="ml-2 text-11 text-tertiary">v{row.version}</span>
                      </h2>
                      <p className="mt-2 line-clamp-2 text-13 whitespace-pre-wrap text-secondary">{row.content}</p>
                      <p className="mt-2 text-11 text-tertiary">
                        {row.tags.join(" · ")} · {row.reference}
                      </p>
                    </button>
                  ) : (
                    <button
                      type="button"
                      key={row.id}
                      className="flex w-full flex-wrap items-center justify-between gap-3 p-4 text-left hover:bg-layer-1"
                      onClick={() => setArticle(row)}
                    >
                      <div>
                        <h2 className="platform-record-link text-14">
                          {row.code && <span className="mr-2 text-11 text-secondary">{row.code}</span>}
                          {row.title}
                        </h2>
                        <p className="mt-1 text-11 text-secondary">创建人：{row.created_by_name || "未记录"}</p>
                        <p className="mt-1 text-12 text-secondary">
                          草稿版本 {row.edit_version} · 已发布 v{row.published_version} ·{" "}
                          {row.publication_active ? "开放检索" : "尚未发布"}
                        </p>
                      </div>
                      <span className="rounded border border-subtle px-2 py-1 text-11">
                        {articleStatusNames[row.status]}
                      </span>
                    </button>
                  )
                )}
              </div>
            )}
            {data && (
              <Paging
                perPage={pageSize(params)}
                onPageSizeChange={(size) => {
                  const next = new URLSearchParams(params);
                  next.set("per_page", String(size));
                  next.delete("page");
                  setParams(next);
                }}
                page={page}
                count={data.count}
                onChange={(n) => {
                  const next = new URLSearchParams(params);
                  next.set("page", String(n));
                  setParams(next);
                }}
              />
            )}
          </>
        )}
      </main>
      {importing && (
        <DocumentImportForm
          base={base.replace("/knowledge/", "/quality/")}
          resource="knowledge"
          onClose={() => setImporting(false)}
          onSaved={saved}
        />
      )}
      {editing !== undefined && context && (
        <ArticleEditor
          base={base}
          context={context}
          value={editing ?? undefined}
          onClose={() => setEditing(undefined)}
          onSaved={saved}
        />
      )}
      {article && context && (
        <ArticleDetail
          base={base}
          value={article}
          canReview={canReview}
          onClose={() => setArticle(null)}
          onSaved={saved}
          onEdit={(value) => {
            setArticle(null);
            setEditing(value);
          }}
        />
      )}
      {publication && <PublicationDetail value={publication} onClose={() => setPublication(null)} />}
    </div>
  );
}
