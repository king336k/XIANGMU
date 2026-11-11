/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState, useEffect, useCallback } from "react";

export const getValueFromLocalStorage = (key: string, defaultValue: any) => {
  if (typeof window === "undefined") return defaultValue;
  try {
    const item = window.localStorage.getItem(key);
    return item ? JSON.parse(item) : defaultValue;
  } catch (_error) {
    try {
      window.localStorage.removeItem(key);
    } catch {
      // Reading and removing can both be denied by browser storage policy.
    }
    return defaultValue;
  }
};

export const setValueIntoLocalStorage = (key: string, value: any) => {
  if (typeof window === "undefined") return false;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch (_error) {
    return false;
  }
};

// TODO: Remove this once we migrate to the new hooks from plane/helpers
const useLocalStorage = <T,>(key: string, initialValue: T) => {
  const [storedValue, setStoredValue] = useState<T | null>(() => getValueFromLocalStorage(key, initialValue));

  const setValue = useCallback(
    (value: T) => {
      setValueIntoLocalStorage(key, value);
      setStoredValue(value);
      window.dispatchEvent(new Event(`local-storage:${key}`));
    },
    [key]
  );

  const clearValue = useCallback(() => {
    try {
      window.localStorage.removeItem(key);
    } catch {
      // Keep the in-memory preference editable when persistence is unavailable.
    }
    setStoredValue(null);
    window.dispatchEvent(new Event(`local-storage:${key}`));
  }, [key]);

  const reHydrate = useCallback(() => {
    const data = getValueFromLocalStorage(key, initialValue);
    setStoredValue(data);
  }, [key, initialValue]);

  useEffect(() => {
    window.addEventListener(`local-storage:${key}`, reHydrate);
    return () => {
      window.removeEventListener(`local-storage:${key}`, reHydrate);
    };
  }, [key, reHydrate]);

  return { storedValue, setValue, clearValue } as const;
};

export default useLocalStorage;
