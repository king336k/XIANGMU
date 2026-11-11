import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { SettingsContentWrapper } from "./content-wrapper";
import { Field, fieldClass, Paging } from "@/components/quality/shared";
import { useCollectionPagination } from "@/components/quality/use-collection-pagination";
import { qualityApi, errorMessage } from "@/components/quality/api";

type Grants = {
  count: number;
  revision: number;
  projects: string[];
  results: { id: string; name: string; identifier: string }[];
};

export function DaqProjectAccess() {
  const endpoint = "/api/quality-auth/daq-project-grants/";
  const [search, setSearch] = useState("");
  const pagination = useCollectionPagination(`daq-projects:${search}`);
  const { data, error, mutate } = useSWR(
    `${endpoint}?${pagination.query}&search=${encodeURIComponent(search)}`,
    (url: string) => qualityApi.read<Grants>(url),
    { revalidateOnFocus: false }
  );
  const [draft, setDraft] = useState<{ projects: string[]; revision: number }>();
  const selected = draft?.projects ?? data?.projects ?? [];
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");

  async function save() {
    if (!data) return;
    setSaving(true);
    setNotice("");
    try {
      await qualityApi.write(endpoint, { projects: selected, expected_revision: draft?.revision ?? data.revision });
      await mutate();
      setDraft(undefined);
      setNotice("DAQ 项目授权已保存。");
    } catch (e) {
      setNotice(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <SettingsContentWrapper hugging>
      <h1 className="platform-page-title mb-3">DAQ 项目授权</h1>
      <p className="mb-5 text-13 leading-6 text-secondary">
        所有已接入的合并 DAQ 采集电脑共用此授权清单。DAQ 只能向选中的项目反馈问题和补传现场材料，上报人信息仅用于展示。
      </p>
      {error ? (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      ) : !data ? (
        <p role="status">正在加载项目…</p>
      ) : (
        <>
          <div className="mb-4 max-w-lg">
            <Field label="搜索项目">
              <input
                aria-label="搜索DAQ授权项目"
                className={fieldClass}
                placeholder="搜索项目名称或编号"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </Field>
          </div>
          <div className="overflow-x-auto rounded border border-subtle">
            <table className="w-full text-left text-13">
              <thead>
                <tr className="border-b border-subtle text-secondary">
                  <th className="w-16 p-3">授权</th>
                  <th className="p-3">项目名称</th>
                  <th className="p-3">项目编号</th>
                  <th className="p-3">反馈权限</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((row) => (
                  <tr key={row.id} className="border-b border-subtle last:border-b-0 hover:bg-layer-1">
                    <td className="p-3">
                      <input
                        aria-label={`允许DAQ向${row.name}反馈`}
                        type="checkbox"
                        checked={selected.includes(row.id)}
                        disabled={saving}
                        onChange={(e) =>
                          setDraft({
                            revision: draft?.revision ?? data.revision,
                            projects: e.target.checked ? [...selected, row.id] : selected.filter((id) => id !== row.id),
                          })
                        }
                      />
                    </td>
                    <td className="p-3">{row.name}</td>
                    <td className="p-3 text-secondary">{row.identifier}</td>
                    <td className="p-3 text-secondary">{selected.includes(row.id) ? "允许反馈" : "未授权"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.results.length && (
              <p className="p-4 text-13 text-secondary">{search ? "暂无匹配项目。" : "请先创建项目，再分配给 DAQ。"}</p>
            )}
          </div>
          <Paging {...pagination.paging} count={data.count} />
          <div className="mt-4 flex items-center gap-3">
            <Button onClick={() => void save()} disabled={saving || !draft}>
              {saving ? "保存中…" : "保存授权"}
            </Button>
            <span className="text-12 text-secondary">已选择 {selected.length} 个项目</span>
          </div>
        </>
      )}
      {notice && (
        <p role="status" className="mt-3 text-13">
          {notice}
        </p>
      )}
    </SettingsContentWrapper>
  );
}
