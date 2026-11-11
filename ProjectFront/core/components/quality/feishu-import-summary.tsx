// SPDX-License-Identifier: AGPL-3.0-only
export type FeishuReadFailure = { block_id?: string; stage?: string; error?: string };
export type FeishuExtraction = {
  format?: string;
  document_id?: string;
  blocks_read?: number;
  segment_count?: number;
  image_count?: number;
  attachment_count?: number;
  files_complete?: boolean;
  failures?: FeishuReadFailure[];
  segments?: { block_id: string; kind: string; locator: string; text: string }[];
};
export type FeishuPreviewError = {
  row: number;
  error?: string;
  fields?: Record<string, unknown>;
  range?: FeishuReadFailure;
};
const isFeishuExtraction = (extraction?: FeishuExtraction) =>
  ["feishu_docx", "feishu"].includes(extraction?.format || "");
const feishuReadIncomplete = (extraction?: FeishuExtraction) =>
  isFeishuExtraction(extraction) && (extraction?.files_complete !== true || !!extraction?.failures?.length);

const stageNames: Record<string, string> = {
  document: "读取文档",
  resolve: "定位文档",
  blocks: "读取文档内容",
  block: "读取文档内容",
  text: "读取正文",
  image: "读取图片",
  attachment: "读取附件",
  download: "下载文件",
  parse: "解析内容",
  snapshot: "保存文档快照",
};
function failureMessage(error?: string) {
  const messages: Record<string, string> = {
    upstream_denied_or_failed: "文件无法读取，请检查飞书权限或文件是否仍存在。",
    upstream_unavailable: "暂时无法连接飞书，请稍后重试。",
    upstream_error_content: "飞书返回了错误页面，请核对文件权限后重新读取。",
    upstream_error_payload: "飞书未能返回文档内容，请检查连接和授权。",
    rate_limit: "飞书请求较多，请稍后重新读取。",
    incomplete_download: "文件未下载完整，请重新读取。",
    empty_download: "文件内容为空，请核对原件。",
    merged_table_requires_review: "暂不支持合并单元格，请拆分表格后重新读取。",
    unsupported_block: "此类内容暂不支持，请转换为正文或普通表格后重新读取。",
    unsupported_text_element: "此段含暂不支持的内容，请转为普通文字后重新读取。",
    incomplete_table_cells: "表格内容未完整读取，请检查原表格后重试。",
    incomplete_children: "部分内容未完整读取，请重新读取文档。",
    missing_child_block: "部分内容未完整读取，请重新读取文档。",
    unreachable_block: "部分内容的顺序无法确认，请核对原文。",
    document_time_budget: "文档读取超时，请按章节拆分后重试。",
    request_budget: "文档读取超出本次范围，请按章节拆分后重试。",
    download_budget: "文件超出读取大小，请拆分后重新读取。",
    media_total_budget: "图片和附件总量过大，请拆分文档后重新读取。",
  };
  if (error && messages[error]) return messages[error];
  return error && /[\u4e00-\u9fff]/u.test(error)
    ? error
    : "此处内容未能读取，请核对原文后重试。";
}
export function FeishuImportSummary({
  extraction,
  errors = [],
}: {
  extraction: FeishuExtraction;
  errors?: FeishuPreviewError[];
}) {
  const failures = extraction.failures?.length
    ? extraction.failures
    : errors
        .filter((item) => item.range)
        .map((item) => ({
          block_id: item.range?.block_id,
          stage: item.range?.stage,
          error: item.error,
        }));
  return (
    <section className="space-y-2 text-12 text-secondary">
      <p>
        飞书文档 · {extraction.segment_count ?? "待核对"}段正文 · {extraction.image_count ?? "待核对"}张图片 ·{" "}
        {extraction.attachment_count ?? "待核对"}份附件
      </p>
      {!!extraction.image_count && <p>图片尚未识别文字，请预览或回源核对。</p>}
      {(feishuReadIncomplete(extraction) || failures.length > 0) && (
        <p role="alert" className="text-danger-primary">
          有内容未完整读取，暂不能确认导入
        </p>
      )}
      {!!failures.length && (
        <ul className="space-y-2 text-danger-primary">
          {failures.map((failure) => (
            <li key={JSON.stringify([failure.block_id, failure.stage, failure.error])}>
              <p>
                {stageNames[failure.stage || ""] || "读取"}：{failureMessage(failure.error)}
              </p>
              {failure.block_id && (
                <details className="mt-1 text-secondary">
                  <summary className="cursor-pointer">查看来源位置</summary>
                  <p className="mt-1 break-all">内容位置：{failure.block_id}</p>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
