// SPDX-License-Identifier: AGPL-3.0-only
import { useRef } from "react";
import type { RefObject } from "react";
import { ArrowUp } from "lucide-react";
import { Button } from "@plane/ui";
import { shouldSendOnEnter } from "./assistant-state";
import type { useAssistantChat } from "./assistant-use-chat";

export function AssistantComposer({
  chat,
  canWrite,
  inputRef,
  onBeforeSend,
}: {
  chat: ReturnType<typeof useAssistantChat>;
  canWrite: boolean;
  inputRef: RefObject<HTMLTextAreaElement>;
  onBeforeSend: () => void;
}) {
  const composing = useRef(false);
  const pendingHere = chat.pending?.origin === chat.selected;
  return (
    <div className="shrink-0 border-t border-subtle px-4 pt-3 pb-3 sm:px-6">
      <div className="mx-auto max-w-[1200px]">
        {chat.error && (
          <p role="alert" className="mb-2 text-12 text-danger-primary">
            {chat.error} 问题已保留，可检查后重试。
          </p>
        )}
        {chat.pending && !pendingHere && (
          <button
            type="button"
            onClick={() => chat.select(chat.pending!.origin)}
            className="mb-2 text-12 text-accent-primary hover:underline"
          >
            另一个会话正在回答，点击查看
          </button>
        )}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onBeforeSend();
            void chat.send();
          }}
          className="focus-within:border-accent-primary rounded-lg border border-subtle bg-surface-1"
        >
          <label htmlFor="knowledge-question" className="sr-only">
            输入问题，最多2000字
          </label>
          <textarea
            ref={inputRef}
            id="knowledge-question"
            value={chat.draft}
            maxLength={2000}
            rows={3}
            onChange={(event) => chat.setDraft(event.target.value)}
            onCompositionStart={() => {
              composing.current = true;
            }}
            onCompositionEnd={() => {
              composing.current = false;
            }}
            onKeyDown={(event) => {
              if (
                shouldSendOnEnter({
                  key: event.key,
                  shiftKey: event.shiftKey,
                  isComposing: event.nativeEvent.isComposing || composing.current,
                  keyCode: event.nativeEvent.keyCode,
                })
              ) {
                event.preventDefault();
                if (!chat.pending && canWrite && chat.status?.configured && chat.draft.trim())
                  event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder={
              chat.status?.configured ? "继续提问，或补充现象、错误码和环境…" : "先写下问题，连接模型后即可发送…"
            }
            className="block max-h-40 min-h-20 w-full resize-y rounded-t-lg bg-transparent px-3 py-3 text-13 leading-6 outline-none placeholder:text-tertiary"
          />
          <div className="flex items-center justify-between gap-2 px-3 pb-2">
            <span className="text-11 text-tertiary">
              {chat.draft.length}/2000<span className="ml-2 hidden sm:inline">Enter 发送 · Shift + Enter 换行</span>
            </span>
            <Button
              type="submit"
              disabled={!!chat.pending || !canWrite || !chat.status?.configured || !chat.draft.trim()}
            >
              <ArrowUp className="mr-1 size-3.5" />
              {pendingHere ? "等待回答" : chat.error ? "重试发送" : "发送"}
            </Button>
          </div>
        </form>
        <p className="mt-2 text-11 text-tertiary">
          {!canWrite
            ? "当前账号暂无问答权限，可查看已有对话。"
            : "请勿输入密码或密钥；回答仅供参考，请核对引用后操作。"}
        </p>
      </div>
    </div>
  );
}
