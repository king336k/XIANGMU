// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";

type FileEntry = { id: string; path: string; size: string; sha256: string };
const emptyFile = (): FileEntry => ({ id: crypto.randomUUID(), path: "", size: "", sha256: "" });

export function PackageForm({
  base,
  defectId,
  onClose,
  onSaved,
}: {
  base: string;
  defectId: string;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const [name, setName] = useState("");
  const [system, setSystem] = useState("");
  const [externalId, setExternalId] = useState("");
  const [files, setFiles] = useState<FileEntry[]>([emptyFile()]);
  const [preview, setPreview] = useState<{ file_count: number; total_bytes: number }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const changed = (index: number, field: keyof FileEntry, value: string) => {
    setFiles((rows) => rows.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
    setPreview(undefined);
  };
  const payload = () => ({
    name,
    source_system: system,
    external_id: externalId,
    defect_id: defectId,
    files: files.map((file) => ({
      path: file.path,
      sha256: file.sha256,
      size: file.size.trim() === "" ? null : Number(file.size),
    })),
  });
  return (
    <Modal
      title="登记问题包清单"
      onClose={onClose}
      submitLabel="确认登记"
      onSubmit={
        preview
          ? async () => {
              await qualityApi.write(`${base}packages/`, payload());
              await onSaved();
            }
          : undefined
      }
    >
      <p className="text-12 text-secondary">先填写清单并校验，再确认登记。登记后可在问题包中上传同名文件并核对内容。</p>
      <fieldset disabled={busy} className="space-y-4">
        <Field label="问题包名称 *">
          <input
            required
            maxLength={255}
            className={fieldClass}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setPreview(undefined);
            }}
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="来源系统 *">
            <input
              required
              maxLength={64}
              className={fieldClass}
              value={system}
              onChange={(e) => {
                setSystem(e.target.value);
                setPreview(undefined);
              }}
              placeholder="例如 daq"
            />
          </Field>
          <Field label="外部问题包编号 *">
            <input
              required
              maxLength={255}
              className={fieldClass}
              value={externalId}
              onChange={(e) => {
                setExternalId(e.target.value);
                setPreview(undefined);
              }}
            />
          </Field>
        </div>
        {files.map((file, index) => (
          <fieldset key={file.id} className="space-y-3 rounded-md border border-subtle p-3">
            <legend className="px-1 text-12 text-secondary">文件 {index + 1}</legend>
            <Field label="包内相对路径 *">
              <input
                required
                maxLength={500}
                value={file.path}
                onChange={(e) => changed(index, "path", e.target.value)}
                className={fieldClass}
                placeholder="logs/capture.log"
              />
            </Field>
            <Field label="文件大小（字节） *">
              <input
                required
                type="number"
                min={0}
                max={209715200}
                value={file.size}
                onChange={(e) => changed(index, "size", e.target.value)}
                className={fieldClass}
              />
            </Field>
            <Field label="SHA256 文件摘要 *">
              <input
                required
                pattern="[a-fA-F0-9]{64}"
                maxLength={64}
                value={file.sha256}
                onChange={(e) => changed(index, "sha256", e.target.value)}
                className={fieldClass}
              />
            </Field>
            {files.length > 1 && (
              <Button
                type="button"
                variant="neutral-primary"
                disabled={busy}
                onClick={() => {
                  setFiles(files.filter((_, i) => i !== index));
                  setPreview(undefined);
                }}
              >
                移除此文件
              </Button>
            )}
          </fieldset>
        ))}
        <Button
          type="button"
          variant="neutral-primary"
          disabled={busy || files.length >= 1000}
          onClick={() => {
            setFiles([...files, emptyFile()]);
            setPreview(undefined);
          }}
        >
          添加文件信息
        </Button>
        <Button
          type="button"
          variant="neutral-primary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError("");
            setPreview(undefined);
            try {
              setPreview(await qualityApi.write(`${base}packages/preflight/`, payload()));
            } catch (e) {
              setError(errorMessage(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "正在校验…" : "校验并预览"}
        </Button>
      </fieldset>
      {preview && (
        <p role="status" className="text-13 text-success-primary">
          校验通过：{preview.file_count} 个文件，共 {preview.total_bytes} 字节。请核对后确认登记。
        </p>
      )}
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
    </Modal>
  );
}
