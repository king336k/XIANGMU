// SPDX-License-Identifier: AGPL-3.0-only
import { PlaneVersionNumber } from "./version-number";

export function PlatformAbout() {
  return (
    <details className="mx-3 mt-6 border-t border-subtle px-2 pt-3 pb-4 text-11 text-tertiary">
      <summary className="cursor-pointer hover:text-secondary">关于平台</summary>
      <div className="pt-3 text-secondary">
        <PlaneVersionNumber />
      </div>
    </details>
  );
}
