// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { AssistantMarkdown } from "./assistant-markdown";
import { BookOpen, Check, Copy, ThumbsDown, ThumbsUp } from "lucide-react";
import { renderNumericDateTime } from "@plane/utils";
import type { Message, Publication } from "./types";

export function AssistantMessage({
  message,
  canWrite,
  feedbackBusy,
  onFeedback,
  onCitation,
  onRetry,
}: {
  message: Message;
  canWrite: boolean;
  feedbackBusy: string;
  onFeedback: (message: Message, value: string) => void;
  onCitation: (value: Publication) => void;
  onRetry: (query: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.answer);
      setCopied(true);
      setCopyError("");
    } catch {
      setCopyError("复制失败，请选择回答文字手动复制。");
    }
  };
  const fallback =
    message.status === "running"
      ? "问题正在处理中，请稍后刷新会话查看。"
      : message.status === "failed"
        ? "这次回答未成功。可以将问题放回输入框，检查后重新发送。"
        : "暂无可显示的回答。";
  return (
    <article className="min-w-0 space-y-5" aria-label="一轮问答">
      <div className="ml-auto max-w-full sm:max-w-[85%]">
        <p className="mb-1.5 text-right text-11 text-tertiary">你 · {renderNumericDateTime(message.created_at)}</p>
        <div className="rounded-lg border border-subtle bg-layer-1 px-4 py-3 text-13 leading-6 [overflow-wrap:anywhere] break-words whitespace-pre-wrap">
          {message.query}
        </div>
      </div>
      <div className="min-w-0">
        <p className="mb-2 flex items-center gap-2 text-12 font-medium text-secondary">
          <BookOpen className="size-4" />
          知识助手
        </p>
        <div className="min-w-0 space-y-3 text-13 leading-7 [overflow-wrap:anywhere] break-words [&_a]:text-accent-primary [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:border-subtle [&_blockquote]:pl-3 [&_blockquote]:text-secondary [&_h1]:text-16 [&_h1]:font-semibold [&_h2]:text-14 [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_ul]:list-disc [&_ul]:pl-5">
          <AssistantMarkdown content={message.answer || fallback} />
          {message.suggested_actions?.length > 0 && (
            <div>
              <h3 className="text-12 font-medium text-secondary">建议操作</h3>
              <ul>
                {[...new Set(message.suggested_actions)].map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            </div>
          )}
          {message.verification_steps?.length > 0 && (
            <div>
              <h3 className="text-12 font-medium text-secondary">验证步骤</h3>
              <ol>
                {[...new Set(message.verification_steps)].map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ol>
            </div>
          )}
        </div>
        {message.citations?.length > 0 && (
          <details className="mt-4 rounded-md border border-subtle text-12">
            <summary className="cursor-pointer px-3 py-2 font-medium text-secondary">
              查看引用来源 · {message.citations.length} 篇
            </summary>
            <div className="space-y-1 border-t border-subtle p-2">
              {message.citations.map((citation) => (
                <button
                  type="button"
                  key={citation.reference}
                  onClick={() => onCitation(citation)}
                  className="flex w-full items-start gap-2 rounded px-2 py-2 text-left hover:bg-layer-1"
                >
                  <BookOpen className="mt-0.5 size-3.5 shrink-0 text-tertiary" />
                  <span className="min-w-0 [overflow-wrap:anywhere] break-words">
                    <span className="text-accent-primary">{citation.title}</span>
                    <span className="ml-2 text-tertiary">v{citation.version}</span>
                    <span className="mt-1 block text-11 text-tertiary">{citation.reference}</span>
                  </span>
                </button>
              ))}
            </div>
          </details>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-1">
          {message.answer && (
            <button
              type="button"
              onClick={() => void copy()}
              className="flex items-center gap-1.5 rounded px-2 py-1.5 text-11 text-secondary hover:bg-layer-1"
            >
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              {copied ? "已复制" : "复制回答"}
            </button>
          )}
          {message.status === "completed" &&
            [
              { value: "helpful", label: "有帮助", selected: "已标记有帮助", Icon: ThumbsUp },
              { value: "unhelpful", label: "需改进", selected: "已记录待改进", Icon: ThumbsDown },
            ].map(({ value, label, selected, Icon }) => (
              <button
                type="button"
                key={value}
                disabled={!canWrite || !!feedbackBusy}
                aria-pressed={message.feedback === value}
                onClick={() => onFeedback(message, value)}
                className={`flex items-center gap-1.5 rounded px-2 py-1.5 text-11 disabled:opacity-60 ${message.feedback === value ? "bg-layer-1 font-medium text-accent-primary" : "text-secondary hover:bg-layer-1"}`}
              >
                <Icon className="size-3.5" />
                {message.feedback === value ? selected : label}
              </button>
            ))}
          {message.status === "failed" && (
            <button
              type="button"
              onClick={() => onRetry(message.query)}
              className="rounded px-2 py-1.5 text-11 text-accent-primary hover:bg-layer-1"
            >
              重新编辑问题
            </button>
          )}
        </div>
        {copyError && (
          <p role="status" className="mt-1 text-11 text-danger-primary">
            {copyError}
          </p>
        )}
      </div>
    </article>
  );
}
