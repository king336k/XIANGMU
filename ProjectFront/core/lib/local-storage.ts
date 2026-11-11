/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { isEmpty } from "lodash-es";

export const storage = {
  set: (key: string, value: object | string | boolean): void => {
    if (typeof window === "undefined" || !key) return undefined;
    const tempValue: string | undefined = ["string", "boolean"].includes(typeof value)
      ? value.toString()
      : isEmpty(value)
        ? undefined
        : JSON.stringify(value);
    if (!tempValue) return undefined;
    try {
      window.localStorage.setItem(key, tempValue);
    } catch {
      // Persisting a preference must not prevent the current page from working.
    }
  },

  get: (key: string): string | undefined => {
    if (typeof window === "undefined") return undefined;
    try {
      const item = window.localStorage.getItem(key);
      return item ? item : undefined;
    } catch {
      return undefined;
    }
  },

  remove: (key: string): void => {
    if (typeof window === "undefined" || !key) return undefined;
    try {
      window.localStorage.removeItem(key);
    } catch {
      // A blocked storage area has no persisted preference to clear.
    }
  },
};
