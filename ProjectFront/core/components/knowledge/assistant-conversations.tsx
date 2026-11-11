// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { MessageSquare, Plus, Search, X } from "lucide-react";
import { renderNumericDateTime } from "@plane/utils";
import type { Conversation } from "./types";

type Props = {
  rows: Conversation[] | undefined;
  selected: string;
  drafts: Record<string, string>;
  pendingOrigin?: string;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  onSelect: (id: string) => void;
  onClose: () => void;
  mobileOpen: boolean;
};
export function AssistantConversations({
  rows,
  selected,
  drafts,
  pendingOrigin,
  loading,
  error,
  onRetry,
  onSelect,
  onClose,
  mobileOpen,
}: Props) {
  const [search, setSearch] = useState("");
  const filtered = rows?.filter((row) => row.title.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  const choose = (id: string) => {
    onSelect(id);
    onClose();
  };
  return (
    <aside
      aria-label="问答会话"
      className={`${mobileOpen ? "flex" : "hidden"} absolute inset-0 z-10 min-h-0 w-full flex-col border-r border-subtle bg-surface-1 md:static md:z-auto md:flex md:w-60 md:shrink-0`}
    >
      <div className="flex items-center gap-2 p-4">
        <button
          type="button"
          onClick={() => choose("new")}
          className="focus-visible:outline-accent-primary flex flex-1 items-center justify-center gap-2 rounded-md border border-subtle px-3 py-2 text-13 font-medium hover:bg-layer-1 focus-visible:outline focus-visible:outline-2"
        >
          <Plus className="size-4" />
          新会话
        </button>
        <button
          type="button"
          aria-label="关闭会话列表"
          onClick={onClose}
          className="rounded p-2 hover:bg-layer-1 md:hidden"
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="px-4 pb-3">
        <label className="relative block">
          <Search aria-hidden="true" className="absolute top-2.5 left-2 size-3.5 text-tertiary" />
          <input
            type="search"
            aria-label="搜索会话"
            placeholder="搜索会话"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="focus:border-accent-primary w-full rounded-md border border-subtle bg-transparent py-2 pr-2 pl-7 text-12 outline-none"
          />
        </label>
      </div>
      <h2 className="px-4 pb-2 text-11 font-medium text-tertiary">我的会话{rows ? ` · ${rows.length}` : ""}</h2>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {loading ? (
          <p role="status" className="p-3 text-12 text-secondary">
            正在加载会话…
          </p>
        ) : error ? (
          <div role="alert" className="p-3 text-12 text-secondary">
            会话列表加载失败。
            <button type="button" onClick={onRetry} className="ml-1 text-accent-primary underline">
              重试
            </button>
          </div>
        ) : !filtered?.length ? (
          <p className="p-3 text-12 text-tertiary">{search ? "没有匹配的会话" : "还没有会话，先写下你的问题吧。"}</p>
        ) : (
          filtered.map((row) => (
            <button
              type="button"
              key={row.id}
              onClick={() => choose(row.id)}
              aria-current={selected === row.id ? "true" : undefined}
              className={`focus-visible:outline-accent-primary mb-1 block w-full rounded-md px-3 py-3 text-left focus-visible:outline focus-visible:outline-2 ${selected === row.id ? "bg-layer-1 text-primary" : "text-secondary hover:bg-layer-1"}`}
            >
              <span className="flex items-center gap-2">
                <MessageSquare className="size-3.5 shrink-0" />
                <span className="truncate text-13" title={row.title}>
                  {row.title}
                </span>
              </span>
              <span className="mt-1 block pl-5 text-11 text-tertiary">
                {pendingOrigin === row.id
                  ? "正在回答…"
                  : drafts[row.id]?.trim()
                    ? "有未发送草稿"
                    : renderNumericDateTime(row.created_at)}
              </span>
            </button>
          ))
        )}
      </div>
      {drafts.new?.trim() && selected !== "new" && (
        <button
          type="button"
          onClick={() => choose("new")}
          className="border-t border-subtle px-4 py-3 text-left text-12 text-accent-primary"
        >
          返回新会话草稿
        </button>
      )}
      <p className="border-t border-subtle px-4 py-3 text-11 text-tertiary">会话仅对自己可见</p>
    </aside>
  );
}
