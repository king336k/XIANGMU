import { useEffect, useState } from "react";
import useSWR from "swr";
import { v4 as uuidv4 } from "uuid";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Badge, Field, fieldClass, Modal } from "./shared";
import { can } from "./types";
import type { Context, Defect } from "./types";
import { ExecutionForm } from "./execution-form";
import { VerificationConfigure } from "./verification-configure";
import { VerificationManualResult } from "./verification-manual-result";
import { VerificationRoundView } from "./verification-round-view";
import type { VerificationData, VerificationItem, VerificationRound } from "./verification-types";
import { verificationStatus, verificationStatusTone } from "./verification-types";
const actionLabels: Record<string, string> = {
  submit: "提交验收",
  accept: "验收关闭",
  return_test: "退回补测",
  return_repair: "退回修复",
  reopen: "重新打开",
};
export function DefectVerificationScope({
  base,
  value,
  context,
  onChanged,
}: {
  base: string;
  value: Defect;
  context: Context;
  projectUrl: string;
  onChanged: (value: Defect) => Promise<void>;
}) {
  const endpoint = `${base}defects/${value.id}/verification/`;
  const { data, error, mutate } = useSWR(endpoint, (url: string) => qualityApi.read<VerificationData>(url));
  useEffect(() => {
    void mutate();
  }, [value.edit_version, mutate]);
  const [editing, setEditing] = useState(false);
  const [initialMode, setInitialMode] = useState<"manual" | "cases">("manual");
  const [recording, setRecording] = useState<{ round: VerificationRound; stepIndex?: number; result?: string }>();
  const [executing, setExecuting] = useState<{
    item: VerificationItem;
    round: VerificationRound;
    stepIndex?: number;
    result?: string;
  }>();
  const [action, setAction] = useState<{ key: string; requestId: string; round: VerificationRound }>();
  const round = data?.current;
  const retiredRound = !!round && ["returned_repair", "reopened", "superseded"].includes(round.status);
  const readyForNewRound =
    !!round &&
    (retiredRound || (!!round.fixed_build && round.fixed_build !== value.fixed_build)) &&
    data?.defect_status === "resolved";
  const canConfigure = round
    ? round.can_configure
    : value.status !== "closed" && ["manage_test_plan", "manage_defect", "solution"].some((cap) => can(context, cap));
  const update = async (result: VerificationData) => {
    await mutate(result, false);
    setEditing(false);
    setRecording(undefined);
    setExecuting(undefined);
    await onChanged(await qualityApi.read<Defect>(`${base}defects/${value.id}/`));
  };
  const start = (mode: "manual" | "cases") => {
    setInitialMode(mode);
    setEditing(true);
  };
  if (error)
    return (
      <p role="alert" className="text-13 text-danger-primary">
        {errorMessage(error)}{" "}
        <button type="button" onClick={() => void mutate()} className="text-accent-primary">
          重试
        </button>
      </p>
    );
  if (!data)
    return (
      <p role="status" className="text-13 text-secondary">
        正在加载…
      </p>
    );
  return (
    <section className="space-y-5">
      {editing ? (
        <VerificationConfigure
          key={round?.id || "new"}
          base={base}
          defectId={value.id}
          version={data.defect_version}
          fixedBuild={value.fixed_build || ""}
          initial={round ? (readyForNewRound ? { ...round, fixed_build: value.fixed_build } : round) : undefined}
          initialMode={initialMode}
          onSaved={update}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-13 font-medium">
                {round ? (round.mode === "manual" ? "人工验证" : "用例回归") : "尚未安排"}
              </p>
              {round && (
                <Badge
                  value={readyForNewRound ? "pending" : verificationStatusTone[round.status] || "neutral"}
                  label={readyForNewRound ? "待重新安排" : verificationStatus[round.status] || round.status}
                />
              )}
            </div>
            {round &&
              (canConfigure || ["manage_test_plan", "manage_defect", "solution"].some((cap) => can(context, cap))) && (
                <Button
                  type="button"
                  variant="neutral-primary"
                  size="sm"
                  disabled={!canConfigure}
                  onClick={() => start(round.mode)}
                >
                  {retiredRound ? "重新安排" : "修改安排"}
                </Button>
              )}
          </div>
          {!round && canConfigure && (
            <div role="group" aria-label="选择验证方式" className="flex flex-wrap gap-2">
              <Button type="button" variant="neutral-primary" onClick={() => start("manual")}>
                人工验证
              </Button>
              <Button type="button" variant="neutral-primary" onClick={() => start("cases")}>
                用例回归
              </Button>
            </div>
          )}
          {round && (
            <>
              {readyForNewRound && (
                <p className="text-12 text-secondary">当前修复版本：{value.fixed_build}；以下为上一轮结果。</p>
              )}
              <VerificationRoundView
                round={round}
                onExecute={(item, stepIndex, result) => setExecuting({ item, round, stepIndex, result })}
                onManualResultChange={
                  round.can_record ? (stepIndex, result) => setRecording({ round, stepIndex, result }) : undefined
                }
                showStatus={false}
                members={context.members}
              />
              {data.defect_status !== "resolved" && data.defect_status !== "closed" && (
                <p className="text-12 text-secondary">修复后可提交验证结果。</p>
              )}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-subtle pt-4">
                <span className="text-12 text-secondary">
                  {round.status === "review"
                    ? "待项目经理 / 管理员验收"
                    : round.can_record
                      ? round.summary.pending
                        ? `未执行 ${round.summary.pending} 项`
                        : "验证结果已记录"
                      : round.status === "accepted"
                        ? "验收完成"
                        : ""}
                </span>
                <div className="flex flex-wrap items-center gap-2">
                  {round.mode === "manual" && round.can_record && (
                    <Button type="button" onClick={() => setRecording({ round })}>
                      记录结果
                    </Button>
                  )}
                  {(
                    [
                      ["return_repair", round.can_return_repair],
                      ["return_test", round.can_return_test],
                      ["submit", round.can_submit],
                      ["accept", round.can_accept || (round.status === "review" && round.can_return_test)],
                      ["reopen", round.can_reopen],
                    ] as const
                  )
                    .filter(([, allowed]) => allowed)
                    .map(([key]) => (
                      <Button
                        key={key}
                        type="button"
                        variant={key === "accept" || key === "submit" ? "primary" : "neutral-primary"}
                        disabled={
                          (key === "submit" && !!round.summary.pending) ||
                          (key === "accept" &&
                            (!round.can_accept || !round.summary.total || round.summary.passed !== round.summary.total))
                        }
                        className={key === "return_repair" ? "text-danger-primary" : undefined}
                        onClick={() => setAction({ key, requestId: uuidv4(), round })}
                      >
                        {actionLabels[key]}
                      </Button>
                    ))}
                </div>
              </div>
            </>
          )}
        </>
      )}
      {!!data.history.length && (
        <details className="border-t border-subtle pt-3">
          <summary className="cursor-pointer text-13 text-secondary">历史验证（{data.history.length}）</summary>
          <div className="mt-3 space-y-3">
            {data.history.map((old) => (
              <details key={old.id} className="rounded border border-subtle p-3">
                <summary className="cursor-pointer text-13">
                  第 {old.round_no} 轮 · {old.mode === "manual" ? "人工验证" : "用例回归"} ·{" "}
                  {verificationStatus[old.status] || old.status}
                </summary>
                <div className="mt-3">
                  <VerificationRoundView round={old} members={context.members} />
                </div>
              </details>
            ))}
          </div>
        </details>
      )}
      {recording && round && (
        <VerificationManualResult
          base={base}
          defectId={value.id}
          round={recording.round}
          initialStepIndex={recording.stepIndex}
          initialResult={recording.result}
          onSaved={update}
          onClose={() => setRecording(undefined)}
        />
      )}
      {executing && round && (
        <ExecutionForm
          base={base}
          stepResultsOnly
          initialExecution={executing.item.latest_execution}
          initialStepIndex={executing.stepIndex}
          initialResult={executing.result}
          plan={{
            name: `第 ${executing.round.round_no} 轮验证`,
            build: executing.round.fixed_build,
            environment: executing.round.environment,
          }}
          item={{
            id: executing.item.item_id,
            revision: {
              snapshot: executing.item.snapshot,
              title: executing.item.title,
              version: executing.item.case_version,
            },
          }}
          onClose={() => setExecuting(undefined)}
          onSaved={async () => {
            setExecuting(undefined);
            await mutate();
            await onChanged(await qualityApi.read<Defect>(`${base}defects/${value.id}/`));
          }}
        />
      )}
      {action && round && (
        <Modal
          title={actionLabels[action.key]}
          submitLabel={actionLabels[action.key]}
          onClose={() => setAction(undefined)}
          onSubmit={async (form) => {
            await update(
              await qualityApi.write<VerificationData>(`${endpoint}workflow/`, {
                expected_version: action.round.version,
                request_id: action.requestId,
                action: action.key,
                comment: form.get("comment") || "",
              })
            );
            setAction(undefined);
          }}
        >
          {["submit", "accept"].includes(action.key) && (
            <div className="flex flex-wrap gap-2 text-12">
              <Badge value="neutral" label={`版本 ${action.round.fixed_build}`} />
              <Badge
                value={action.round.summary.passed ? "passed" : "neutral"}
                label={`通过 ${action.round.summary.passed}/${action.round.summary.total}`}
              />
              {action.round.summary.failed > 0 && (
                <Badge value="failed" label={`失败 ${action.round.summary.failed}`} />
              )}
            </div>
          )}
          <Field label={["return_test", "return_repair", "reopen"].includes(action.key) ? "原因" : "验收说明（选填）"}>
            <textarea
              name="comment"
              required={["return_test", "return_repair", "reopen"].includes(action.key)}
              rows={3}
              maxLength={4000}
              className={fieldClass}
            />
          </Field>
        </Modal>
      )}
    </section>
  );
}
