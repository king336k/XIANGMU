// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useState } from "react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "./api";
import { LogContent } from "./log-content";

type FileRecord = { id: string; name: string; size: number };
export function InlineFilePreview({ base, file, onOpen }: { base: string; file: FileRecord; onOpen: () => void }) {
  const image = /\.(png|jpe?g|gif|webp)$/i.test(file.name);
  const text = /\.(log|txt|json|csv|md|ya?ml)$/i.test(file.name);
  const supported = image ? file.size <= 5 * 1024 * 1024 : text && file.size <= 1024 * 1024;
  const { data, error, isLoading } = useSWR(
    supported ? `${base}files/${file.id}/preview/` : null,
    (url: string) => qualityApi.blob(url),
    { revalidateOnFocus: false }
  );
  const [content, setContent] = useState<{ image?: string; text?: string }>();
  useEffect(() => {
    if (!data) return;
    let active = true;
    const objectUrl = image ? URL.createObjectURL(data) : undefined;
    if (objectUrl) setContent({ image: objectUrl });
    else
      void data.text().then((value) => {
        if (active) setContent({ text: value });
        return undefined;
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [data, image]);
  if (!supported) return null;
  return (
    <div className="mt-3 w-full">
      {isLoading && (
        <p role="status" className="text-12 text-secondary">
          正在加载文件预览…
        </p>
      )}
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          预览暂不可用：{errorMessage(error)}
        </p>
      )}
      {content?.image && (
        <button
          type="button"
          onClick={onOpen}
          aria-label={`放大查看 ${file.name}`}
          className="block max-w-full cursor-zoom-in"
        >
          <img
            src={content.image}
            alt={file.name}
            loading="lazy"
            className="max-h-60 max-w-full rounded-md border border-subtle object-contain"
          />
        </button>
      )}
      {content?.text !== undefined && (
        <div className="space-y-1.5">
          <div
            tabIndex={0}
            aria-label={`${file.name} 完整内容，可滚动`}
            className="max-h-72 overflow-auto rounded-md border border-subtle bg-layer-1 p-3"
          >
            <LogContent text={content.text} />
          </div>
          <p className="text-11 text-secondary">
            {content.text.split("\n").length} 行 · 可滚动阅读，或展开搜索与自动换行。
          </p>
        </div>
      )}
    </div>
  );
}
