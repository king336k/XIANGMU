// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { ChevronDown, ChevronUp } from "lucide-react";
import { qualityApi, errorMessage } from "./api";
import { Paging } from "./shared";
import { DefectCommentCard } from "./defect-comments-card";
import { DefectCommentsEditor } from "./defect-comments-editor";
import type {
  DiscussionAttachment,
  DiscussionComment,
  DiscussionDraft,
  DiscussionReplies,
} from "./defect-comments-data";
export function DefectCommentThread({
  comment,
  endpoint,
  active,
  search,
  author,
  reply,
  draftStore,
  onReply,
  onCancelReply,
  onRefresh,
  onPreview,
  onDownload,
}: {
  comment: DiscussionComment;
  endpoint: string;
  active: boolean;
  search: string;
  author: string;
  reply: DiscussionComment | null;
  draftStore: { current: DiscussionDraft };
  onReply: (rootId: string, target: DiscussionComment) => void;
  onCancelReply: () => void;
  onRefresh: () => Promise<unknown>;
  onPreview: (file: DiscussionAttachment) => void;
  onDownload: (file: DiscussionAttachment) => void;
}) {
  const composer = useRef<HTMLDivElement>(null);
  const { mutate: mutateCache } = useSWRConfig();
  const [expanded, setExpanded] = useState(!!reply),
    [page, setPage] = useState(1);
  useEffect(() => {
    setPage(1);
  }, [search, author]);
  useEffect(() => {
    if (!reply || !expanded || !active) return;
    composer.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    const editable = composer.current?.querySelector<HTMLElement>('[contenteditable="true"]');
    editable?.focus();
  }, [reply, expanded, active]);
  const params = new URLSearchParams({ page: String(page), per_page: "10" });
  if (search) params.set("search", search);
  if (author) params.set("author", author);
  const { data, error, isLoading, mutate } = useSWR(
    active && expanded ? `${endpoint}${comment.id}/replies/?${params}` : null,
    (url: string) => qualityApi.read<DiscussionReplies>(url),
    { revalidateOnFocus: false }
  );
  const replyTo = (target: DiscussionComment) => {
    setExpanded(true);
    onReply(comment.id, target);
  };
  const count = data?.reply_count ?? comment.reply_count ?? 0;
  return (
    <section
      aria-label={`${comment.actor}的讨论`}
      className="min-w-0 overflow-hidden rounded-lg border border-subtle bg-surface-1"
      data-thread-id={comment.id}
    >
      <DefectCommentCard
        comment={comment}
        endpoint={endpoint}
        onReply={replyTo}
        onPreview={onPreview}
        onDownload={onDownload}
        embedded
      />
      {(count > 0 || expanded || !!reply) && (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
          className="focus-visible:ring-accent-primary mx-3 mb-3 inline-flex items-center gap-1.5 rounded border border-accent-subtle bg-accent-subtle px-3 py-1.5 text-12 text-accent-primary hover:bg-layer-1 focus-visible:ring-2 focus-visible:outline-none sm:mx-4"
        >
          {expanded ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          {expanded ? `收起回复（${count}）` : `共 ${count} 条回复 · 展开`}
        </button>
      )}
      <div hidden={!expanded} className="min-w-0 space-y-3 border-t border-subtle bg-layer-1 px-3 py-3 sm:px-4">
        {error && (
          <p
            role="alert"
            className="rounded border border-danger-subtle bg-danger-subtle p-3 text-12 text-danger-primary"
          >
            {errorMessage(error)}
            <button type="button" className="ml-3 underline" onClick={() => void mutate()}>
              重试
            </button>
          </p>
        )}
        {isLoading && !data && (
          <p role="status" className="py-3 text-12 text-secondary">
            正在读取回复…
          </p>
        )}
        {data && !data.results.length && (
          <p className="py-3 text-12 text-secondary">{search || author ? "当前筛选没有匹配的回复。" : "暂无回复。"}</p>
        )}
        <div aria-label="讨论回复" className="min-w-0 space-y-2 border-l-2 border-accent-subtle pl-3 sm:pl-4">
          {data?.results.map((row) => (
            <DefectCommentCard
              key={row.id}
              comment={row}
              endpoint={endpoint}
              onReply={replyTo}
              onPreview={onPreview}
              onDownload={onDownload}
              compact
            />
          ))}
        </div>
        {data && data.count > 10 && <Paging page={page} count={data.count} perPage={10} onChange={setPage} />}
        {reply && (
          <div ref={composer} aria-label="回复输入区">
            <DefectCommentsEditor
              endpoint={endpoint}
              reply={reply}
              draftStore={draftStore}
              preserveReplyAfterPublish
              onCancelReply={onCancelReply}
              onPublished={async () => {
                const firstParams = new URLSearchParams(params);
                firstParams.set("page", "1");
                const firstKey = `${endpoint}${comment.id}/replies/?${firstParams}`;
                setPage(1);
                await mutateCache(firstKey, qualityApi.read<DiscussionReplies>(firstKey), { revalidate: false });
                await onRefresh();
              }}
            />
          </div>
        )}
      </div>
    </section>
  );
}
