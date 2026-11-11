// SPDX-License-Identifier: AGPL-3.0-only
import type { Message } from "./types";

export type ChatAttempt = { origin: string; query: string; request_id: string; conversation_id?: string };

export function prepareAttempt(
  previous: ChatAttempt | undefined,
  origin: string,
  query: string,
  uuid: () => string
): ChatAttempt {
  const text = query.trim();
  if (previous?.origin === origin && previous.query === text) return previous;
  return { origin, query: text, request_id: uuid(), ...(origin !== "new" ? { conversation_id: origin } : {}) };
}

export function mergeMessage(messages: Message[] | undefined, response: Message): Message[] {
  const rows = messages ?? [];
  return rows.some((row) => row.id === response.id)
    ? rows.map((row) => (row.id === response.id ? response : row))
    : [...rows, response];
}

export const clearSentDraft = (draft: string, sent: string): string => (draft.trim() === sent ? "" : draft);

export function shouldSendOnEnter(event: {
  key: string;
  shiftKey: boolean;
  isComposing: boolean;
  keyCode: number;
}): boolean {
  return event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229;
}
