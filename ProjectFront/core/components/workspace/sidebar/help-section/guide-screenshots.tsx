// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Maximize2 } from "lucide-react";
import { Modal } from "@/components/quality/shared";

export type GuideScreenshot = { src: string; title: string; caption: string; width?: number; height?: number };

export function GuideScreenshots({ images }: { images: GuideScreenshot[] }) {
  const [expanded, setExpanded] = useState<GuideScreenshot>();
  return (
    <section aria-label="操作截图" className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-14 font-medium">操作截图</h4>
        <span className="text-11 text-tertiary">项目平台实拍 · 点击放大</span>
      </div>
      {images.map((image) => (
        <figure key={image.src} className="overflow-hidden rounded-md border border-subtle">
          <button
            type="button"
            onClick={() => setExpanded(image)}
            aria-label={`放大截图：${image.title}`}
            className="group focus-visible:outline-accent-primary relative block w-full cursor-zoom-in bg-layer-1 focus-visible:outline-2"
          >
            <img
              src={image.src}
              alt={image.title}
              width={image.width ?? 1280}
              height={image.height ?? 720}
              loading="lazy"
              className="h-auto w-full"
            />
            <span className="shadow-sm absolute right-2 bottom-2 rounded bg-surface-1 p-1.5 text-secondary">
              <Maximize2 aria-hidden="true" className="size-4" />
            </span>
          </button>
          <figcaption className="space-y-1 bg-surface-1 px-3 py-2 text-12">
            <p className="font-medium">{image.title}</p>
            <p className="leading-5 text-secondary">{image.caption}</p>
          </figcaption>
        </figure>
      ))}
      {expanded && (
        <Modal title={expanded.title} width="wide" onClose={() => setExpanded(undefined)}>
          <img
            src={expanded.src}
            alt={expanded.title}
            width={expanded.width ?? 1280}
            height={expanded.height ?? 720}
            className="h-auto w-full"
          />
          <p className="text-13 leading-6 text-secondary">{expanded.caption}</p>
        </Modal>
      )}
    </section>
  );
}
