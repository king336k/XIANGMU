import { v4 as uuidv4 } from "uuid";
// SPDX-License-Identifier: AGPL-3.0-only
import { useRef, useState } from "react";
import { isAxiosError } from "axios";
import useSWR, { useSWRConfig } from "swr";
import { qualityApi, errorMessage } from "@/components/quality/api";
import type { Conversation, Message } from "./types";
import { clearSentDraft, mergeMessage, prepareAttempt } from "./assistant-state";
import type { ChatAttempt } from "./assistant-state";

type AssistantStatus = { configured: boolean; model: string; message: string };
export function useAssistantChat(base: string, canWrite: boolean) {
  const { mutate: mutateCache } = useSWRConfig();
  const [selected, setSelected] = useState("new");
  const selectedRef = useRef(selected);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<ChatAttempt | null>(null);
  const inFlight = useRef(false);
  const attempts = useRef<Record<string, ChatAttempt | undefined>>({});
  const [feedbackBusy, setFeedbackBusy] = useState("");
  const {
    data: status,
    error: statusError,
    mutate: refreshStatus,
  } = useSWR(`${base}status/`, (url: string) => qualityApi.read<AssistantStatus>(url));
  const {
    data: conversations,
    error: conversationsError,
    isLoading: conversationsLoading,
    mutate: refreshConversations,
  } = useSWR(`${base}conversations/all`, () => qualityApi.all<Conversation>(`${base}conversations/`));
  const messageKey = (id: string) => `${base}conversations/${id}/all`;
  const {
    data: messages,
    error: messagesError,
    isLoading: messagesLoading,
    mutate: refreshMessages,
  } = useSWR(selected === "new" ? null : messageKey(selected), () =>
    qualityApi.all<Message>(`${base}conversations/${selected}/`)
  );
  const select = (id: string) => {
    selectedRef.current = id;
    setSelected(id);
  };
  const setDraft = (value: string) => {
    setDrafts((previous) => ({ ...previous, [selected]: value }));
    setErrors((previous) => ({ ...previous, [selected]: "" }));
  };
  const send = async () => {
    const origin = selectedRef.current;
    const query = drafts[origin]?.trim();
    if (inFlight.current || !query || !canWrite || !status?.configured) return;
    const attempt = prepareAttempt(attempts.current[origin], origin, query, () => uuidv4());
    attempts.current[origin] = attempt;
    inFlight.current = true;
    setPending(attempt);
    setErrors((previous) => ({ ...previous, [origin]: "" }));
    try {
      const { origin: _origin, ...payload } = attempt;
      const response = await qualityApi.write<Message>(`${base}chat/`, payload);
      // Seed the response's actual key before selecting it; the previous SWR hook may still be unbound.
      await mutateCache(
        messageKey(response.conversation_id),
        (rows: Message[] | undefined) => mergeMessage(rows, response),
        { revalidate: false }
      );
      const stillSelected = selectedRef.current === origin;
      setDrafts((previous) => {
        const remaining = clearSentDraft(previous[origin] ?? "", attempt.query);
        // Keep text written while a first answer was pending with the newly created conversation.
        if (origin === "new" && stillSelected)
          return {
            ...previous,
            new: "",
            [response.conversation_id]: remaining,
          };
        return { ...previous, [origin]: remaining };
      });
      delete attempts.current[origin];
      if (selectedRef.current === origin) select(response.conversation_id);
      await mutateCache(
        `${base}conversations/all`,
        (rows: Conversation[] | undefined) => {
          const current = rows ?? [];
          return current.some((row) => row.id === response.conversation_id)
            ? current
            : [{ id: response.conversation_id, title: attempt.query, created_at: response.created_at }, ...current];
        },
        { revalidate: false }
      );
      // List refresh failures must never turn a successfully saved answer into a retry.
      void refreshConversations().catch(() => undefined);
    } catch (error) {
      // A transport failure can hide a saved answer: retain its ID for a safe retry.
      // A confirmed terminal model failure needs a fresh attempt (the API never reruns failed IDs).
      if (isAxiosError(error) && error.response?.status === 502 && error.response.data?.code)
        delete attempts.current[origin];
      setErrors((previous) => ({ ...previous, [origin]: errorMessage(error) }));
      void refreshConversations().catch(() => undefined);
      if (origin !== "new") void mutateCache(messageKey(origin)).catch(() => undefined);
    } finally {
      inFlight.current = false;
      setPending(null);
    }
  };
  const feedback = async (message: Message, value: string) => {
    if (feedbackBusy || !canWrite) return;
    const origin = message.conversation_id;
    setFeedbackBusy(message.id);
    try {
      const response = await qualityApi.write<Message>(`${base}messages/${message.id}/feedback/`, { feedback: value });
      await mutateCache(messageKey(origin), (rows: Message[] | undefined) => mergeMessage(rows, response), {
        revalidate: false,
      });
    } catch (error) {
      setErrors((previous) => ({ ...previous, [origin]: errorMessage(error) }));
    } finally {
      setFeedbackBusy("");
    }
  };
  return {
    selected,
    select,
    draft: drafts[selected] ?? "",
    setDraft,
    drafts,
    status,
    statusError,
    refreshStatus,
    conversations,
    conversationsError,
    conversationsLoading,
    refreshConversations,
    messages,
    messagesError,
    messagesLoading,
    refreshMessages,
    pending,
    error: errors[selected],
    send,
    feedback,
    feedbackBusy,
  };
}
