// SPDX-License-Identifier: AGPL-3.0-only
export type DiscussionAttachment = { id: string; name: string; size: number; content_type: string };
export type DiscussionComment = {
  id: string;
  content: string;
  content_html: string;
  visibility: "internal";
  actor: string;
  created_by_id: string | null;
  created_at: string;
  reply_to: { id: string; actor: string; content: string } | null;
  attachments: DiscussionAttachment[];
};
export type DiscussionPage = {
  count: number;
  results: DiscussionComment[];
  participants: { id: string; name: string }[];
};
export type DiscussionIntent = { signature: string; requestId: string };
export function discussionIntent(
  previous: DiscussionIntent | null,
  content: { content_html: string; reply_to: string | null; attachment_ids: string[] },
  nextId: () => string
): DiscussionIntent {
  const signature = JSON.stringify(content);
  return previous?.signature === signature ? previous : { signature, requestId: nextId() };
}
export function discussionQuery(page: number, search: string, author: string) {
  const query = new URLSearchParams({ page: String(page), per_page: "20" });
  if (search.trim()) query.set("search", search.trim());
  if (author) query.set("author", author);
  return query;
}
export const discussionSize = (bytes: number) =>
  bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export function validateDiscussionFiles(existing: { size: number }[], chosen: { name: string; size: number }[]) {
  if (existing.length + chosen.length > 10) throw Error("每条评论最多10个附件。");
  for (const file of chosen) if (file.size > 20 * 1024 * 1024) throw Error(`${file.name} 超过20MB。`);
  if ([...existing, ...chosen].reduce((sum, file) => sum + file.size, 0) > 50 * 1024 * 1024)
    throw Error("单条评论附件合计不能超过50MB。");
}
