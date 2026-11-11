import { useResolvedProjectParams } from "@/hooks/use-resolved-project-params";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { CustomMenu } from "@plane/ui";
import { Bookmark, ChevronDown } from "lucide-react";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";
type Saved = { id: string; name: string; filters: Record<string, string> };
export function SavedViewControls({
  kind,
  params,
  onApply,
}: {
  kind: string;
  params: URLSearchParams;
  onApply: (params: URLSearchParams) => void;
}) {
  const { workspaceSlug, projectId } = useResolvedProjectParams();
  const base = `/api/workspaces/${workspaceSlug}/projects/${projectId}/quality/`;
  const supported = [
    "defects",
    "requirements",
    "cases",
    "plans",
    "executions",
    "suites",
    "releases",
    "reports",
    "articles",
  ].includes(kind);
  const { data, error, mutate } = useSWR(supported ? `${base}saved-views/?resource=${kind}` : null, (url: string) =>
    qualityApi.read<Saved[]>(url)
  );
  const [saving, setSaving] = useState(false),
    [renaming, setRenaming] = useState(false),
    [message, setMessage] = useState("");
  if (!supported) return null;
  const selected = params.get("saved_view") || "";
  const current = data?.find((row) => row.id === selected);
  const navigation = () => {
    const next = new URLSearchParams();
    for (const key of ["tab", "panel", "layout", "per_page"]) if (params.has(key)) next.set(key, params.get(key)!);
    return next;
  };
  return (
    <div className="text-12 text-secondary">
      <CustomMenu
        placement="bottom-end"
        closeOnSelect
        customButton={
          <span className="flex max-w-48 items-center gap-2 rounded-md border border-subtle px-3 py-1.5">
            <Bookmark className="size-3.5 shrink-0" />
            <span className="truncate">{current?.name || "视图"}</span>
            <ChevronDown className="size-3 shrink-0" />
          </span>
        }
      >
        <CustomMenu.MenuItem
          onClick={() => {
            const next = navigation();
            onApply(next);
          }}
        >
          全部记录
        </CustomMenu.MenuItem>
        {data?.map((row) => (
          <CustomMenu.MenuItem
            key={row.id}
            onClick={() => {
              const next = navigation();
              for (const [key, value] of Object.entries(row.filters)) next.set(key, value);
              next.set("saved_view", row.id);
              onApply(next);
            }}
          >
            {row.name}
            {selected === row.id ? " ✓" : ""}
          </CustomMenu.MenuItem>
        ))}
        <div className="my-1 border-t border-subtle" />
        <CustomMenu.MenuItem onClick={() => setSaving(true)}>保存为新视图</CustomMenu.MenuItem>
        {current && <CustomMenu.MenuItem onClick={() => setRenaming(true)}>重命名当前视图</CustomMenu.MenuItem>}
        {current && (
          <CustomMenu.MenuItem
            onClick={async () => {
              try {
                await qualityApi.write(`${base}saved-views/${selected}/`, {}, "delete");
                const next = new URLSearchParams(params);
                next.delete("saved_view");
                onApply(next);
                await mutate();
              } catch (e) {
                setMessage(errorMessage(e));
              }
            }}
          >
            删除当前视图
          </CustomMenu.MenuItem>
        )}
      </CustomMenu>
      {(error || message) && (
        <span role="status" className="text-secondary">
          {message || errorMessage(error)}
        </span>
      )}
      {saving && (
        <Modal
          title="保存视图"
          onClose={() => setSaving(false)}
          onSubmit={async (form) => {
            const filters = Object.fromEntries(
              [...params].filter(
                ([key]) =>
                  !["page", "per_page", "tab", "panel", "plan", "defect", "requirement", "q", "saved_view"].includes(
                    key
                  )
              )
            );
            const saved = await qualityApi.write<Saved>(`${base}saved-views/`, {
              name: form.get("name"),
              resource: kind,
              filters,
            });
            const next = new URLSearchParams(params);
            next.set("saved_view", saved.id);
            onApply(next);
            await mutate();
          }}
        >
          <Field label="视图名称 *">
            <input required name="name" maxLength={120} className={fieldClass} placeholder="例如：我的待回归缺陷" />
          </Field>
          <p className="text-12 text-secondary">保存为新视图和视图格式，仅自己可见。</p>
        </Modal>
      )}
      {renaming && current && (
        <Modal
          title="重命名视图"
          onClose={() => setRenaming(false)}
          onSubmit={async (form) => {
            await qualityApi.write(
              `${base}saved-views/${current.id}/`,
              { name: form.get("name"), expected_name: current.name },
              "patch"
            );
            await mutate();
          }}
        >
          <Field label="视图名称 *">
            <input name="name" required maxLength={120} defaultValue={current.name} className={fieldClass} />
          </Field>
        </Modal>
      )}
    </div>
  );
}
