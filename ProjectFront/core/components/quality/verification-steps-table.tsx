import { useMemo } from "react";
import { v4 as uuidv4 } from "uuid";
import { Badge } from "./shared";
import { resultNames } from "./types";
import type { Step } from "./types";

export function VerificationStepsTable({
  steps,
  results,
  onResultChange,
}: {
  onResultChange?: (index: number, result: string) => void;
  steps: Step[];
  results?: { result: string; actual: string }[];
}) {
  const rows = useMemo(() => steps.map((step) => ({ step, key: uuidv4() })), [steps]);
  return (
    <div className="overflow-x-auto rounded-md border border-subtle">
      <table className="w-full table-fixed text-left text-13">
        <thead className="hidden bg-layer-1 text-12 text-secondary sm:table-header-group">
          <tr>
            <th className="w-12 p-3 font-medium">步骤</th>
            <th className="p-3 font-medium">验证操作</th>
            <th className="p-3 font-medium">预期结果</th>
            <th className="p-3 font-medium">实际结果</th>
            <th className="w-24 p-3 font-medium">结果</th>
          </tr>
        </thead>
        <tbody className="block divide-y divide-subtle sm:table-row-group">
          {rows.map(({ step, key: rowKey }, index) => (
            <tr key={rowKey} className="block p-3 sm:table-row sm:p-0">
              <td className="block text-12 text-secondary sm:table-cell sm:p-3 sm:align-top">
                {String(index + 1).padStart(2, "0")}
              </td>
              <td className="block py-1 break-words whitespace-pre-wrap sm:table-cell sm:p-3 sm:align-top">
                <span className="mr-2 text-12 text-secondary sm:hidden">操作</span>
                {step.action}
              </td>
              <td className="block py-1 break-words whitespace-pre-wrap sm:table-cell sm:p-3 sm:align-top">
                <span className="mr-2 text-12 text-secondary sm:hidden">预期</span>
                {step.expected}
              </td>
              <td className="block py-1 break-words whitespace-pre-wrap sm:table-cell sm:p-3 sm:align-top">
                <span className="mr-2 text-12 text-secondary sm:hidden">实际</span>
                {results?.[index]?.actual || "—"}
              </td>
              <td className="block py-1 sm:table-cell sm:p-3 sm:align-top">
                {onResultChange ? (
                  <select
                    aria-label={`步骤 ${index + 1} 结果`}
                    value={results?.[index]?.result || "pending"}
                    onChange={(event) => onResultChange(index, event.target.value)}
                    className={`max-w-full rounded border px-2 py-1 text-12 ${results?.[index]?.result === "passed" ? "border-success-subtle bg-success-subtle text-success-primary" : ["failed", "blocked"].includes(results?.[index]?.result || "") ? "border-danger-subtle bg-danger-subtle text-danger-primary" : "border-subtle bg-layer-1 text-secondary"}`}
                  >
                    <option value="pending" disabled>
                      未执行
                    </option>
                    {Object.entries(resultNames)
                      .filter(([key]) => key !== "pending")
                      .map(([key, label]) => (
                        <option key={key} value={key}>
                          {label}
                        </option>
                      ))}
                  </select>
                ) : (
                  <Badge value={results?.[index]?.result || "pending"} />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
