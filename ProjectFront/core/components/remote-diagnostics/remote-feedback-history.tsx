// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { renderNumericDateTime } from "@plane/utils";
import { reportSections } from "../quality/report-summary";

type Reply = { id: string; content: string; created_at: string };
export function RemoteFeedbackHistory({
  replies,
  page,
  feedbackId,
}: {
  replies: Reply[];
  page: number;
  feedbackId: string;
}) {
  const [expanded, setExpanded] = useState<{ key: string; id: string | null } | null>(null);
  const latestKey = `${feedbackId}:${replies[0]?.id || ""}`;
  const expandedId = expanded?.key === latestKey ? expanded.id : replies[0]?.id;
  return (
    <div className="space-y-2">
      {replies.slice((page - 1) * 3, page * 3).map((reply) => {
        const header = reply.content.split("\n")[0];
        const repaired = header === "Agent 远程处理：已修复";
        const verified = header === "Agent 远程处理：验证通过";
        const open = expandedId === reply.id;
        return (
          <div key={reply.id} className="rounded border border-subtle bg-surface-1 px-3 py-2">
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setExpanded({ key: latestKey, id: open ? null : reply.id })}
              className="w-full cursor-pointer text-left text-12"
            >
              <span className={repaired || verified ? "text-success-primary" : "text-warning-primary"}>
                {repaired ? "已修复" : verified ? "验证正常" : "需跟进"}
              </span>
              <time className="ml-3 text-secondary" dateTime={reply.created_at}>
                {renderNumericDateTime(reply.created_at)}
              </time>
            </button>
            {open && (
              <div className="mt-3 space-y-3">
                <dl className="space-y-3 text-12">
                  {reportSections(reply.content).map((section) => (
                    <div key={section.label} className="grid gap-1 sm:grid-cols-[3rem_minmax(0,1fr)] sm:gap-3">
                      <dt className="text-secondary">{section.label}</dt>
                      <dd className="leading-6 break-words whitespace-pre-wrap">
                        {section.label === "结论" ? (
                          <ul aria-label="处理结论要点" className="list-disc space-y-1 pl-4">
                            {section.text
                              .split(/(?<=[。；！？])\s*/)
                              .filter(Boolean)
                              .map((point) => (
                                <li key={point}>{point}</li>
                              ))}
                          </ul>
                        ) : (
                          section.text
                        )}
                      </dd>
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
      })}
    </div>
  );
}
