import { useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { GripVertical } from "lucide-react";
import { combine } from "@atlaskit/pragmatic-drag-and-drop/combine";
import { draggable, dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { setCustomNativeDragPreview } from "@atlaskit/pragmatic-drag-and-drop/element/set-custom-native-drag-preview";
import { pointerOutsideOfPreview } from "@atlaskit/pragmatic-drag-and-drop/element/pointer-outside-of-preview";
import type { BoardDropPlacement } from "./arrangement";
import { boardDropPlacement } from "./arrangement";
import type { ColumnPreview } from "./use-column-motion";
type Props = {
  id: string;
  title: string;
  boardKey: string;
  ids: string[];
  className: string;
  style?: CSSProperties;
  children: (handle: ReactNode) => ReactNode;
  enabled: boolean;
  onPlace: (source: string, target: string, placement: BoardDropPlacement) => void;
  onPreview: (preview: ColumnPreview | null) => void;
};
export function SortableKanbanColumn({
  id,
  title,
  boardKey,
  ids,
  className,
  style,
  onPlace,
  onPreview,
  children,
  enabled,
}: Props) {
  const elementRef = useRef<HTMLDivElement>(null),
    handleRef = useRef<HTMLButtonElement>(null);
  const callbacks = useRef({ onPlace, onPreview });
  callbacks.current = { onPlace, onPreview };
  const [placement, setPlacement] = useState<BoardDropPlacement | null>(null),
    [dragging, setDragging] = useState(false);
  useEffect(() => {
    const element = elementRef.current,
      handle = handleRef.current;
    if (!enabled || !element || !handle) return;
    const intent = (data: Record<string, unknown>, input: { clientX: number; clientY: number }) =>
      boardDropPlacement(
        { x: Number(data.startX), y: Number(data.startY) },
        { x: input.clientX, y: input.clientY },
        element.getBoundingClientRect()
      );
    return combine(
      draggable({
        element,
        dragHandle: handle,
        getInitialData: ({ input }) => ({
          type: "KANBAN_COLUMN",
          boardKey,
          columnId: id,
          startX: input.clientX,
          startY: input.clientY,
        }),
        onGenerateDragPreview: ({ nativeSetDragImage }) =>
          setCustomNativeDragPreview({
            nativeSetDragImage,
            getOffset: pointerOutsideOfPreview({ x: "12px", y: "8px" }),
            render: ({ container }) => {
              const root = createRoot(container);
              root.render(
                <div className="flex items-center gap-2 rounded border border-subtle bg-surface-1 px-3 py-2 text-12 text-primary shadow-raised-200">
                  <GripVertical className="size-3.5" />
                  {title}
                </div>
              );
              return () => root.unmount();
            },
          }),
        onDragStart: () => setDragging(true),
        onDrop: () => {
          setDragging(false);
          callbacks.current.onPreview(null);
        },
      }),
      dropTargetForElements({
        element,
        canDrop: ({ source, input }) =>
          source.data.type === "KANBAN_COLUMN" &&
          source.data.boardKey === boardKey &&
          (source.data.columnId !== id || ["above", "below"].includes(intent(source.data, input))),
        getData: ({ source, input }) => ({
          type: "KANBAN_COLUMN",
          boardKey,
          columnId: id,
          placement: intent(source.data, input),
        }),
        onDrag: ({ source, self }) => {
          const next = self.data.placement as BoardDropPlacement;
          setPlacement(next);
          callbacks.current.onPreview({ source: source.data.columnId as string, target: id, placement: next });
        },
        onDragEnter: ({ source, self }) => {
          const next = self.data.placement as BoardDropPlacement;
          setPlacement(next);
          callbacks.current.onPreview({ source: source.data.columnId as string, target: id, placement: next });
        },
        onDragLeave: () => {
          setPlacement(null);
          callbacks.current.onPreview(null);
        },
        onDrop: ({ source, self }) => {
          setPlacement(null);
          callbacks.current.onPlace(source.data.columnId as string, id, self.data.placement as BoardDropPlacement);
        },
      })
    );
  }, [enabled, boardKey, id, title]);
  const handle = enabled ? (
    <button
      ref={handleRef}
      type="button"
      aria-label={`调整${title}栏顺序`}
      title="左右插入，上下换行；方向键也可调整"
      className="focus-visible:outline-accent-primary shrink-0 cursor-grab rounded p-0.5 text-tertiary hover:bg-layer-1 hover:text-primary focus-visible:outline-2 active:cursor-grabbing"
      onKeyDown={(event) => {
        const index = ids.indexOf(id);
        let target: string | undefined,
          edge: BoardDropPlacement = "before";
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          target = id;
          edge = event.key === "ArrowDown" ? "below" : "above";
        } else if (event.key === "ArrowLeft") target = ids[index - 1];
        else if (event.key === "ArrowRight") {
          target = ids[index + 1];
          edge = "after";
        } else if (event.key === "Home") target = ids[0];
        else if (event.key === "End") {
          target = ids[ids.length - 1];
          edge = "after";
        }
        if (target) {
          event.preventDefault();
          onPlace(id, target, edge);
        }
      }}
    >
      <GripVertical aria-hidden="true" className="size-3.5" />
    </button>
  ) : null;
  return (
    <div
      ref={elementRef}
      data-board-column={id}
      data-column-name={title}
      data-drop-placement={placement || undefined}
      className={className}
      style={style}
    >
      {placement && (
        <div
          aria-hidden="true"
          className={`pointer-events-none absolute z-20 bg-accent-primary ${placement === "before" ? "top-0 bottom-0 -left-2 w-0.5" : placement === "after" ? "top-0 -right-2 bottom-0 w-0.5" : placement === "above" ? "top-0 right-0 left-0 h-0.5" : "top-12 right-0 left-0 h-0.5"}`}
        >
          {(placement === "below" || placement === "above") && (
            <span className="absolute left-2 rounded bg-accent-primary px-2 py-1 text-11 whitespace-nowrap text-on-color">
              {placement === "below" ? "移到下一排" : "移到上一排"}
            </span>
          )}
        </div>
      )}
      <div data-column-visual className={`relative w-full ${dragging ? "opacity-40" : ""}`}>
        {children(handle)}
      </div>
    </div>
  );
}
