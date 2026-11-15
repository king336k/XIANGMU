import { Button } from "@plane/ui";
import { renderNumericDateTime } from "@plane/utils";
import { Badge } from "./shared";
import { VerificationStepsTable } from "./verification-steps-table";
import { resultNames } from "./types";
import type { VerificationItem, VerificationRound } from "./verification-types";
import { verificationStatus, verificationStatusTone } from "./verification-types";

export function VerificationRoundView({
  round,
  onExecute,
  showStatus = true,
  members = [],
}: {
  round: VerificationRound;
  onExecute?: (item: VerificationItem, stepIndex?: number, result?: string) => void;
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
        {showStatus && (
          <Badge
            value={verificationStatusTone[round.execution_state || round.status] || "neutral"}
            label={verificationStatus[round.execution_state || round.status] || round.status}
          />
        )}
      </div>
      {round.mode === "manual" ? (
        <section className="space-y-3">
          <div>
            <h3 className="text-13 font-medium">执行验证</h3>
            <p className="mt-1 text-12 text-secondary">按要求测试后填写结果</p>
          </div>
          <div className="rounded-md border border-subtle bg-layer-1 p-3">
            <p className="mb-1 text-12 text-secondary">如何测试</p>
            <p className="text-13 whitespace-pre-wrap">
              {round.steps
                .map((step) => step.action)
                .filter(Boolean)
                .join("\n") || "暂未填写测试要求"}
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-13 font-medium">验证结果</h3>
              <Badge value={latest?.result || "pending"} />
            </div>
            {latest && (
              <span className="text-12 text-secondary">
                实际测试人：
                {latest.created_by_name ||
                  members.find((member) => member.id === latest.created_by_id)?.name ||
                  "执行人未记录"}{" "}
                · {renderNumericDateTime(latest.created_at)}
              </span>
            )}
          </div>
          {latest ? (
            <div className="space-y-2 rounded-md border border-subtle p-3">
              <p className="text-13 font-medium">测试结果：{resultNames[latest.result] || latest.result}</p>
              {latest.actual_result && (
                <p className="text-13 whitespace-pre-wrap">
                  <span className="text-secondary">结果说明：</span>
                  {latest.actual_result}
                </p>
              )}
              {latest.evidence && (
                <p className="text-12 whitespace-pre-wrap text-secondary">测试备注：{latest.evidence}</p>
              )}
              {latest.next_action && (
                <p className="text-12 whitespace-pre-wrap text-secondary">下一步：{latest.next_action}</p>
              )}
            </div>
          ) : (
            <p className="rounded-md border border-dashed border-subtle p-3 text-12 text-secondary">
              等待测试员提交测试结果
            </p>
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
                      <span className="ml-2 text-secondary">
                        {result.created_by_name || "执行人未记录"} · {renderNumericDateTime(result.created_at)}
                      </span>
                    </summary>
                    <div className="mt-3">
                      <div className="space-y-2 text-13">
                        <p className="whitespace-pre-wrap">
                          <span className="text-secondary">结果说明：</span>
                          {result.actual_result}
                        </p>
                        {result.evidence && (
                          <p className="text-12 whitespace-pre-wrap text-secondary">测试备注：{result.evidence}</p>
                        )}
                      </div>
                    </div>
                  </details>
                ))}
              </div>
            </details>
          )}
        </section>
      ) : (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-13 font-medium">执行验证</h3>
              <p className="mt-1 text-12 text-secondary">逐条填写结果，完成后提交验收</p>
            </div>
            <Badge
              value={verificationStatusTone[round.execution_state || round.status] || "neutral"}
              label={verificationStatus[round.execution_state || round.status] || round.status}
            />
          </div>
          <h4 className="text-12 font-medium text-secondary">用例执行列表</h4>
          {round.test_requirements && (
            <div className="rounded-md border border-subtle bg-layer-1 p-3 text-13">
              <p className="mb-1 text-12 text-secondary">测试要求</p>
              <p className="whitespace-pre-wrap">{round.test_requirements}</p>
            </div>
          )}
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
            <article key={item.item_id} className="min-w-0 rounded-md border border-subtle">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-subtle px-3 py-2">
                <span className="min-w-0 flex-1 text-13 font-medium break-words">{item.title}</span>
                <Badge value={item.result} />
                {onExecute && round.can_record && !item.stale && (
                  <Button
                    type="button"
                    size="sm"
                    variant={item.latest_execution ? "neutral-primary" : "primary"}
                    onClick={() => onExecute(item)}
                  >
                    {item.latest_execution ? "重新执行" : "执行用例"}
                  </Button>
                )}
              </div>
              <details open={round.items.length === 1 || item.result === "failed" || item.result === "blocked"}>
                <summary className="cursor-pointer px-3 py-3 text-13">
                  <span className="inline-flex max-w-full flex-wrap items-center gap-2 align-middle">
                    <span className="text-12 text-secondary">查看步骤</span>
                    <span className="text-12 text-secondary">
                      {item.source === "round" ? "本轮临时用例" : item.case_version ? `v${item.case_version}` : "用例"}{" "}
                      · {item.snapshot.steps.length} 个步骤
                    </span>
                    {item.stale && <Badge value="inconclusive" label="用例已更新" />}
                  </span>
                </summary>
                <div className="space-y-3 border-t border-subtle p-3">
                  <VerificationStepsTable
                    instructionsOnly={!!item.source && item.source !== "legacy"}
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
                      {item.latest_execution.actual_result !==
                        item.latest_execution.step_results
                          .map((step, index) => `${index + 1}. ${step.actual}`)
                          .join("\n") && (
                        <p className="break-words whitespace-pre-wrap">
                          <span className="text-secondary">测试结果：</span>
                          {item.latest_execution.actual_result}
                        </p>
                      )}
                      {item.latest_execution.evidence && (
                        <p className="break-words whitespace-pre-wrap text-secondary">
                          测试备注：{item.latest_execution.evidence}
                        </p>
                      )}
                      <p className="text-secondary">
                        {item.latest_execution.executor} · {renderNumericDateTime(item.latest_execution.created_at)}
                      </p>
                    </div>
                  )}
                  {(item.execution_history?.length || 0) > 1 && (
                    <details className="border-t border-subtle pt-2">
                      <summary className="cursor-pointer text-12 text-secondary">
                        历史执行（{item.execution_history!.length - 1}）
                      </summary>
                      <div className="mt-2 space-y-2">
                        {item.execution_history!.slice(1).map((execution) => (
                          <div key={execution.id} className="rounded border border-subtle p-2 text-12">
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge value={execution.result} />
                              <span className="text-secondary">
                                {execution.executor} · {renderNumericDateTime(execution.created_at)}
                              </span>
                            </div>
                            {execution.actual_result && (
                              <p className="mt-1 whitespace-pre-wrap">
                                <span className="text-secondary">测试结果：</span>
                                {execution.actual_result}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
              </details>
            </article>
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
