import type { VerificationRound } from "./verification-types";

const labels = ["安排测试", "执行测试", "验收关闭"];

export function VerificationProgress({ round, defectStatus }: { round: VerificationRound; defectStatus: string }) {
  const returnedForRepair = round.status === "returned_repair";
  const returnedForTest = round.status === "returned_test";
  const closed = round.status === "accepted" && defectStatus === "closed";
  const waitingForOwner = ["needs_assignment", "needs_cases"].includes(round.execution_state || "");
  const waitingForRepair = round.execution_state === "waiting_repair";
  const needsArrangement = round.execution_state === "needs_arrangement";
  const readyToSubmit = round.execution_state === "tested";
  const current =
    closed || round.status === "review" ? 2 : round.execution_state === "needs_assignment" || needsArrangement ? 0 : 1;
  const currentLabel = returnedForRepair
    ? "退回修复"
    : returnedForTest
      ? "退回补测"
      : waitingForOwner
        ? round.execution_state === "needs_cases"
          ? "补充用例"
          : "安排测试"
        : waitingForRepair
          ? "等待修复"
          : needsArrangement
            ? "重新安排验证"
            : readyToSubmit
              ? "提交验收"
              : round.status === "review"
                ? "待验收"
                : labels[current];

  return (
    <ol
      aria-label="缺陷验证进度"
      className="flex flex-wrap items-center gap-2 rounded-md border border-subtle bg-layer-1 p-3"
    >
      {labels.map((label, index) => {
        const complete = closed || index < current;
        const active = !closed && index === current;
        const failed = active && (returnedForRepair || returnedForTest || needsArrangement);
        const tone = complete
          ? "border-success-subtle bg-success-subtle text-success-primary"
          : failed
            ? "border-danger-subtle bg-danger-subtle text-danger-primary"
            : active
              ? round.status === "review"
                ? "border-warning-subtle bg-warning-subtle text-warning-primary"
                : "border-accent-subtle bg-accent-subtle text-accent-primary"
              : "border-subtle text-secondary";
        return (
          <li
            key={label}
            aria-current={active ? "step" : undefined}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-11 ${tone}`}
          >
            <span className="font-semibold">{complete ? "✓" : String(index + 1)}</span>
            <span>{label}</span>
            {active && currentLabel !== label && <span className="text-11">{currentLabel}</span>}
          </li>
        );
      })}
    </ol>
  );
}
