// SPDX-License-Identifier: AGPL-3.0-only
import { reportEvidence } from "./report-summary";
export function AgentReportText({ content }: { content: string }) {
  const occurrences = new Map<string, number>();
  const split = content.split(/\r?\n\s*(?:\*\*)?(?:详细证据与处理过程|详细依据)(?:\*\*)?[:：]\s*\r?\n/);
  const main = reportEvidence(split[0]);
  const basis = reportEvidence(split.slice(1).join("\n"));
  const paragraphs = (value: string) =>
    value
      .split(/\r?\n/)
      .flatMap((line) => line.split(/\s+(?=\d+[.)、]\s)/))
      .map((line) => {
        const count = (occurrences.get(line) || 0) + 1;
        occurrences.set(line, count);
        const label =
          /^(Agent\s*远程处理|故障|已处理|待验证|当前检查|历史处理|问题|原因|处理|验证|结论|原因与证据|已执行操作|复测|后续方案|修改位置)([：:])(.*)$/.exec(
            line
          );
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
      });
  return (
    <div className="space-y-2 text-12 leading-6 break-words whitespace-pre-wrap">
      {paragraphs(main.readable)}
      {split.length > 1 && basis.readable && (
        <details>
          <summary className="cursor-pointer">关键依据</summary>
          <div className="mt-2">{paragraphs(basis.readable)}</div>
        </details>
      )}
      {(main.hasTechnical || basis.hasTechnical) && (
        <details>
          <summary className="cursor-pointer">技术追踪</summary>
          <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap">{content}</pre>
        </details>
      )}
    </div>
  );
}
