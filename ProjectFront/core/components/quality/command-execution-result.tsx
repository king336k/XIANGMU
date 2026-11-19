// SPDX-License-Identifier: AGPL-3.0-only
export type CommandExecutionStep = {
  argv?: string[];
  stdout?: string;
  stderr?: string;
  exit_code?: number | null;
  ok?: boolean | null;
  status?: string;
  timed_out?: boolean;
};
export type CommandExecution = CommandExecutionStep & { execution_steps?: CommandExecutionStep[] };
function outputPreview(output: string) {
  let formatted = output.replaceAll("\r\n", "\n").replace(/\n$/, "");
  // JSON.parse would round long receipt sequence numbers; keep those bytes intact.
  if (!/\d{16}/.test(formatted) && (formatted.trimStart().startsWith("{") || formatted.trimStart().startsWith("["))) {
    try {
      formatted = JSON.stringify(JSON.parse(formatted), null, 2);
    } catch {
      // Non-JSON output remains the exact received text.
    }
  }
  const lines = formatted
    .split("\n")
    .slice(-12)
    .map((line) => (line.length > 200 ? `${line.slice(0, 199)}…` : line));
  while (lines.join("\n").length > 1000) lines.shift();
  const preview = lines.join("\n");
  return { preview, excerpt: preview !== formatted };
}
function executionStatus(command: CommandExecutionStep) {
  const hasExit = typeof command.exit_code === "number" && Number.isInteger(command.exit_code);
  const failed =
    command.timed_out === true ||
    (hasExit && command.exit_code !== 0) ||
    (command.status === "done" && command.ok === false);
  const completed = !failed && command.status === "done" && hasExit && command.exit_code === 0;
  return failed ? "失败" : completed ? "成功" : "待确认";
}
function executionResult(command: CommandExecutionStep) {
  const hasExit = typeof command.exit_code === "number" && Number.isInteger(command.exit_code);
  const status = executionStatus(command);
  const failed = status === "失败";
  const completed = status === "成功";
  const resultClass = failed ? "bg-danger-subtle" : completed ? "bg-success-subtle" : "bg-surface-2";
  const resultText = command.timed_out
    ? "命令执行超时"
    : failed
      ? "命令执行失败"
      : completed
        ? "命令执行完成，业务结果见复测"
        : "执行回执待确认";
  const argv = command.argv
    ?.map((value) => (/^[a-zA-Z0-9_./:@%+=,-]+$/.test(value) ? value : `'${value.replaceAll("'", "'\\''")}'`))
    .join(" ");
  const outputs = (
    [
      ["标准输出", command.stdout],
      ["标准错误", command.stderr],
    ] as const
  ).filter(([, value]) => typeof value === "string" && value.length > 0);
  return (
    <section aria-label="命令执行记录" className="overflow-hidden">
      <div className="grid sm:grid-cols-2">
        <div aria-label="执行命令" className="min-w-0 bg-danger-subtle px-3 py-2">
          <h5 className="mb-1 text-11 text-secondary">执行命令</h5>
          <pre className="font-mono overflow-auto text-12 leading-6 break-words whitespace-pre-wrap">
            {argv || "命令参数未记录"}
          </pre>
        </div>
        <div
          aria-label="执行结果"
          className={`min-w-0 border-t border-subtle px-3 py-2 sm:border-t-0 sm:border-l ${resultClass}`}
        >
          <h5 className="mb-1 text-11 text-secondary">执行结果</h5>
          <p className="text-12">{resultText}</p>
          {hasExit && <p className="mt-1 text-11 text-secondary">退出码：{command.exit_code}</p>}
          {outputs.map(([label, value]) => {
            const { preview, excerpt } = outputPreview(value!);
            return (
              <div key={label} className="mt-2 space-y-1">
                <p className="text-11 text-secondary">
                  {label}
                  {excerpt ? " · 输出节选，原文见完整输出" : ""}
                </p>
                <pre
                  aria-label={`${label}摘要`}
                  className="font-mono overflow-auto text-12 leading-6 break-words whitespace-pre-wrap"
                >
                  {preview}
                </pre>
                {excerpt && (
                  <details className="text-11 text-tertiary">
                    <summary className="cursor-pointer">完整{label}</summary>
                    <pre className="font-mono mt-1 max-h-64 overflow-auto text-12 leading-6 break-words whitespace-pre-wrap">
                      {value}
                    </pre>
                  </details>
                )}
              </div>
            );
          })}
          {outputs.length === 0 && <p className="mt-2 text-11 text-secondary">暂无文本输出</p>}
        </div>
      </div>
    </section>
  );
}

export function CommandExecutionResult({ command, target }: { command: CommandExecution; target?: string }) {
  const steps = command.execution_steps?.length ? command.execution_steps : [command];
  const statuses = steps.map(executionStatus);
  const outerFailed = executionStatus(command) === "失败";
  const status =
    outerFailed || statuses.includes("失败") ? "失败" : statuses.every((value) => value === "成功") ? "成功" : "待确认";
  const outerError = command.execution_steps?.length && outerFailed ? command.stderr : undefined;
  const occurrences = new Map<string, number>();
  return (
    <details className="overflow-hidden rounded border border-subtle">
      <summary
        className={`cursor-pointer bg-surface-2 px-3 py-2 text-12 break-all ${status === "失败" ? "text-danger-primary" : "text-secondary"}`}
      >
        {target || "命令与执行结果"} · {status}
      </summary>
      <div aria-label="实际执行步骤" className="space-y-3 border-t border-subtle">
        {!!command.execution_steps?.length && outerFailed && (
          <div className="bg-danger-subtle px-3 py-2 text-12 text-danger-primary">
            <p>整体执行未通过</p>
            {outerError && (
              <>
                <pre aria-label="整体错误摘要" className="font-mono mt-1 overflow-auto break-words whitespace-pre-wrap">
                  {outputPreview(outerError).preview}
                </pre>
                <details className="mt-1 text-11">
                  <summary className="cursor-pointer">完整整体错误</summary>
                  <pre className="font-mono mt-1 max-h-64 overflow-auto break-words whitespace-pre-wrap">
                    {outerError}
                  </pre>
                </details>
              </>
            )}
          </div>
        )}
        {steps.map((step) => {
          const signature = JSON.stringify(step);
          const occurrence = (occurrences.get(signature) || 0) + 1;
          occurrences.set(signature, occurrence);
          return <div key={`${signature}:${occurrence}`}>{executionResult(step)}</div>;
        })}
      </div>
    </details>
  );
}
