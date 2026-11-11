// SPDX-License-Identifier: AGPL-3.0-only
import { List, Table2, Columns3, ChevronDown, Check } from "lucide-react";
import { CustomMenu } from "@plane/ui";
export type RecordLayout = "list" | "table" | "board";
export function recordLayout(params: URLSearchParams): RecordLayout {
  const value = params.get("layout");
  return value === "table" || value === "board" ? value : "list";
}
export function LayoutControls({
  params,
  onApply,
}: {
  params: URLSearchParams;
  onApply: (params: URLSearchParams) => void;
}) {
  const selected = recordLayout(params);
  const layouts = [
    { key: "list", title: "列表视图", icon: List },
    { key: "table", title: "表格视图", icon: Table2 },
    { key: "board", title: "看板视图", icon: Columns3 },
  ] as const;
  const current = layouts.find(({ key }) => key === selected)!;
  const Icon = current.icon;
  return (
    <CustomMenu
      placement="bottom-end"
      closeOnSelect
      customButton={
        <span className="flex shrink-0 items-center gap-2 rounded-md border border-subtle px-3 py-1.5 text-12 whitespace-nowrap text-secondary">
          <Icon className="size-3.5" />
          <span>显示方式</span>
          <ChevronDown className="size-3" />
        </span>
      }
    >
      {layouts.map(({ key, title, icon: ItemIcon }) => (
        <CustomMenu.MenuItem
          key={key}
          onClick={() => {
            const next = new URLSearchParams(params);
            next.set("layout", key);
            onApply(next);
          }}
        >
          <ItemIcon className="size-4" />
          <span>{title}</span>
          {selected === key && <Check className="ml-auto size-3.5" aria-label="当前视图" />}
        </CustomMenu.MenuItem>
      ))}
    </CustomMenu>
  );
}
