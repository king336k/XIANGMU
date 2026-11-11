import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { BoardDropPlacement } from "./arrangement";
import { insertBoardGroup } from "./arrangement";
export type ColumnPreview = { source: string; target: string; placement: BoardDropPlacement };
export function useColumnMotion(ids: string[], layoutKey: string) {
  const rootRef = useRef<HTMLDivElement>(null),
    snapshots = useRef(new Map<string, DOMRect>()),
    previewRef = useRef<ColumnPreview | null>(null);
  const [preview, setPreview] = useState<ColumnPreview | null>(null);
  const capture = useCallback(() => {
    const map = new Map<string, DOMRect>();
    rootRef.current?.querySelectorAll<HTMLElement>("[data-board-column]").forEach((node) => {
      const visual = node.querySelector<HTMLElement>("[data-column-visual]");
      if (visual) map.set(node.dataset.boardColumn!, visual.getBoundingClientRect());
    });
    snapshots.current = map;
  }, []);
  const showPreview = useCallback(
    (next: ColumnPreview | null) => {
      if (JSON.stringify(next) === JSON.stringify(previewRef.current)) return;
      capture();
      previewRef.current = next;
      setPreview(next);
    },
    [capture]
  );
  const commit = useCallback(
    (action: () => void) => {
      capture();
      previewRef.current = null;
      setPreview(null);
      action();
    },
    [capture]
  );
  const key = ids.join("|") + layoutKey + JSON.stringify(preview);
  useLayoutEffect(() => {
    const nodes = Array.from(rootRef.current?.querySelectorAll<HTMLElement>("[data-board-column]") || []);
    const visuals = new Map(
      nodes.flatMap((node) => {
        const visual = node.querySelector<HTMLElement>("[data-column-visual]");
        return visual ? [[node.dataset.boardColumn!, visual] as const] : [];
      })
    );
    const before = snapshots.current;
    const old = new Map([...visuals].map(([id, visual]) => [id, before.get(id) || visual.getBoundingClientRect()]));
    visuals.forEach((visual) => {
      visual.getAnimations().forEach((animation) => animation.cancel());
      visual.style.transform = "";
    });
    const natural = new Map([...visuals].map(([id, visual]) => [id, visual.getBoundingClientRect()]));
    const desired =
      preview && (preview.placement === "before" || preview.placement === "after")
        ? insertBoardGroup(ids, preview.source, preview.target, preview.placement)
        : ids;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    for (const [id, visual] of visuals) {
      const base = natural.get(id)!,
        previous = old.get(id)!,
        slot = natural.get(ids[desired.indexOf(id)]) || base;
      const x = slot.left - base.left,
        y = slot.top - base.top;
      visual.style.transform = `translate(${x}px,${y}px)`;
      if (!reduced && before.size) {
        visual.animate(
          [
            { transform: `translate(${previous.left - base.left}px,${previous.top - base.top}px)` },
            { transform: `translate(${x}px,${y}px)` },
          ],
          { duration: 200, easing: "cubic-bezier(0.2,0,0,1)" }
        );
      }
    }
    snapshots.current = new Map();
  }, [key]);
  return { rootRef, preview, showPreview, commit };
}
