// SPDX-License-Identifier: AGPL-3.0-only
import { useRef, useState } from "react";
import { isAxiosError } from "axios";
import useSWR, { useSWRConfig } from "swr";
import { ArrowUp, LockKeyhole, MessageCircle, RefreshCw, Search } from "lucide-react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Modal, Paging, fieldClass } from "./shared";
import { DefectCommentsEditor } from "./defect-comments-editor";
import { DefectCommentThread } from "./defect-comments-thread";
import { discussionQuery } from "./defect-comments-data";
import type { DiscussionAttachment, DiscussionComment, DiscussionDraft, DiscussionPage } from "./defect-comments-data";
export function DefectComments({ base, defectId, active }: { base: string; defectId: string; active: boolean }) {
  const endpoint = `${base}defects/${defectId}/comments/`;
  const { mutate: mutateCache } = useSWRConfig();
  const refreshDiscussion = () =>
    mutateCache(
      (key) =>
        typeof key === "string" &&
        (key.startsWith(`${endpoint}?`) || (key.startsWith(endpoint) && key.includes("/replies/?")))
    );
  const top = useRef<HTMLDivElement>(null),
    permitted = useRef(false);
  const [page, setPage] = useState(1),
    [search, setSearch] = useState(""),
    [query, setQuery] = useState(""),
    [author, setAuthor] = useState("");
  const replyDrafts = useRef<Record<string, { current: DiscussionDraft }>>({});
  const draftFor = (id: string) => {
    if (!replyDrafts.current[id]) replyDrafts.current[id] = { current: { html: "", files: [], intent: null } };
    return replyDrafts.current[id];
  };
  const [reply, setReply] = useState<{ rootId: string; target: DiscussionComment } | null>(null),
    [preview, setPreview] = useState<DiscussionAttachment | null>(null);
  const [actionError, setActionError] = useState("");
  const params = discussionQuery(page, query, author);
  params.set("view", "threads");
  const { data, error, isLoading, mutate } = useSWR(
    active ? `${endpoint}?${params}` : null,
    (url: string) => qualityApi.read<DiscussionPage>(url),
    { revalidateOnFocus: false }
  );
  const denied = isAxiosError(error) && error.response?.status === 403;
  if (data) permitted.current = true;
  if (denied) permitted.current = false;
  const download = async (file: DiscussionAttachment) => {
    setActionError("");
    try {
      await qualityApi.download(`${endpoint}files/${file.id}/download/`, file.name);
    } catch (e) {
      setActionError(errorMessage(e));
    }
  };
  const latest = () => {
    setPage(1);
    setAuthor("");
    setSearch("");
    setQuery("");
    void mutate();
    top.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  };
  return (
    <div ref={top} className="min-w-0 space-y-5" aria-label="缺陷评论">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <MessageCircle className="size-4 text-accent-primary" />
          <h2 className="text-15 font-semibold">评论</h2>
          <span className="rounded-full bg-layer-1 px-2 py-0.5 text-11 text-secondary">
            {data?.comment_count ?? data?.count ?? "—"}
          </span>
        </div>
        <span className="inline-flex items-center gap-1.5 text-11 text-secondary">
          <LockKeyhole className="size-3.5" />
          项目内部交流
        </span>
      </header>
      {denied ? (
        <p role="status" className="rounded-md border border-subtle bg-layer-1 p-4 text-13 text-secondary">
          当前账号没有查看项目内部评论的权限。
        </p>
      ) : (
        <>
          {permitted.current && (
            <DefectCommentsEditor
              key={endpoint}
              endpoint={endpoint}
              reply={null}
              onCancelReply={() => {}}
              onPublished={async () => {
                const firstParams = discussionQuery(1, "", "");
                firstParams.set("view", "threads");
                const firstKey = `${endpoint}?${firstParams}`;
                setPage(1);
                setAuthor("");
                setSearch("");
                setQuery("");
                await mutateCache(firstKey, qualityApi.read<DiscussionPage>(firstKey), { revalidate: false });
                top.current?.scrollIntoView({ block: "start", behavior: "smooth" });
              }}
            />
          )}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-subtle bg-layer-1 px-3 py-3">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
              <label className="min-w-40 flex-1 sm:max-w-72">
                <span className="sr-only">搜索评论</span>
                <input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      setQuery(search);
                      setPage(1);
                    }
                  }}
                  placeholder="搜索评论内容"
                  className={`${fieldClass} bg-surface-1`}
                />
              </label>
              <button
                type="button"
                aria-label="搜索评论"
                onClick={() => {
                  setQuery(search);
                  setPage(1);
                }}
                className="rounded-md border border-subtle bg-surface-1 p-2 text-secondary hover:text-accent-primary"
              >
                <Search className="size-4" />
              </button>
              <select
                aria-label="按参与人筛选"
                value={author}
                onChange={(event) => {
                  setAuthor(event.target.value);
                  setPage(1);
                }}
                className={`${fieldClass.replace("w-full ", "")} w-44 max-w-full bg-surface-1`}
              >
                <option value="">全部参与人</option>
                {data?.participants.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex shrink-0 items-center gap-3 text-11 text-secondary">
              <span>最新在前 · 回复在原讨论内</span>
              <button
                type="button"
                aria-label="刷新评论"
                onClick={refreshDiscussion}
                className="rounded p-1.5 hover:bg-surface-1 hover:text-accent-primary"
              >
                <RefreshCw className="size-3.5" />
              </button>
              {(page > 1 || author || query) && (
                <button
                  type="button"
                  onClick={latest}
                  className="inline-flex items-center gap-1 rounded px-2 py-1 text-12 text-accent-primary hover:bg-accent-subtle"
                >
                  <ArrowUp className="size-3.5" />
                  回到最新
                </button>
              )}
            </div>
          </div>
          {error && (
            <div
              role="alert"
              className="rounded-md border border-danger-subtle bg-danger-subtle p-3 text-13 text-danger-primary"
            >
              {errorMessage(error)}
              <button type="button" onClick={() => void mutate()} className="ml-3 underline">
                重试
              </button>
            </div>
          )}
          {actionError && (
            <p role="alert" className="text-12 text-danger-primary">
              {actionError}
            </p>
          )}
          {isLoading && !data && (
            <p role="status" className="py-8 text-center text-13 text-secondary">
              正在读取评论…
            </p>
          )}
          {data && !data.results.length && (
            <div role="status" className="rounded-md border border-dashed border-subtle py-10 text-center">
              <MessageCircle className="mx-auto mb-3 size-6 text-tertiary" />
              <p className="text-13 text-secondary">
                {query || author ? "没有匹配的评论。" : "暂无评论，写下第一条讨论。"}
              </p>
            </div>
          )}
          <div aria-label="讨论记录" className="min-w-0 space-y-3">
            {data?.results.map((comment) => (
              <DefectCommentThread
                key={comment.id}
                comment={comment}
                endpoint={endpoint}
                active={active}
                search={query}
                author={author}
                reply={reply?.rootId === comment.id ? reply.target : null}
                draftStore={draftFor(comment.id)}
                onReply={(rootId, target) => setReply({ rootId, target })}
                onCancelReply={() => setReply(null)}
                onRefresh={mutate}
                onPreview={setPreview}
                onDownload={(file) => void download(file)}
              />
            ))}
          </div>
          {data && (
            <Paging
              page={page}
              count={data.count}
              perPage={20}
              onChange={(value) => {
                setPage(value);
              }}
            />
          )}
        </>
      )}
      {preview && (
        <Modal title={preview.name} width="wide" onClose={() => setPreview(null)}>
          <img
            src={`${endpoint}files/${preview.id}/preview/`}
            alt={preview.name}
            className="mx-auto max-h-[65vh] max-w-full object-contain"
          />
          <div className="flex justify-end">
            <Button type="button" variant="neutral-primary" onClick={() => void download(preview)}>
              下载图片
            </Button>
          </div>
        </Modal>
      )}
    </div>
  );
}
