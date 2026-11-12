import { useMemo } from "react";
import { v4 as uuidv4 } from "uuid";
import { Button } from "@plane/ui";
import { renderNumericDateTime } from "@plane/utils";
import { Badge } from "./shared";
import type { VerificationItem, VerificationRound } from "./verification-types";
import { verificationStatus } from "./verification-types";
export function VerificationRoundView({
  round,
  onExecute,
}: {
  round: VerificationRound;
  onExecute?: (item: VerificationItem) => void;
}) {
  const caseSteps = useMemo(
    () =>
      new Map(round.items.map((item) => [item.item_id, item.snapshot.steps.map((step) => ({ step, key: uuidv4() }))])),
    [round.items]
  );
  const steps = useMemo(() => round.steps.map((step) => ({ step, key: uuidv4() })), [round.steps]);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-12 text-secondary">
        <span>第 {round.round_no} 轮</span>
        <span>{verificationStatus[round.status] || round.status}</span>
        <span>{round.fixed_build}</span>
        <span>{round.environment}</span>
      </div>
      {round.mode === "manual" ? (
        <ol className="space-y-3">
          {steps.map(({ step, key }, index) => (
            <li key={key} className="text-13">
              <p>
                {index + 1}. {step.action}
              </p>
              <p className="mt-1 text-12 text-secondary">预期：{step.expected}</p>
            </li>
          ))}
        </ol>
      ) : (
        <div className="space-y-2">
          {round.items.map((item) => (
            <details key={item.item_id} className="rounded border border-subtle p-3" open={round.items.length === 1}>
              <summary className="cursor-pointer text-13">
                {item.title} <span className="text-12 text-secondary">v{item.case_version}</span>{" "}
                <Badge value={item.result} />
                {item.stale && <span className="ml-2 text-12 text-danger-primary">用例已更新</span>}
              </summary>
              <ol className="mt-3 space-y-2 text-12">
                {caseSteps.get(item.item_id)?.map(({ step, key }, index) => (
                  <li key={key}>
                    <p>
                      {index + 1}. {step.action}
                    </p>
                    <p className="text-secondary">预期：{step.expected}</p>
                    {item.latest_execution?.step_results[index] && (
                      <p className="mt-1">
                        <Badge value={item.latest_execution.step_results[index].result} />{" "}
                        {item.latest_execution.step_results[index].actual}
                      </p>
                    )}
                  </li>
                ))}
              </ol>
              {item.latest_execution && (
                <div className="mt-3 space-y-1 text-12">
                  <p className="whitespace-pre-wrap">{item.latest_execution.actual_result}</p>
                  {item.latest_execution.evidence && (
                    <p className="whitespace-pre-wrap text-secondary">证据：{item.latest_execution.evidence}</p>
                  )}
                  <p className="text-secondary">
                    {item.latest_execution.executor} · {renderNumericDateTime(item.latest_execution.created_at)}
                  </p>
                </div>
              )}
              {onExecute && round.can_record && !item.stale && (
                <Button type="button" size="sm" variant="neutral-primary" onClick={() => onExecute(item)}>
                  {item.latest_execution ? "重新执行" : "执行用例"}
                </Button>
              )}
            </details>
          ))}
          <p className="text-12 text-secondary">
            共 {round.summary.total} 条 · 通过 {round.summary.passed} · 失败 {round.summary.failed} · 未执行{" "}
            {round.summary.pending}
          </p>
        </div>
      )}
      {round.mode === "manual" && round.manual_results.length > 0 && (
        <div className="space-y-2 border-t border-subtle pt-3">
          {round.manual_results.map((result) => (
            <div key={result.id} className="text-13">
              <Badge value={result.result} />
              <p className="mt-1 whitespace-pre-wrap">{result.actual_result}</p>
              <p className="mt-1 text-12 whitespace-pre-wrap text-secondary">证据：{result.evidence}</p>
              {!!result.step_results?.length && (
                <details className="mt-2 text-12">
                  <summary className="cursor-pointer text-secondary">各步骤结果</summary>
                  <ul className="mt-2 space-y-1">
                    {steps.map(({ step, key }, index) => (
                      <li key={key}>
                        {step.action}：<Badge value={result.step_results[index]?.result || "pending"} />{" "}
                        {result.step_results[index]?.actual || "未记录"}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {result.next_action && <p className="mt-2 text-12 text-secondary">下一步：{result.next_action}</p>}
              <p className="mt-1 text-12 text-secondary">{renderNumericDateTime(result.created_at)}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
