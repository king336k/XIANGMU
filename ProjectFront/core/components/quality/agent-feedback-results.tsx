import { sortBy } from "lodash-es";
// SPDX-License-Identifier: AGPL-3.0-only
import useSWR from "swr";
import { useState } from "react";
import { renderNumericDateTime } from "@plane/utils";
import { qualityApi, errorMessage } from "./api";
import { AgentFeedbackActions } from "./agent-feedback-actions";
import { reportSections } from "./report-summary";

type Reply = { id: string; visibility: string; content: string; created_at: string };
const prefix = "Agent 远程处理：";

export function AgentFeedbackResults({
  base,
  defectId,
  active,
  onHistory,
  onCompleted,
}: {
  base: string;
  defectId: string;
  active: boolean;
  onHistory?: () => void;
  onCompleted?: () => void;
}) {
  const url = `${base}defects/${defectId}/collaboration/`;
  const { data, error, mutate } = useSWR(active ? url : null, () => qualityApi.all<Reply>(url), {
    refreshInterval: active ? 10000 : 0,
  });
  const results = sortBy(
    (data || []).filter((reply) => reply.visibility === "public" && reply.content.startsWith(prefix)),
    (reply) => -Date.parse(reply.created_at)
  );
  const [expanded, setExpanded] = useState<{ key: string; id: string | null } | null>(null);
  const latestKey = `${defectId}:${results[0]?.id || ""}`;
  const expandedId = expanded?.key === latestKey ? expanded.id : results[0]?.id;
  return (
    <section aria-label="Agent 现场处理" className="mt-5 space-y-3 rounded-md border border-subtle p-4">
      <header className="flex items-center justify-between gap-3">
        <h3 className="text-14 font-semibold">Agent 现场处理</h3>
        <button type="button" onClick={() => void mutate()} className="text-12 text-accent-primary">
          刷新结果
        </button>
      </header>
      <p className="text-12 text-secondary">现场检查、执行操作及复测结果；同一条回复也会同步至 DAQ 异常反馈。</p>
      <AgentFeedbackActions
        defectId={defectId}
        active={active}
        onHistory={onHistory || (() => {})}
        onCompleted={() => {
          void mutate();
          onCompleted?.();
        }}
      />
      {error ? (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      ) : !data ? (
        <p role="status" className="text-13 text-secondary">
          正在读取处理结果…
        </p>
      ) : !results.length ? (
        <p className="text-13 text-secondary">暂无 Agent 现场处理结果。</p>
      ) : (
        results.map((reply) => {
          const [status] = reply.content.slice(prefix.length).split("\n");
          const repaired = status.trim() === "已修复";
          const verified = status.trim() === "验证通过";
          return (
            <div key={reply.id} className="rounded border border-subtle px-3 py-2">
              <button
                type="button"
                aria-expanded={expandedId === reply.id}
                onClick={() => setExpanded({ key: latestKey, id: expandedId === reply.id ? null : reply.id })}
                className="w-full cursor-pointer text-left text-13"
              >
                <span
                  className={
                    repaired || verified ? "font-medium text-success-primary" : "font-medium text-warning-primary"
                  }
                >
                  {status}
                </span>
                <time dateTime={reply.created_at} className="ml-3 text-12 text-secondary">
                  {renderNumericDateTime(reply.created_at)}
                </time>
              </button>
              {expandedId === reply.id && (
                <div className="mt-3 space-y-3">
                  <dl className="space-y-2 text-13">
                    {reportSections(reply.content).map((section) => (
                      <div key={section.label} className="grid gap-1 sm:grid-cols-[3rem_minmax(0,1fr)] sm:gap-3">
                        <dt className="text-12 text-secondary">{section.label}</dt>
                        <dd className="leading-6 break-words whitespace-pre-wrap">{section.text}</dd>
                      </div>
                    ))}
                  </dl>
                  <details className="border-t border-subtle pt-2">
                    <summary className="cursor-pointer text-12 text-secondary">详细证据与处理过程</summary>
                    <pre className="font-sans mt-2 max-h-96 overflow-auto text-12 leading-6 break-words whitespace-pre-wrap">
                      {reply.content}
                    </pre>
                  </details>
                </div>
              )}
            </div>
          );
        })
      )}
    </section>
  );
}
