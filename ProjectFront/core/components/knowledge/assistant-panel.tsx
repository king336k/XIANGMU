// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import { ArrowDown, BookOpen, List, MessageSquare, RefreshCw, Settings } from "lucide-react";
import { errorMessage } from "@/components/quality/api";
import type { Publication } from "./types";
import { PublicationDetail } from "./publication-detail";
import { AssistantConversations } from "./assistant-conversations";
import { AssistantMessage } from "./assistant-message";
import { AssistantComposer } from "./assistant-composer";
import { useAssistantChat } from "./assistant-use-chat";

const examples = ["采集启动失败，如何逐步排查？", "如何定位设备离线和网络异常？", "版本升级前需要做哪些验证？"];
export function AssistantPanel({
  base,
  canWrite,
  canConfigure = false,
  onNavigate,
}: {
  base: string;
  canWrite: boolean;
  canConfigure?: boolean;
  onNavigate: (tab: "search" | "settings") => void;
}) {
  const chat = useAssistantChat(base, canWrite);
  const [citation, setCitation] = useState<Publication | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const nearBottom = useRef(true);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const lastConversation = useRef(chat.selected);
  const pendingHere = chat.pending?.origin === chat.selected;
  const scrollToEnd = () => {
    const element = scroller.current;
    if (element) element.scrollTop = element.scrollHeight;
    nearBottom.current = true;
    setAtBottom(true);
  };
  useEffect(() => {
    // Empty conversations start at the introduction, even when it is taller than the viewport.
    if (!chat.messages?.length && !pendingHere) {
      if (scroller.current) scroller.current.scrollTop = 0;
      lastConversation.current = chat.selected;
      nearBottom.current = true;
      setAtBottom(true);
      return;
    }
    if (lastConversation.current !== chat.selected) {
      lastConversation.current = chat.selected;
      scrollToEnd();
    } else if (nearBottom.current) {
      const element = scroller.current;
      if (element) element.scrollTop = element.scrollHeight;
    }
  }, [chat.selected, chat.messages, chat.pending, pendingHere]);
  const insert = (query: string) => {
    chat.setDraft(chat.draft.trim() ? `${chat.draft}\n${query}` : query);
    input.current?.focus();
  };
  const title =
    chat.selected === "new"
      ? "新会话"
      : (chat.conversations?.find((row) => row.id === chat.selected)?.title ?? "历史会话");
  return (
    <div className="relative flex h-full min-h-0 min-w-0 flex-1 overflow-hidden rounded-lg border border-subtle bg-surface-1">
      <AssistantConversations
        rows={chat.conversations}
        selected={chat.selected}
        drafts={chat.drafts}
        pendingOrigin={chat.pending?.origin}
        loading={chat.conversationsLoading}
        error={!!chat.conversationsError}
        onRetry={() => void chat.refreshConversations()}
        onSelect={chat.select}
        onClose={() => setMobileOpen(false)}
        mobileOpen={mobileOpen}
      />
      <section
        aria-label="知识问答"
        className={`${mobileOpen ? "hidden md:flex" : "flex"} min-h-0 min-w-0 flex-1 flex-col`}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-subtle px-4 py-3">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            aria-label="打开会话列表"
            aria-expanded={mobileOpen}
            className="rounded p-1 text-secondary hover:bg-layer-1 md:hidden"
          >
            <List className="size-4" />
          </button>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-14 font-medium" title={title}>
              {title}
            </h2>
            <p className="mt-0.5 text-11 text-tertiary">基于本项目已发布知识 · 回答附可核对来源</p>
          </div>
          {chat.selected !== "new" && (
            <button
              type="button"
              aria-label="刷新当前会话"
              onClick={() => void chat.refreshMessages()}
              className="shrink-0 rounded p-1.5 text-secondary hover:bg-layer-1"
            >
              <RefreshCw className="size-3.5" />
            </button>
          )}
          {chat.status?.configured && (
            <span className="shrink-0 rounded border border-subtle px-2 py-1 text-11 text-secondary">已连接</span>
          )}
        </header>
        {!chat.status?.configured && (
          <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-subtle bg-layer-1 px-4 py-2.5 text-12 text-secondary">
            <span className="min-w-0 flex-1">
              {chat.statusError
                ? "暂时无法读取模型状态"
                : chat.status
                  ? "尚未连接模型，可先写下问题或查阅知识。"
                  : "正在检查模型配置…"}
            </span>
            {chat.statusError && (
              <button
                type="button"
                className="text-accent-primary hover:underline"
                onClick={() => void chat.refreshStatus()}
              >
                重试
              </button>
            )}
            <button
              type="button"
              className="flex items-center gap-1 text-accent-primary hover:underline"
              onClick={() => onNavigate("search")}
            >
              <BookOpen className="size-3.5" />
              知识库
            </button>
            {canConfigure && (
              <button
                type="button"
                className="flex items-center gap-1 text-accent-primary hover:underline"
                onClick={() => onNavigate("settings")}
              >
                <Settings className="size-3.5" />
                模型配置
              </button>
            )}
          </div>
        )}
        <div
          ref={scroller}
          onScroll={() => {
            const node = scroller.current;
            if (node) {
              nearBottom.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
              setAtBottom(nearBottom.current);
            }
          }}
          className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain"
          tabIndex={0}
          aria-label="对话记录"
          aria-busy={chat.messagesLoading}
        >
          <div className="mx-auto w-full max-w-[1200px] space-y-8 px-4 py-6 sm:px-6">
            {chat.messagesError ? (
              <div role="alert" className="rounded-md border border-subtle p-4 text-13 text-secondary">
                对话加载失败：{errorMessage(chat.messagesError)}
                <button
                  type="button"
                  onClick={() => void chat.refreshMessages()}
                  className="ml-2 text-accent-primary underline"
                >
                  重新加载
                </button>
              </div>
            ) : chat.messagesLoading ? (
              <div role="status" className="space-y-3 py-4">
                <p className="text-12 text-secondary">正在加载对话…</p>
                <div className="h-12 animate-pulse rounded-md bg-layer-1" />
                <div className="h-24 animate-pulse rounded-md bg-layer-1" />
              </div>
            ) : chat.messages?.length ? (
              chat.messages.map((message) => (
                <AssistantMessage
                  key={message.id}
                  message={message}
                  canWrite={canWrite}
                  feedbackBusy={chat.feedbackBusy}
                  onFeedback={(row, value) => void chat.feedback(row, value)}
                  onCitation={setCitation}
                  onRetry={insert}
                />
              ))
            ) : (
              !pendingHere && (
                <div className="py-1">
                  <h3 className="flex items-center gap-2 text-16 font-semibold">
                    <MessageSquare className="size-4 text-secondary" />
                    从一个具体问题开始
                  </h3>
                  <p className="mt-2 text-13 leading-6 text-secondary">
                    描述现象、错误码和环境，助手会从项目知识中寻找依据，给出建议与验证步骤。
                  </p>
                  <p className="mt-3 text-11 text-tertiary">试试这些问题，点击后可继续补充</p>
                  <div className="mt-2 flex flex-wrap items-start gap-2">
                    {examples.map((example) => (
                      <button
                        type="button"
                        key={example}
                        onClick={() => insert(example)}
                        className="max-w-full rounded-md border border-subtle px-3 py-2 text-left text-12 text-secondary hover:bg-layer-1"
                      >
                        {example}
                        <span aria-hidden="true" className="ml-2 text-tertiary">
                          ↗
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )
            )}
            {pendingHere && (
              <div role="status" className="space-y-4">
                <div className="ml-auto max-w-full rounded-lg border border-subtle bg-layer-1 px-4 py-3 text-13 leading-6 [overflow-wrap:anywhere] break-words whitespace-pre-wrap sm:max-w-[85%]">
                  {chat.pending?.query}
                </div>
                <p className="flex items-center gap-2 text-12 text-secondary">
                  <span className="size-2 animate-pulse rounded-full bg-accent-primary" />
                  正在检索知识并等待模型完整回答…
                </p>
                <p className="text-11 text-tertiary">可以切换会话，回答会保存在当前会话中。</p>
              </div>
            )}
          </div>
        </div>
        {!atBottom && !!chat.messages?.length && (
          <div className="flex justify-center">
            <button
              type="button"
              onClick={scrollToEnd}
              className="my-1 flex items-center gap-1 rounded border border-subtle bg-surface-1 px-3 py-1 text-11 text-secondary"
            >
              <ArrowDown className="size-3" />
              回到最新消息
            </button>
          </div>
        )}
        <AssistantComposer chat={chat} canWrite={canWrite} inputRef={input} onBeforeSend={scrollToEnd} />
      </section>
      {citation && <PublicationDetail value={citation} onClose={() => setCitation(null)} />}
    </div>
  );
}
