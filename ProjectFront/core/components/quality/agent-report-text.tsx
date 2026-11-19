// SPDX-License-Identifier: AGPL-3.0-only
export function AgentReportText({ content }: { content: string }) {
  const occurrences = new Map<string, number>();
  return (
    <div className="space-y-2 text-12 leading-6 break-words whitespace-pre-wrap">
      {content
        .split(/\r?\n/)
        .flatMap((line) => line.split(/\s+(?=\d+[.)、]\s)/))
        .map((line) => {
          const count = (occurrences.get(line) || 0) + 1;
          occurrences.set(line, count);
          const label = /^(Agent\s*远程处理|结论|原因与证据|已执行操作|复测|后续方案|修改位置)([：:])(.*)$/.exec(line);
          return (
            <p key={`${line}:${count}`} className={line ? undefined : "h-2"}>
              {label ? (
                <>
                  <strong className="font-semibold">
                    {label[1]}
                    {label[2]}
                  </strong>
                  {label[3]}
                </>
              ) : (
                line || "\u00a0"
              )}
            </p>
          );
        })}
    </div>
  );
}
