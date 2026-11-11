import { AssistantMarkdown } from "./assistant-markdown";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { Field, fieldClass, Modal } from "@/components/quality/shared";
import type { Article, Publication } from "./types";
import { articleStatusNames } from "./types";
import { DocumentAnalysis } from "./document-analysis";
import { SharingPanel } from "./sharing-panel";
import { PublicationDetail } from "./publication-detail";
import { DocumentSourceFiles } from "@/components/quality/document-source-files";

export function ArticleDetail({
  base,
  value,
  canReview,
  onClose,
  onSaved,
  onEdit,
}: {
  base: string;
  value: Article;
  canReview: boolean;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
  onEdit: (article: Article) => void;
}) {
  const [article, setArticle] = useState(value);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [publication, setPublication] = useState<Publication | null>(null);
  const perform = async (verb: string, comment = "") => {
    const updated = await qualityApi.write<Article>(`${base}articles/${article.id}/workflow/`, {
      action: verb,
      expected_version: article.edit_version,
      comment,
    });
    setArticle(updated);
    await onSaved();
  };
  const click = async (verb: string) => {
    setBusy(true);
    setError("");
    try {
      await perform(verb);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {analyzing && (
        <DocumentAnalysis
          base={base}
          article={article}
          canEdit={true}
          onSaved={async (updated) => {
            setArticle(updated);
            await onSaved();
          }}
          onClose={() => setAnalyzing(false)}
        />
      )}
      {sharing && (
        <SharingPanel
          base={base}
          articleId={article.id}
          version={article.edit_version}
          onClose={() => setSharing(false)}
        />
      )}
      <Modal title={article.title} onClose={onClose}>
        <div className="flex flex-wrap gap-3 text-12 text-secondary">
          <span>
            {articleStatusNames[article.status]} · 草稿版本 {article.edit_version}
          </span>
          <span>
            已发布 v{article.published_version} · {article.publication_active ? "可检索" : "未开放检索"}
          </span>
        </div>
        <div className="max-h-80 overflow-y-auto rounded-md border border-subtle p-4 text-13 leading-7 break-words whitespace-pre-wrap">
          <AssistantMarkdown content={article.content} />
        </div>
        <DocumentSourceFiles files={article.source_files || []} />
        <div className="flex flex-wrap gap-2">
          {article.status !== "review" && !article.merged_into_id && (
            <Button variant="neutral-primary" onClick={() => setAnalyzing(true)}>
              解读文档
            </Button>
          )}
          {canReview && article.publication_active && (
            <Button variant="neutral-primary" onClick={() => setSharing(true)}>
              共享范围
            </Button>
          )}
          {article.status !== "review" && (
            <Button variant="neutral-primary" onClick={() => onEdit(article)}>
              编辑草稿
            </Button>
          )}
          {article.status === "draft" && !article.merged_into_id && (
            <>
              <Button variant="neutral-primary" disabled={busy} onClick={() => void click("scan")}>
                脱敏检查
              </Button>
              <Button
                disabled={busy || article.scanned_version !== article.edit_version || !!article.scan_findings.length}
                onClick={() => void click(canReview ? "publish" : "submit")}
              >
                {canReview ? "发布" : "提交审核"}
              </Button>
            </>
          )}
          {canReview && article.status === "review" && (
            <>
              <Button disabled={busy} onClick={() => void click("publish")}>
                发布
              </Button>
              <Button variant="neutral-primary" onClick={() => setAction("reject")}>
                退回修改
              </Button>
            </>
          )}
          {canReview && article.publication_active && (
            <Button variant="neutral-primary" onClick={() => setAction("offline")}>
              下线发布版
            </Button>
          )}
        </div>
        {error && (
          <p role="alert" className="text-13 text-danger-primary">
            {error}
          </p>
        )}
        {article.status === "draft" && !article.merged_into_id && (
          <section className="space-y-2 text-12">
            <h3 className="font-medium">脱敏检查</h3>
            {article.scanned_version === article.edit_version ? (
              article.scan_findings.length ? (
                article.scan_findings.map((finding) => (
                  <p key={`${finding.kind}-${finding.line}`} className="text-danger-primary">
                    {({ title: "标题", content: "内容", tags: "标签" } as Record<string, string>)[
                      finding.field || ""
                    ] || "文本"}
                    第{finding.line}行 · {finding.message}
                  </p>
                ))
              ) : (
                <p className="text-success-primary">未发现常见敏感信息，请确认内容可供当前项目使用。</p>
              )
            ) : (
              <p className="text-secondary">当前草稿尚未完成扫描。</p>
            )}
          </section>
        )}
        <section className="space-y-2 border-t border-subtle pt-4">
          <h3 className="text-13 font-medium">发布历史</h3>
          {article.versions.length ? (
            article.versions.map((version) => (
              <button
                type="button"
                key={version.id}
                className="block text-left text-12 text-accent-primary"
                onClick={() => setPublication(version)}
              >
                v{version.version} · {version.title} · {renderNumericDateTime(version.created_at)}
              </button>
            ))
          ) : (
            <p className="text-12 text-secondary">尚未发布。</p>
          )}
        </section>
        <details className="text-12">
          <summary className="cursor-pointer">操作记录（{article.events.length}）</summary>
          <ol className="mt-3 space-y-2">
            {article.events.map((event) => (
              <li key={event.id}>
                {renderNumericDateTime(event.created_at)} · {event.actor || "成员"} ·{" "}
                {
                  (
                    {
                      edit: "编辑",
                      scan: "扫描",
                      submit: "提交审核",
                      publish: "发布",
                      reject: "退回",
                      offline: "下线",
                    } as Record<string, string>
                  )[event.action]
                }{" "}
                {event.note}
              </li>
            ))}
          </ol>
        </details>
      </Modal>
      {action && (
        <Modal
          title={action === "reject" ? "退回知识草稿" : "下线知识"}
          onClose={() => setAction(null)}
          onSubmit={async (form) => {
            await perform(action, String(form.get("comment")));
          }}
        >
          <Field label="原因 *">
            <textarea required name="comment" rows={3} maxLength={4000} className={fieldClass} />
          </Field>
        </Modal>
      )}
      {publication && <PublicationDetail value={publication} onClose={() => setPublication(null)} />}
    </>
  );
}
