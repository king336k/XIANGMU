import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useUser } from "@/hooks/store/user";
import { getValueFromLocalStorage, setValueIntoLocalStorage } from "@/hooks/use-local-storage";
import { listPageSizeKey, normalizeListPageSize } from "./pagination";

export function useListPageSize(storeType: string, groupBy?: string | null) {
  const { data: user } = useUser();
  const path = usePathname();
  const key = listPageSizeKey(user?.id || "anonymous", path || "", storeType, groupBy);
  const grouped = !!groupBy;
  const [saved, setSaved] = useState<{ key: string; size: number }>();
  const pageSize = saved?.key === key ? saved.size : normalizeListPageSize(undefined, grouped);

  useEffect(() => {
    const read = () => {
      try {
        setSaved({ key, size: normalizeListPageSize(getValueFromLocalStorage(key, undefined), grouped) });
      } catch {
        setSaved({ key, size: normalizeListPageSize(undefined, grouped) });
      }
    };
    read();
    window.addEventListener(`local-storage:${key}`, read);
    return () => window.removeEventListener(`local-storage:${key}`, read);
  }, [key, grouped]);

  const setPageSize = useCallback(
    (size: number) => {
      const value = normalizeListPageSize(size, grouped);
      setSaved({ key, size: value });
      // Use the existing guarded writer; storage failure must not block changing the visible page.
      setValueIntoLocalStorage(key, value);
    },
    [key, grouped]
  );

  return { key, pageSize, setPageSize };
}
