// SPDX-License-Identifier: AGPL-3.0-only
import type { RemoteProcess } from "./types";
type Command = NonNullable<RemoteProcess["command"]>;
type Change = NonNullable<Command["changes"]>[number];
function lineNumber(value: number | null | undefined) {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? `第${value}行` : "行号未记录";
}
function fieldText(change: Change, side: "before" | "after") {
  if (change[`${side}_exists`] === false) return "字段不存在";
  if (!Object.hasOwn(change, side) || change[side] === undefined) return "字段值未记录";
  return `${JSON.stringify(change.key)}: ${JSON.stringify(change[side], null, 2)}`;
}
const backupCaption = (path: string) =>
  path.replace(/(\.backup)[-_](?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i, "$1…");
export function ConfigurationChangeDiff({ command }: { command: Command }) {
  const groups = new Map<string, Change[]>();
  for (const change of command.changes || []) {
    const path = change.path || command.path || "文件路径未记录";
    groups.set(path, [...(groups.get(path) || []), change]);
  }
  return (
    <div aria-label="配置差异" className="space-y-3">
      {[...groups].map(([path, changes]) => (
        <section key={path} className="overflow-hidden rounded border border-subtle">
          <h5 className="font-mono border-b border-subtle bg-surface-2 px-3 py-2 text-12 break-all">{path}</h5>
          {changes.map((change) => (
            <div
              key={JSON.stringify([change.key, change.before, change.after, change.before_exists, change.after_exists])}
              className="border-b border-subtle last:border-b-0"
            >
              {(change.before_exists === false || change.after_exists === false) && (
                <p className="px-3 py-1.5 text-11 text-secondary">
                  {change.before_exists === false ? "新增字段" : "删除字段"}
                </p>
              )}
              {change.before_file_exists === false && (
                <p className="px-3 py-1.5 text-11 text-secondary">新建配置文件 · 修改前目标文件不存在</p>
              )}
              {change.before_source_path && (
                <p className="px-3 py-1.5 text-11 text-secondary">
                  原值来源（{change.before_source_role || "执行回执"}）：{change.before_source_path}
                </p>
              )}
              <div className="grid sm:grid-cols-2">
                <div aria-label={`修改前 ${change.key}`} className="min-w-0 bg-danger-subtle px-3 py-2">
                  <p className="mb-1 text-11 text-danger-primary">− 修改前 · {lineNumber(change.before_line)}</p>
                  <pre className="font-mono overflow-auto text-12 leading-6 break-words whitespace-pre-wrap">
                    {fieldText(change, "before")}
                  </pre>
                </div>
                <div
                  aria-label={`修改后 ${change.key}`}
                  className="min-w-0 border-t border-subtle bg-success-subtle px-3 py-2 sm:border-t-0 sm:border-l"
                >
                  <p className="mb-1 text-11 text-success-primary">+ 修改后 · {lineNumber(change.after_line)}</p>
                  <pre className="font-mono overflow-auto text-12 leading-6 break-words whitespace-pre-wrap">
                    {fieldText(change, "after")}
                  </pre>
                </div>
              </div>
              {!change.before_line &&
                !change.after_line &&
                typeof change.line === "number" &&
                Number.isInteger(change.line) &&
                change.line > 0 && (
                  <p className="px-3 py-1 text-11 text-secondary">
                    回执位置：{lineNumber(change.line)}（未区分修改前后）
                  </p>
                )}
              {(change.backup || command.backup || change.before_sha256 || change.after_sha256) && (
                <details className="px-3 py-2 text-11 text-tertiary">
                  <summary className="cursor-pointer">备份与校验信息</summary>
                  <div className="mt-2 space-y-1">
                    <p>
                      {change.before_file_exists === false ? "空备份标记（原文件不存在）：" : "备份 / 修改前："}
                      {change.backup || command.backup ? (
                        <span title={change.backup || command.backup}>
                          {backupCaption(change.backup || command.backup!)}
                        </span>
                      ) : (
                        "修改前文件未记录"
                      )}
                    </p>
                    <p>
                      修改后：<span title={path}>{path}</span>
                    </p>
                  </div>
                  <details className="mt-2">
                    <summary className="cursor-pointer">技术信息</summary>
                    {(change.backup || command.backup) && (
                      <p className="mt-1 break-all">{change.backup || command.backup}</p>
                    )}
                    {change.before_sha256 && <p className="mt-1 break-all">修改前：{change.before_sha256}</p>}
                    {change.after_sha256 && <p className="mt-1 break-all">修改后：{change.after_sha256}</p>}
                  </details>
                </details>
              )}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
