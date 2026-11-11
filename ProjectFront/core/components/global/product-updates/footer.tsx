// SPDX-License-Identifier: AGPL-3.0-only
export function ProductUpdatesFooter() {
  return (
    <div className="m-6 mb-4 text-right">
      <button
        type="button"
        onClick={() => window.dispatchEvent(new Event("platform-help-open"))}
        className="text-12 text-secondary hover:text-primary"
      >
        平台使用文档
      </button>
    </div>
  );
}
