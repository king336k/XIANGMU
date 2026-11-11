import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useUser } from "@/hooks/store/user";
import {
  boardArrangementKey,
  moveBoardGroup,
  normalizeBoardArrangement,
  placeBoardGroup,
  boardInitialCount,
} from "./arrangement";
import type { BoardArrangement, BoardDropPlacement } from "./arrangement";

export function useBoardArrangement(groupBy?: string | null) {
  const { data: user } = useUser();
  const path = usePathname();
  const key = boardArrangementKey(user?.id || "anonymous", path || "", groupBy || "none");
  const [saved, setSaved] = useState<{ key: string; value: BoardArrangement }>();
  const value = saved?.key === key ? saved.value : normalizeBoardArrangement(null);
  useEffect(() => {
    const read = (event?: Event) => {
      if (event instanceof CustomEvent) {
        setSaved({ key, value: normalizeBoardArrangement(event.detail) });
        return;
      }
      try {
        setSaved({ key, value: normalizeBoardArrangement(JSON.parse(localStorage.getItem(key) || "null")) });
      } catch {
        setSaved({ key, value: normalizeBoardArrangement(null) });
      }
    };
    read();
    window.addEventListener(`board-arrangement:${key}`, read);
    return () => window.removeEventListener(`board-arrangement:${key}`, read);
  }, [key]);
  const update = useCallback(
    (patch: Partial<BoardArrangement>) => {
      const next = { ...value, ...patch };
      setSaved({ key, value: next });
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* Keep this session usable when browser storage is unavailable. */
      }
      window.dispatchEvent(new CustomEvent(`board-arrangement:${key}`, { detail: next }));
    },
    [key, value]
  );
  const move = useCallback(
    (ids: string[], source: string, target: string) => update({ order: moveBoardGroup(ids, source, target) }),
    [update]
  );
  const place = useCallback(
    (ids: string[], source: string, target: string, placement: BoardDropPlacement) => {
      const next = placeBoardGroup(ids, value.rowStarts || [], source, target, placement, value.layout);
      update({
        ...next,
        initialCounts: {
          ...value.initialCounts,
          "custom-rows": value.layout === "horizontal" ? 5 : boardInitialCount(value),
        },
      });
    },
    [value, update]
  );
  return { key, ...value, update, move, place };
}
