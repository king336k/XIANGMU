// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { DocumentSourceFiles } from "./document-source-files";
import { DocumentOcrReview } from "./document-ocr-review";
import type { OcrStatus } from "./document-ocr-review";
import type { DocumentSourceFile } from "@/components/knowledge/types";
import { FeishuImportSummary } from "./feishu-import-summary";
import type { FeishuExtraction, FeishuPreviewError } from "./feishu-import-summary";
import { FeishuConnectionSelect } from "./feishu-connection-select";
type Preview = {
  files: DocumentSourceFile[];
  extraction: FeishuExtraction & {
    format?: string;
    page_count?: number;
    image_count?: number;
    attachment_count?: number;
    ocr?: OcrStatus;
  };
  id: string;
  valid: boolean;
  rows: Record<string, unknown>[];
  errors: FeishuPreviewError[];
  source_url: string;
  object_ids: string[];
  status: string;
};
export function DocumentImportForm({
  base,
  resource,
  onClose,
  onSaved,
}: {
  base: string;
  resource: "knowledge" | "requirements" | "versions";
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const [file, setFile] = useState<File>(),
    [preview, setPreview] = useState<Preview>(),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [source, setSource] = useState(""),
    [url, setUrl] = useState(""),
    [ocrPending, setOcrPending] = useState(false),
    [feishuOpen, setFeishuOpen] = useState(false),
    [connectionReady, setConnectionReady] = useState(false);
  const isFeishu = ["feishu_docx", "feishu"].includes(preview?.extraction?.format || "");
  const feishuIncomplete =
    isFeishu &&
    (preview?.extraction?.files_complete !== true ||
      !!preview.extraction.failures?.length ||
      !!preview.errors.some((item) => item.range));
  const canOcr =
    resource === "knowledge" &&
    preview?.status === "preview" &&
    !preview.source_url &&
    ["pdf", "docx", "png"].includes(preview.extraction?.format || file?.name.split(".").pop()?.toLowerCase() || "");
  const candidatePending =
    !!preview?.extraction?.ocr &&
    preview.extraction.ocr.status !== "idle" &&
    !(preview.extraction.ocr.reviewed === true && preview.extraction.ocr.requires_review === false);
  const perform = async (fromFeishu = false) => {
    setBusy(true);
    setError("");
    setPreview(undefined);
    setOcrPending(false);
    try {
      if (fromFeishu)
        setPreview(
          await qualityApi.write<Preview>(`${base}document-imports/feishu/`, { resource, source_instance: source, url })
        );
      else {
        if (!file) throw new Error("请选择文件。");
        const form = new FormData();
        form.set("resource", resource);
        form.set("file", file);
        setPreview(await qualityApi.write<Preview>(`${base}document-imports/`, form));
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={{ knowledge: "导入知识草稿", requirements: "导入需求文档", versions: "导入版本清单" }[resource]}
      onClose={onClose}
      submitLabel="确认导入草稿"
      onSubmit={
        preview?.valid && !ocrPending && !candidatePending && !feishuIncomplete
          ? async () => {
              await qualityApi.write(`${base}document-imports/${preview.id}/confirm/`, {});
              await onSaved();
            }
          : undefined
      }
    >
      <p className="text-12 text-secondary">
        先预检、阅读，再确认草稿。DOCX / PDF / PNG 最大20MiB，文本 / JSON 最大2MiB；飞书文档保留正文、图片与附件供核对。
      </p>
      <Field
        label={resource === "knowledge" ? "选择 DOCX / PDF / PNG / Markdown / TXT / JSON 文件" : "选择JSON数组文件"}
      >
        <input
          type="file"
          accept={resource === "knowledge" ? ".docx,.pdf,.png,.md,.txt,.json" : ".json"}
          className={fieldClass}
          onChange={(event) => {
            const selected = event.target.files?.[0];
            if (!selected) return;
            setFile(selected);
            setPreview(undefined);
            setOcrPending(false);
          }}
        />
      </Field>
      <Button type="button" variant="neutral-primary" disabled={busy || !file} onClick={() => void perform(false)}>
        预检文件
      </Button>
      {resource !== "versions" && (
        <details className="text-12 text-secondary" onToggle={(event) => setFeishuOpen(event.currentTarget.open)}>
          <summary className="cursor-pointer">从飞书文档读取</summary>
          <div className="mt-3 space-y-3">
            <FeishuConnectionSelect
              base={base}
              enabled={feishuOpen}
              value={source}
              onChange={(value) => {
                setSource(value);
                setPreview(undefined);
              }}
              onReadyChange={setConnectionReady}
            />
            <Field label="飞书知识库/文档链接">
              <input
                value={url}
                maxLength={1000}
                onChange={(event) => {
                  setUrl(event.target.value);
                  setPreview(undefined);
                }}
                className={fieldClass}
                placeholder="https://company.feishu.cn/wiki/..."
              />
            </Field>
            <Button
              type="button"
              variant="neutral-primary"
              disabled={busy || !source || !url || !connectionReady}
              onClick={() => void perform(true)}
            >
              读取并预检
            </Button>
          </div>
        </details>
      )}
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
      {preview && (
        <div className="space-y-3">
          <p className="text-13">
            {preview.valid && !feishuIncomplete ? "预检通过" : "预检未通过"} · {preview.rows.length}条可识别内容
          </p>
          {preview.source_url && <p className="text-12 text-secondary">来源：{preview.source_url}</p>}
          {preview.errors
            .filter((row) => !isFeishu || !row.range)
            .map((row) => (
              <p key={row.row} className="text-12 text-danger-primary">
                第{row.row}条：{row.error || JSON.stringify(row.fields)}
              </p>
            ))}
          {isFeishu && <FeishuImportSummary extraction={preview.extraction} errors={preview.errors} />}
          {!isFeishu && preview.extraction?.image_count !== undefined && (
            <p className="text-12 text-secondary">
              {preview.extraction.page_count ? `${preview.extraction.page_count}页 · ` : ""}
              {preview.extraction.image_count}张图片 · {preview.extraction.attachment_count || 0}个附件
            </p>
          )}
          <DocumentSourceFiles files={preview.files || []} />
          {canOcr && (
            <DocumentOcrReview<Preview>
              key={preview.id}
              base={base}
              importId={preview.id}
              initial={preview.extraction?.ocr}
              onPendingChange={setOcrPending}
              onApplied={setPreview}
            />
          )}
          <div className="max-h-80 space-y-4 overflow-auto rounded-md border border-subtle p-4">
            {preview.rows.map((row, index) => (
              <article
                key={`${preview.id}-${String(row.title || row.name)}-${String(row.content || row.description || row.version)}`}
                className="space-y-2 text-13"
              >
                <h3 className="font-medium">{String(row.title || row.name || `第${index + 1}条`)}</h3>
                <p className="leading-7 break-words whitespace-pre-wrap">
                  {String(row.content || row.description || "")}
                </p>
                {Object.entries(row)
                  .filter(([key]) => !["title", "name", "content", "description"].includes(key))
                  .map(([key, value]) => (
                    <p key={key} className="text-12 text-secondary">
                      {(
                        { tags: "标签", version: "版本", acceptance: "验收标准", priority: "优先级" } as Record<
                          string,
                          string
                        >
                      )[key] || key}
                      ：{Array.isArray(value) ? value.join("、") : String(value ?? "")}
                    </p>
                  ))}
              </article>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}
