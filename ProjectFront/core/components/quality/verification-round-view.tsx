import { Button } from "@plane/ui";
import { renderNumericDateTime } from "@plane/utils";
import { Badge } from "./shared";
import { VerificationStepsTable } from "./verification-steps-table";
import type { VerificationItem, VerificationRound } from "./verification-types";
import { verificationStatus, verificationStatusTone } from "./verification-types";

type ManualResult = VerificationRound["manual_results"][number];
function ManualResultContent({
  result,
  round,
  onResultChange,
}: {
  result: ManualResult;
  round: VerificationRound;
  onResultChange?: (index: number, result: string) => void;
}) {
  return (
    <div className="space-y-3">
      <VerificationStepsTable steps={round.steps} results={result.step_results} onResultChange={onResultChange} />
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2 rounded-md border border-subtle px-3 py-3 text-12">
        <span className="text-secondary">验证证据</span>
        <p className="min-w-0 flex-1 break-words whitespace-pre-wrap">{result.evidence || "未记录"}</p>
      </div>
      <p className="text-13 break-words whitespace-pre-wrap">{result.actual_result}</p>
      {result.next_action && <p className="text-12 text-secondary">下一步：{result.next_action}</p>}
    </div>
  );
}
export function VerificationRoundView({
  round,
  onExecute,
  showStatus = true,
  members = [],
  onManualResultChange,
}: {
  round: VerificationRound;
  onExecute?: (item: VerificationItem, stepIndex?: number, result?: string) => void;
  onManualResultChange?: (stepIndex: number, result: string) => void;
  showStatus?: boolean;
  members?: { id: string; name: string }[];
}) {
  const latest = round.manual_results[0];
  const submit = round.events.find((event) => event.action === "submit");
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-subtle pb-4 text-12 text-secondary">
        <span>
          轮次 <strong className="ml-1.5 font-medium text-primary">第 {round.round_no} 轮</strong>
        </span>
        <span>
          验证版本 <strong className="ml-1.5 font-medium text-primary">{round.fixed_build}</strong>
        </span>
        <span>
          环境 <strong className="ml-1.5 font-medium text-primary">{round.environment}</strong>
        </span>
        {showStatus && (
          <Badge
            value={verificationStatusTone[round.status] || "neutral"}
            label={verificationStatus[round.status] || round.status}
          />
        )}
      </div>
      {round.mode === "manual" ? (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-13 font-medium">验证结果</h3>
              <Badge value={latest?.result || "pending"} />
            </div>
            {latest && (
              <span className="text-12 text-secondary">
                {latest.created_by_name ||
                  members.find((member) => member.id === latest.created_by_id)?.name ||
                  "执行人未记录"}{" "}
                · {renderNumericDateTime(latest.created_at)}
              </span>
            )}
          </div>
          {latest ? (
            <ManualResultContent result={latest} round={round} onResultChange={onManualResultChange} />
          ) : (
            <VerificationStepsTable steps={round.steps} onResultChange={onManualResultChange} />
          )}
          {round.manual_results.length > 1 && (
            <details className="border-t border-subtle pt-3">
              <summary className="cursor-pointer text-12 text-secondary">
                此前结果（{round.manual_results.length - 1}）
              </summary>
              <div className="mt-3 space-y-3">
                {round.manual_results.slice(1).map((result) => (
                  <details key={result.id} className="rounded-md border border-subtle p-3">
                    <summary className="cursor-pointer text-12">
                      <Badge value={result.result} />{" "}
                      <span className="ml-2 text-secondary">{renderNumericDateTime(result.created_at)}</span>
                    </summary>
                    <div className="mt-3">
                      <ManualResultContent result={result} round={round} />
                    </div>
                  </details>
                ))}
              </div>
            </details>
          )}
        </section>
      ) : (
        <section className="space-y-3">
          <h3 className="text-13 font-medium">验证用例</h3>
          <div className="flex flex-wrap gap-2" aria-label="执行结果汇总">
            <Badge value="neutral" label={`共 ${round.summary.total} 条`} />
            <Badge value={round.summary.passed ? "passed" : "neutral"} label={`通过 ${round.summary.passed}`} />
            <Badge value={round.summary.failed ? "failed" : "neutral"} label={`失败 ${round.summary.failed}`} />
            <Badge value="neutral" label={`未执行 ${round.summary.pending}`} />
            {round.summary.blocked > 0 && <Badge value="blocked" label={`受阻 ${round.summary.blocked}`} />}
            {round.summary.inconclusive > 0 && (
              <Badge value="inconclusive" label={`无法判定 ${round.summary.inconclusive}`} />
            )}
            {round.summary.skipped > 0 && <Badge value="neutral" label={`跳过 ${round.summary.skipped}`} />}
          </div>
          {round.items.map((item) => (
            <details
              key={item.item_id}
              className="rounded-md border border-subtle"
              open={round.items.length === 1 || item.result === "failed" || item.result === "blocked"}
            >
              <summary className="cursor-pointer px-3 py-3 text-13">
                <span className="inline-flex max-w-full flex-wrap items-center gap-2 align-middle">
                  <strong className="font-medium break-words">{item.title}</strong>
                  <span className="text-12 text-secondary">
                    v{item.case_version} · {item.snapshot.steps.length} 个步骤
                  </span>
                  <Badge value={item.result} />
                  {item.stale && <Badge value="inconclusive" label="用例已更新" />}
                </span>
              </summary>
              <div className="space-y-3 border-t border-subtle p-3">
                <VerificationStepsTable
                  steps={item.snapshot.steps}
                  results={item.latest_execution?.step_results}
                  onResultChange={
                    onExecute && round.can_record && !item.stale
                      ? (index, result) => onExecute(item, index, result)
                      : undefined
                  }
                />
                {item.latest_execution && (
                  <div className="space-y-2 text-12">
                    <p className="break-words whitespace-pre-wrap">{item.latest_execution.actual_result}</p>
                    <p className="break-words whitespace-pre-wrap text-secondary">
                      证据：{item.latest_execution.evidence || "未记录"}
                    </p>
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
              </div>
            </details>
          ))}
        </section>
      )}
      {submit && (
        <div className="flex flex-wrap gap-x-4 gap-y-2 rounded-md border border-subtle px-3 py-3 text-12">
          <span className="text-secondary">提交验收</span>
          <span>{submit.actor}</span>
          <span className="text-secondary">{renderNumericDateTime(submit.created_at)}</span>
          {submit.note && <p className="break-words whitespace-pre-wrap text-secondary">{submit.note}</p>}
        </div>
      )}
    </div>
  );
}
