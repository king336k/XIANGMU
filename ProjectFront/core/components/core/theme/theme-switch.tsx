/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import type { I_THEME_OPTION } from "@plane/constants";
import { THEME_OPTIONS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
// constants
import { CustomSelect } from "@plane/ui";
import { Check } from "lucide-react";
// ui

type Props = {
  value: I_THEME_OPTION | null;
  onChange: (value: I_THEME_OPTION) => void;
  presentation?: "dropdown" | "cards";
};

export function ThemeSwitch(props: Props) {
  const { value, onChange, presentation = "dropdown" } = props;
  // translation
  const { t } = useTranslation();

  if (presentation === "cards")
    return (
      <div role="group" aria-label="选择主题" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {THEME_OPTIONS.map((option) => {
          const selected = option.value === value?.value;
          const dark = option.type === "dark";
          return (
            <button
              key={option.value}
              type="button"
              aria-label={t(option.key)}
              aria-pressed={selected}
              onClick={() => onChange(option)}
              className={`focus-visible:outline-accent-primary min-w-0 rounded-md border p-2.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 ${selected ? "border-accent-strong bg-accent-subtle" : "border-subtle hover:border-strong hover:bg-layer-1"}`}
            >
              <div
                aria-hidden="true"
                className="mb-2 flex h-16 overflow-hidden rounded border border-subtle"
                style={{ background: option.icon.color1 }}
              >
                <div
                  className="w-1/4 border-r border-black/10 p-1.5"
                  style={{ background: dark ? "#262a30" : "#edf0f4" }}
                >
                  <div className="mb-2 h-1.5 w-3 rounded-sm" style={{ background: option.icon.color2 }} />
                  <div className="mb-1 h-1 w-full rounded-sm bg-black/15" />
                  <div className="h-1 w-2/3 rounded-sm bg-black/15" />
                </div>
                <div className="flex-1 space-y-1.5 p-2">
                  <div className="h-1.5 w-2/3 rounded-sm" style={{ background: dark ? "#cbd5e1" : "#667085" }} />
                  <div className="h-1 w-full rounded-sm" style={{ background: dark ? "#475569" : "#d0d5dd" }} />
                  <div className="h-1 w-4/5 rounded-sm" style={{ background: dark ? "#475569" : "#d0d5dd" }} />
                  <div className="h-2 w-1/3 rounded-sm" style={{ background: option.icon.color2 }} />
                </div>
              </div>
              <span className="flex items-center justify-between gap-1 text-12 font-medium">
                <span>{t(option.key)}</span>
                {selected && <Check className="size-3.5 shrink-0 text-accent-primary" />}
              </span>
            </button>
          );
        })}
      </div>
    );

  return (
    <CustomSelect
      value={value}
      label={
        value ? (
          <div className="flex items-center gap-2">
            <div
              className="relative flex h-4 w-4 rotate-45 transform items-center justify-center rounded-full border-1"
              style={{
                borderColor: value.icon.border,
              }}
            >
              <div
                className="h-full w-1/2 rounded-l-full"
                style={{
                  background: value.icon.color1,
                }}
              />
              <div
                className="h-full w-1/2 rounded-r-full border-l"
                style={{
                  borderLeftColor: value.icon.border,
                  background: value.icon.color2,
                }}
              />
            </div>
            {t(value.key)}
          </div>
        ) : (
          t("select_your_theme")
        )
      }
      onChange={onChange}
      buttonClassName="border border-subtle-1"
      placement="bottom-end"
      input
    >
      {THEME_OPTIONS.map((themeOption) => (
        <CustomSelect.Option key={themeOption.value} value={themeOption}>
          <div className="flex items-center gap-2">
            <div
              className="relative flex h-4 w-4 rotate-45 transform items-center justify-center rounded-full border border-1"
              style={{
                borderColor: themeOption.icon.border,
              }}
            >
              <div
                className="h-full w-1/2 rounded-l-full"
                style={{
                  background: themeOption.icon.color1,
                }}
              />
              <div
                className="h-full w-1/2 rounded-r-full border-l"
                style={{
                  borderLeftColor: themeOption.icon.border,
                  background: themeOption.icon.color2,
                }}
              />
            </div>
            {t(themeOption.key)}
          </div>
        </CustomSelect.Option>
      ))}
    </CustomSelect>
  );
}
