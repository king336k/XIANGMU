import { AssistantMarkdown } from "./assistant-markdown";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { Modal } from "@/components/quality/shared";
import type { Publication } from "./types";
export function PublicationDetail({ value, onClose }: { value: Publication; onClose: () => void }) {
  return (
    <Modal title={`${value.title} · v${value.version}`} onClose={onClose}>
      <p className="text-12 text-secondary">
        {value.source_project_name && `${value.source_project_name} · `}
        {value.reference} · {renderNumericDateTime(value.created_at)}
      </p>
      {(value.device_scope || value.version_scope) && (
        <p className="text-12 text-secondary">
          适用：{[value.device_scope, value.version_scope].filter(Boolean).join(" · ")}
        </p>
      )}
      {value.is_excerpt && (
        <p className="text-12 text-secondary">
          本次引用摘录 · 原文 {value.source_characters?.toLocaleString()} 字 · 已标注原文位置
        </p>
      )}
      <div className="text-13 leading-7 break-words whitespace-pre-wrap">
        <AssistantMarkdown content={value.content} />
      </div>
      <p className="text-12 text-secondary">{value.tags.join(" · ")}</p>
    </Modal>
  );
}
