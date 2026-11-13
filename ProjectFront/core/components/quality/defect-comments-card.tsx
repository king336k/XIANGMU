// SPDX-License-Identifier: AGPL-3.0-only
import { Download, FileText, Image as ImageIcon, Reply } from "lucide-react";
import { renderNumericDateTime } from "@plane/utils";
import type { DiscussionAttachment, DiscussionComment } from "./defect-comments-data";
import { discussionSize } from "./defect-comments-data";
const avatarColors = [
  "bg-accent-subtle text-accent-primary",
  "bg-success-subtle text-success-primary",
  "bg-warning-subtle text-warning-primary",
];
const bodyClass =
  "prose prose-sm max-w-none break-words text-13 text-primary [&_a]:text-accent-primary [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:border-accent-subtle [&_blockquote]:pl-3 [&_blockquote]:text-secondary [&_h1]:text-18 [&_h2]:text-16 [&_h3]:text-14 [&_p]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-layer-1 [&_pre]:p-3 [&_code]:text-12";
export function DefectCommentCard({
  comment,
  endpoint,
  onReply,
  onPreview,
  onDownload,
  compact = false,
}: {
  comment: DiscussionComment;
  endpoint: string;
  onReply: (comment: DiscussionComment) => void;
  onPreview: (file: DiscussionAttachment) => void;
  onDownload: (file: DiscussionAttachment) => void;
  compact?: boolean;
}) {
  const tone =
    avatarColors[
      (comment.created_by_id || comment.actor).split("").reduce((sum, c) => sum + c.charCodeAt(0), 0) %
        avatarColors.length
    ];
  const content = comment.content_html ? (
    <div className={bodyClass} dangerouslySetInnerHTML={{ __html: comment.content_html }} />
  ) : (
    <p className="text-13 leading-7 break-words whitespace-pre-wrap">{comment.content}</p>
  );
  return (
    <article
      id={`discussion-${comment.id}`}
      aria-label={`${comment.actor}的评论`}
      className={
        compact
          ? "min-w-0 border-b border-subtle bg-surface-1 py-3 last:border-b-0"
          : "min-w-0 rounded-lg border border-subtle bg-surface-1 px-3 py-4 sm:px-4"
      }
    >
      <div className="flex min-w-0 gap-3">
        <span
          aria-hidden="true"
          className={`grid size-8 shrink-0 place-items-center rounded-full text-12 font-semibold ${tone}`}
        >
          {(comment.actor || "成员").slice(0, 2)}
        </span>
        <div className="min-w-0 flex-1">
          <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <strong className="text-13 font-semibold break-words">{comment.actor}</strong>
              <time dateTime={comment.created_at} className="text-11 text-secondary">
                {renderNumericDateTime(comment.created_at)}
              </time>
            </div>
            <button
              type="button"
              onClick={() => onReply(comment)}
              className="focus-visible:ring-accent-primary inline-flex shrink-0 items-center gap-1 rounded px-2 py-1 text-12 text-accent-primary hover:bg-accent-subtle focus-visible:ring-2 focus-visible:outline-none"
            >
              <Reply className="size-3.5" />
              回复
            </button>
          </header>
          {comment.reply_to && (
            <blockquote className="mt-3 min-w-0 rounded border-l-2 border-accent-subtle bg-layer-1 px-3 py-2">
              <p className="text-11 font-medium text-accent-primary">回复 {comment.reply_to.actor}</p>
              <p className="mt-1 line-clamp-2 text-12 break-words text-secondary">{comment.reply_to.content}</p>
            </blockquote>
          )}
          <div className="mt-2">
            {comment.content.length > 1000 || comment.content.split("\n").length > 12 ? (
              <details>
                <summary className="cursor-pointer text-12 text-accent-primary">
                  {comment.content.slice(0, 130)}… 展开全文
                </summary>
                <div className="mt-2">{content}</div>
              </details>
            ) : (
              content
            )}
          </div>
          {!!comment.attachments.length && (
            <div aria-label="评论附件" className="mt-3 grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {comment.attachments.map((file) => {
                const image = file.content_type.startsWith("image/");
                return (
                  <div key={file.id} className="min-w-0 overflow-hidden rounded-md border border-subtle bg-layer-1">
                    {image && (
                      <button
                        type="button"
                        aria-label={`预览 ${file.name}`}
                        onClick={() => onPreview(file)}
                        className="block w-full cursor-zoom-in border-b border-subtle bg-surface-1 p-2"
                      >
                        <img
                          src={`${endpoint}files/${file.id}/preview/`}
                          alt={file.name}
                          loading="lazy"
                          className="mx-auto h-28 max-w-full object-contain"
                        />
                      </button>
                    )}
                    <div className="flex min-w-0 items-center gap-2 px-3 py-2">
                      {image ? (
                        <ImageIcon className="size-4 shrink-0 text-accent-primary" />
                      ) : (
                        <FileText className="size-4 shrink-0 text-accent-primary" />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-12" title={file.name}>
                          {file.name}
                        </span>
                        <span className="text-10 text-secondary">{discussionSize(file.size)}</span>
                      </span>
                      <button
                        type="button"
                        aria-label={`下载 ${file.name}`}
                        onClick={() => onDownload(file)}
                        className="focus-visible:ring-accent-primary rounded p-1.5 text-secondary hover:bg-accent-subtle hover:text-accent-primary focus-visible:ring-2 focus-visible:outline-none"
                      >
                        <Download className="size-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}
