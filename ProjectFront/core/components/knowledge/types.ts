// SPDX-License-Identifier: AGPL-3.0-only
export type Publication = {
  is_excerpt?: boolean;
  source_characters?: number;
  source_project_name?: string;
  device_scope?: string;
  version_scope?: string;
  created_by_name?: string;
  id: string;
  article_id: string;
  version: number;
  reference: string;
  title: string;
  content: string;
  tags: string[];
  created_at: string;
};
export type DocumentSourceFile = {
  id: string;
  name: string;
  kind: string;
  size: number;
  sha256: string;
  download_url: string;
  preview_url: string | null;
};
export type Article = {
  source_files?: DocumentSourceFile[];
  code?: string;
  number?: number;
  created_by_name?: string;
  id: string;
  title: string;
  content: string;
  tags: string[];
  status: string;
  edit_version: number;
  merged_into_id: string | null;
  published_version: number;
  publication_active: boolean;
  scanned_version: number;
  scan_findings: { kind: string; line: number; message: string; field?: string }[];
  source_issue_id: string | null;
  versions: Publication[];
  events: { id: string; action: string; version: number; note: string; created_at: string; actor: string }[];
};
export type Conversation = { id: string; title: string; created_at: string };
export type Message = {
  id: string;
  conversation_id: string;
  query: string;
  status: string;
  answer: string;
  suggested_actions: string[];
  verification_steps: string[];
  citations: Publication[];
  feedback: string;
  error_code: string;
  model: string;
  created_at: string;
};
export const articleStatusNames: Record<string, string> = {
  draft: "草稿",
  review: "待审核",
  published: "已发布",
  offline: "已下线",
};
