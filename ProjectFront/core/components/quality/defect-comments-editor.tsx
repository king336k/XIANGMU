// SPDX-License-Identifier: AGPL-3.0-only
import { useRef, useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { LiteTextEditorWithRef } from "@plane/editor";
import type { EditorRefApi, TFileHandler } from "@plane/editor";
import { Bold, Code2, Heading2, Italic, List, ListOrdered, Paperclip, Quote, Smile, X } from "lucide-react";
import { Button } from "@plane/ui";
import { sanitizeHTML } from "@plane/utils";
import { qualityApi, errorMessage } from "./api";
import { discussionIntent, discussionSize, validateDiscussionFiles } from "./defect-comments-data";
import type { DiscussionAttachment, DiscussionComment, DiscussionIntent } from "./defect-comments-data";
const disabledFiles: TFileHandler = {
  assetsUploadStatus: {},
  cancel() {},
  checkIfAssetExists: async () => false,
  delete: async () => {},
  getAssetDownloadSrc: async () => "",
  getAssetSrc: async () => "",
  restore: async () => {},
  upload: async () => {
    throw Error("请使用评论附件上传。");
  },
  duplicate: async () => {
    throw Error("请重新上传附件。");
  },
  validation: { maxFileSize: 20 * 1024 * 1024 },
};
const tools = [
  { key: "h2", title: "标题", icon: Heading2 },
  { key: "bold", title: "加粗", icon: Bold },
  { key: "italic", title: "斜体", icon: Italic },
  { key: "bulleted-list", title: "无序列表", icon: List },
  { key: "numbered-list", title: "有序列表", icon: ListOrdered },
  { key: "quote", title: "引用", icon: Quote },
  { key: "code", title: "代码", icon: Code2 },
] as const;
const emojis = ["👍", "✅", "🙏", "👀", "🎉", "🙂", "🤔", "❗", "💡", "🚀", "👌", "❤️"];
export function DefectCommentsEditor({
  endpoint,
  reply,
  onCancelReply,
  onPublished,
}: {
  endpoint: string;
  reply: DiscussionComment | null;
  onCancelReply: () => void;
  onPublished: () => Promise<unknown>;
}) {
  const editor = useRef<EditorRefApi>(null),
    input = useRef<HTMLInputElement>(null);
  const intent = useRef<DiscussionIntent | null>(null);
  const [html, setHtml] = useState(""),
    [files, setFiles] = useState<DiscussionAttachment[]>([]);
  const [busy, setBusy] = useState(false),
    [uploading, setUploading] = useState(false),
    [error, setError] = useState("");
  const [activeTools, setActiveTools] = useState<Record<string, boolean>>({});
  const refreshActiveTools = () => {
    if (!editor.current) return;
    setActiveTools(
      Object.fromEntries(
        tools.map((tool) => [tool.key, editor.current?.isMenuItemActive?.({ itemKey: tool.key }) || false])
      )
    );
  };
  const [emojiOpen, setEmojiOpen] = useState(false),
    [dragging, setDragging] = useState(false);
  const upload = async (chosen: File[]) => {
    if (!chosen.length || busy || uploading) return;
    setUploading(true);
    setError("");
    try {
      validateDiscussionFiles(files, chosen);
      await chosen.reduce<Promise<void>>(
        (chain, file) =>
          chain.then(async () => {
            const form = new FormData();
            form.append("file", file);
            const result = await qualityApi.write<DiscussionAttachment>(`${endpoint}files/`, form);
            setFiles((previous) => [...previous, result]);
            return undefined;
          }),
        Promise.resolve()
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setUploading(false);
    }
  };
  const publish = async () => {
    if (busy || uploading || (!sanitizeHTML(html) && !files.length)) return;
    setBusy(true);
    setError("");
    try {
      const body = {
        content_html: html || "<p></p>",
        reply_to: reply?.id || null,
        attachment_ids: files.map((file) => file.id),
      };
      intent.current = discussionIntent(intent.current, body, uuidv4);
      await qualityApi.write(endpoint, { ...body, request_id: intent.current.requestId });
      editor.current?.clearEditor();
      setHtml("");
      setFiles([]);
      intent.current = null;
      onCancelReply();
      await onPublished();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section
      aria-label="发表评论"
      onKeyDown={(event) => {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          event.stopPropagation();
          void publish();
        }
      }}
      className={`min-w-0 overflow-hidden rounded-lg border bg-surface-1 ${dragging ? "border-accent-primary" : "border-subtle"}`}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        void upload(Array.from(event.dataTransfer.files));
      }}
      onPaste={(event) => {
        const pasted = Array.from(event.clipboardData.files);
        if (pasted.length) {
          event.preventDefault();
          void upload(pasted);
        }
      }}
    >
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-subtle bg-layer-1 px-4 py-3">
        <h3 className="text-13 font-semibold">发表评论</h3>
        <span className="text-11 text-secondary">仅项目成员可见</span>
      </header>
      {reply && (
        <div className="border-accent-primary mx-4 mt-3 flex min-w-0 items-start gap-3 rounded-md border-l-2 bg-accent-subtle px-3 py-2 text-12">
          <div className="min-w-0 flex-1">
            <p className="font-medium text-accent-primary">回复 {reply.actor}</p>
            <p className="mt-1 line-clamp-2 break-words text-secondary">{reply.content}</p>
          </div>
          <button
            type="button"
            aria-label="取消回复"
            disabled={busy}
            onClick={onCancelReply}
            className="rounded p-1 text-secondary hover:bg-layer-1"
          >
            <X className="size-4" />
          </button>
        </div>
      )}
      <div
        role="toolbar"
        aria-label="评论格式"
        className="flex flex-wrap items-center gap-1 border-b border-subtle px-3 py-2"
      >
        {tools.map((tool) => (
          <button
            key={tool.key}
            type="button"
            title={tool.title}
            aria-label={tool.title}
            disabled={busy}
            aria-pressed={activeTools[tool.key] || false}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => editor.current?.executeMenuItemCommand({ itemKey: tool.key })}
            className={`focus-visible:ring-accent-primary rounded p-2 hover:bg-accent-subtle hover:text-accent-primary focus-visible:ring-2 focus-visible:outline-none disabled:opacity-40 ${activeTools[tool.key] ? "bg-accent-subtle text-accent-primary" : "text-secondary"}`}
          >
            <tool.icon className="size-4" />
          </button>
        ))}
        <span className="mx-1 h-5 border-l border-subtle" />
        <button
          type="button"
          aria-label="添加表情"
          title="表情"
          aria-expanded={emojiOpen}
          disabled={busy}
          onClick={() => setEmojiOpen(!emojiOpen)}
          className="rounded p-2 text-secondary hover:bg-accent-subtle hover:text-accent-primary"
        >
          <Smile className="size-4" />
        </button>
        <button
          type="button"
          aria-label="上传图片或文件"
          title="上传图片或文件"
          disabled={busy || uploading}
          onClick={() => input.current?.click()}
          className="rounded p-2 text-secondary hover:bg-accent-subtle hover:text-accent-primary disabled:opacity-40"
        >
          <Paperclip className="size-4" />
        </button>
        <input
          ref={input}
          type="file"
          multiple
          accept=".png,.jpg,.jpeg,.gif,.webp,.txt,.log,.md,.json,.csv,.yaml,.yml,.pdf,.zip,.doc,.docx,.xls,.xlsx"
          aria-label="选择评论附件"
          className="sr-only"
          disabled={busy || uploading}
          onChange={(event) => {
            void upload(Array.from(event.target.files || []));
            event.target.value = "";
          }}
        />
      </div>
      {emojiOpen && (
        <div
          role="group"
          aria-label="选择表情"
          className="flex flex-wrap gap-1 border-b border-subtle bg-layer-1 px-4 py-2"
        >
          {emojis.map((emoji) => (
            <button
              key={emoji}
              type="button"
              aria-label={`插入 ${emoji}`}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                editor.current?.setEditorValueAtCursorPosition(emoji);
                setEmojiOpen(false);
              }}
              className="rounded px-2 py-1 text-18 hover:bg-accent-subtle"
            >
              {emoji}
            </button>
          ))}
        </div>
      )}
      <div className="min-h-36 min-w-0 px-3 py-3 [&_.ProseMirror]:max-h-72 [&_.ProseMirror]:min-h-28 [&_.ProseMirror]:overflow-y-auto">
        <LiteTextEditorWithRef
          ref={editor}
          id={`defect-discussion-${endpoint.split("/").filter(Boolean).at(-2)}`}
          initialValue={html || "<p></p>"}
          editable={!busy}
          disabledExtensions={["image", "issue-embed", "slash-commands", "enter-key"]}
          flaggedExtensions={[]}
          fileHandler={disabledFiles}
          mentionHandler={{ renderComponent: () => null }}
          getEditorMetaData={() => ({ file_assets: [], user_mentions: [] })}
          extendedEditorProps={{}}
          placeholder="写下讨论内容，或粘贴图片、拖入文件…"
          onChange={(_, content) => setHtml(content)}
          onTransaction={refreshActiveTools}
          displayConfig={{ fontSize: "small-font" }}
          containerClassName="min-w-0"
        />
      </div>
      {!!files.length && (
        <div className="flex flex-wrap gap-2 px-4 pb-3">
          {files.map((file) => (
            <div
              key={file.id}
              className="flex max-w-full min-w-0 items-center gap-2 rounded-md border border-subtle bg-layer-1 px-3 py-2 text-12"
            >
              <Paperclip className="size-3.5 shrink-0 text-accent-primary" />
              <span className="max-w-56 truncate">{file.name}</span>
              <span className="shrink-0 text-11 text-secondary">{discussionSize(file.size)}</span>
              <button
                type="button"
                aria-label={`移除 ${file.name}`}
                disabled={busy}
                onClick={() => setFiles((previous) => previous.filter((row) => row.id !== file.id))}
                className="rounded p-1 text-secondary hover:text-danger-primary"
              >
                <X className="size-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
      {error && (
        <p
          role="alert"
          className="mx-4 mb-3 rounded border border-danger-subtle bg-danger-subtle p-3 text-12 text-danger-primary"
        >
          {error}
        </p>
      )}
      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-subtle bg-layer-1 px-4 py-3">
        <span role={uploading ? "status" : undefined} className="text-11 text-secondary">
          {uploading ? "正在上传附件…" : "粘贴图片或拖入文件 · 最多10个，单个20MB · Ctrl+Enter 发布"}
        </span>
        <Button type="button" disabled={busy || uploading || (!sanitizeHTML(html) && !files.length)} onClick={publish}>
          {busy ? "正在发布…" : "发布评论"}
        </Button>
      </footer>
    </section>
  );
}
