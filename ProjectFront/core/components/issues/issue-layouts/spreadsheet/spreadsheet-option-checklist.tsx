import { useEffect, useState } from "react";
import { useTranslation } from "@plane/i18n";
import type { IFilterOption, TFilterValue, TSupportedFilterFieldConfigs } from "@plane/types";

type Props = {
  config: TSupportedFilterFieldConfigs<TFilterValue>;
  property: string;
  value: unknown;
  disabled: boolean;
  onChange: (value: string[]) => void;
};
export function SpreadsheetOptionChecklist({ config, property, value, disabled, onChange }: Props) {
  const { t } = useTranslation();
  const [query, setQuery] = useState(""),
    [options, setOptions] = useState<IFilterOption<TFilterValue>[]>([]),
    [loading, setLoading] = useState(true),
    [failed, setFailed] = useState(false),
    [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailed(false);
    Promise.resolve()
      .then(() =>
        "getOptions" in config
          ? typeof config.getOptions === "function"
            ? config.getOptions()
            : config.getOptions
          : []
      )
      .then((data) => {
        if (active) setOptions(data);
      })
      .catch(() => {
        if (active) setFailed(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [config, attempt]);
  const selected = Array.isArray(value) ? value.map(String) : value == null ? [] : [String(value)];
  const labelFor = (option: IFilterOption<TFilterValue>) =>
    property === "priority" ? t(String(option.value)) : String(option.label);
  const visible = options.filter((option) => labelFor(option).toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <div className="space-y-2">
      <input
        aria-label="搜索选项"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="搜索选项"
        className="h-8 w-full rounded border border-subtle bg-surface-1 px-2 text-12 outline-none focus:border-accent-strong"
      />
      <div className="max-h-64 overflow-y-auto">
        {loading ? (
          <p role="status" className="py-2 text-12 text-secondary">
            正在加载…
          </p>
        ) : failed ? (
          <button type="button" onClick={() => setAttempt(attempt + 1)} className="py-2 text-12 text-accent-primary">
            加载失败，点击重试
          </button>
        ) : visible.length === 0 ? (
          <p className="py-2 text-12 text-secondary">没有匹配项</p>
        ) : (
          visible.map((option) => (
            <label
              key={String(option.value)}
              className="flex cursor-pointer items-center gap-2 rounded px-1 py-2 text-12 text-primary hover:bg-layer-1"
            >
              <input
                type="checkbox"
                checked={selected.includes(String(option.value))}
                disabled={disabled || option.disabled}
                onChange={(event) =>
                  onChange(
                    event.target.checked
                      ? [...selected, String(option.value)]
                      : selected.filter((id) => id !== String(option.value))
                  )
                }
              />
              {option.icon && (
                <span aria-hidden="true" className="shrink-0">
                  {option.icon}
                </span>
              )}
              <span className="min-w-0 break-words">{labelFor(option)}</span>
            </label>
          ))
        )}
      </div>
    </div>
  );
}
