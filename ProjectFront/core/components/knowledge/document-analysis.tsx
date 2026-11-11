// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { Field, fieldClass, Modal } from "@/components/quality/shared";
import type { Article } from "./types";

type Segment = { id: string; text: string; characters: number };
type Source = {
  version: number;
  source_hash: string;
  characters: number;
  max_characters: number;
  segments: Segment[];
  image_notice: string;
};
type Citation = { segment_id: string; quote: string };
type Evidence = { text: string; citations: Citation[] };
type Analysis = {
  device_scope: Evidence;
  version_scope: Evidence;
  phenomena: Evidence[];
  checks: { action: string; expected: string; citations: Citation[] }[];
  limitations: Evidence[];
};
type Preview = { analysis: Analysis; token: string; expires_in: number; segment_ids: string[]; image_notice: string };

function Citations({ values }: { values: Citation[] }) {
  return (
    <div className="space-y-1 border-l-2 border-subtle pl-3 text-12 text-secondary">
      {values.length ? (
        values.map((value) => (
          <p key={`${value.segment_id}-${value.quote}`} className="break-words">
            <span className="font-medium">[{value.segment_id}]</span>「{value.quote}」
          </p>
        ))
      ) : (
        <p>原文未说明</p>
      )}
    </div>
  );
}

export function DocumentAnalysis({
  base,
  article,
  canEdit,
  onSaved,
  onClose,
}: {
  base: string;
  article: Article;
  canEdit: boolean;
  onSaved: (article: Article) => Promise<unknown>;
  onClose: () => void;
}) {
  const [source, setSource] = useState<Source>();
  const [selected, setSelected] = useState<string[]>([]);
  const [focus, setFocus] = useState("");
  const [preview, setPreview] = useState<Preview>();
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endpoint = `${base}articles/${article.id}/analysis/`;
  useEffect(() => {
    let current = true;
    if (!canEdit) return;
    const load = async () => {
      try {
        const value = await qualityApi.read<Source>(endpoint);
        if (!current) return;
        setSource(value);
        setSelected(
          value.characters <= value.max_characters && value.segments.length <= 500
            ? value.segments.map((segment) => segment.id)
            : []
        );
        setPreview(undefined);
        setConfirmed(false);
      } catch (e) {
        if (current) setError(errorMessage(e));
      }
    };
    void load();
    return () => {
      current = false;
    };
  }, [endpoint, article.edit_version, canEdit]);
  const characters =
    source?.segments
      .filter((segment) => selected.includes(segment.id))
      .reduce((sum, segment) => sum + segment.characters, 0) || 0;
  const toggle = (id: string) => {
    setSelected((values) => (values.includes(id) ? values.filter((value) => value !== id) : [...values, id]));
    setPreview(undefined);
    setConfirmed(false);
  };
  const generate = async () => {
    if (!source) return;
    setBusy(true);
    setError("");
    setPreview(undefined);
    setConfirmed(false);
    try {
      setPreview(
        await qualityApi.write<Preview>(endpoint, {
          expected_version: source.version,
          source_hash: source.source_hash,
          segment_ids: selected,
          focus,
        })
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title="解读文档并整理草稿"
      onClose={onClose}
      submitLabel="确认应用到草稿"
      onSubmit={
        canEdit && preview && confirmed && !busy
          ? async () => {
              const updated = await qualityApi.write<Article>(`${endpoint}apply/`, {
                token: preview.token,
                confirmed: true,
              });
              await onSaved(updated);
            }
          : undefined
      }
    >
      <p className="text-12 text-secondary">
        选择文字范围，核对解读与依据后再应用。原文保留，应用后需重新检查和审核；原图用于核对。
      </p>
      {!canEdit && (
        <p role="alert" className="text-13 text-danger-primary">
          当前权限不能解读或编辑知识。
        </p>
      )}
      {source && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-12">
            <span>
              原文 {source.characters.toLocaleString()} 字 · 已选 {selected.length} 段 / {characters.toLocaleString()}{" "}
              字
            </span>
            <button
              type="button"
              className="text-accent-primary"
              disabled={busy}
              onClick={() => {
                setSelected([]);
                setPreview(undefined);
                setConfirmed(false);
              }}
            >
              清除选择
            </button>
          </div>
          {source.characters > source.max_characters && (
            <p className="text-12 text-secondary">
              文档较长，请按章节选择不超过 {source.max_characters.toLocaleString()} 字。解读只覆盖选中范围。
            </p>
          )}
          <div className="max-h-60 space-y-2 overflow-auto rounded-md border border-subtle p-3">
            {source.segments.map((segment) => (
              <div key={segment.id} className="flex items-start gap-3">
                <input
                  aria-label={`选择段落 ${segment.id}`}
                  className="mt-1 size-4 shrink-0"
                  type="checkbox"
                  checked={selected.includes(segment.id)}
                  disabled={busy}
                  onChange={() => toggle(segment.id)}
                />
                <details className="min-w-0 flex-1 text-12">
                  <summary className="cursor-pointer break-words">
                    <span className="font-medium">{segment.id}</span> · {segment.characters}字 ·{" "}
                    {segment.text.slice(0, 90)}
                    {segment.text.length > 90 ? "…" : ""}
                  </summary>
                  <p className="mt-2 leading-6 break-words whitespace-pre-wrap text-secondary">{segment.text}</p>
                </details>
              </div>
            ))}
          </div>
          <Field label="本次关注点（可选）">
            <textarea
              value={focus}
              maxLength={1000}
              rows={2}
              disabled={busy}
              className={fieldClass}
              placeholder="例如：设备版本限制、采集停止后的检查步骤"
              onChange={(event) => {
                setFocus(event.target.value);
                setPreview(undefined);
                setConfirmed(false);
              }}
            />
          </Field>
          {characters > source.max_characters && (
            <p role="alert" className="text-12 text-danger-primary">
              所选范围超过20,000字，请减少段落。
            </p>
          )}
          <Button
            type="button"
            variant="neutral-primary"
            disabled={busy || !canEdit || !selected.length || characters > source.max_characters}
            onClick={() => void generate()}
          >
            {busy ? "正在解读所选正文…" : "生成解读预览"}
          </Button>
        </>
      )}
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
      {preview && (
        <section className="space-y-4 rounded-md border border-subtle p-4 text-13">
          <h3 className="font-medium">解读预览 · 仅覆盖 {preview.segment_ids.join("、")}</h3>
          <div className="space-y-2">
            <p>适用设备：{preview.analysis.device_scope.text}</p>
            <Citations values={preview.analysis.device_scope.citations} />
            <p>适用版本：{preview.analysis.version_scope.text}</p>
            <Citations values={preview.analysis.version_scope.citations} />
          </div>
          <h4 className="font-medium">现象</h4>
          {preview.analysis.phenomena.length ? (
            preview.analysis.phenomena.map((item) => (
              <div key={item.text} className="space-y-2">
                <p className="whitespace-pre-wrap">{item.text}</p>
                <Citations values={item.citations} />
              </div>
            ))
          ) : (
            <p className="text-12 text-secondary">原文未给出可归纳现象。</p>
          )}
          <h4 className="font-medium">检查步骤与预期</h4>
          {preview.analysis.checks.length ? (
            preview.analysis.checks.map((item, index) => (
              <div key={item.action} className="space-y-2">
                <p className="whitespace-pre-wrap">
                  {index + 1}. {item.action}
                </p>
                <p className="text-secondary">预期：{item.expected}</p>
                <Citations values={item.citations} />
              </div>
            ))
          ) : (
            <p className="text-12 text-secondary">原文未提供检查步骤，请补充资料。</p>
          )}
          <div className="space-y-1 text-12 text-secondary">
            <p>{preview.image_notice}</p>
            {preview.analysis.limitations.map((item) => (
              <div key={item.text}>
                <p>{item.text}</p>
                <Citations values={item.citations} />
              </div>
            ))}
            <p>预览10分钟内有效；原文变更后需重新分析。</p>
          </div>
          <label className="flex items-start gap-2 text-13">
            <input
              type="checkbox"
              className="mt-1 size-4 shrink-0"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            <span>我已核对适用范围、步骤和原文依据，确认加入当前草稿。</span>
          </label>
        </section>
      )}
    </Modal>
  );
}
