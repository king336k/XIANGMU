import { useCollectionPagination } from "./use-collection-pagination";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal, Paging } from "./shared";
import { nodeKinds } from "./version-types";
import type { FlowNode, VersionDetail } from "./version-types";
import type { Context } from "./types";
type Option = { id: string; name: string; version?: string };
export function VersionRecordPicker({
  base,
  kind,
  value,
  onChange,
}: {
  base: string;
  kind: string;
  value: string;
  onChange: (row: Option) => void;
}) {
  const [search, setSearch] = useState("");
  const pagination = useCollectionPagination(`${base}:${kind}:${search}`, undefined, 25);
  const { data, error } = useSWR(
    `${base}versions/options/?${new URLSearchParams({ kind, search, page: String(pagination.page), per_page: String(pagination.perPage) })}`,
    (url: string) => qualityApi.read<{ results: Option[]; count: number }>(url)
  );
  return (
    <div className="space-y-2 rounded-md border border-subtle p-3">
      <input
        aria-label="搜索关联记录"
        placeholder="按名称搜索"
        className={fieldClass}
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
          pagination.paging.onChange(1);
        }}
      />
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      <div className="max-h-52 space-y-1 overflow-y-auto">
        {data?.results.map((row) => (
          <button
            key={row.id}
            type="button"
            onClick={() => onChange(row)}
            className={`block w-full rounded px-2 py-2 text-left text-12 ${value === row.id ? "bg-accent-subtle text-accent-primary" : "text-secondary hover:bg-layer-1"}`}
          >
            {row.name}
            {value === row.id ? " ✓" : ""}
          </button>
        ))}
        {data?.count === 0 && <p className="py-3 text-12 text-secondary">没有匹配记录。</p>}
      </div>
      {data && <Paging {...pagination.paging} count={data.count} pageSizes={[25, 50, 100]} />}
    </div>
  );
}
export function VersionForm({
  base,
  value,
  context,
  onClose,
  onSaved,
}: {
  base: string;
  value?: VersionDetail;
  context: Context;
  onClose: () => void;
  onSaved: (version: VersionDetail) => void;
}) {
  const [cycle, setCycle] = useState<{ id: string; name: string }>({
    id: value?.cycle_id || "",
    name: value?.cycle_name || "",
  });
  const [showCycles, setShowCycles] = useState(false);
  const [release, setRelease] = useState(value?.quality_release_id || "");
  const [showReleases, setShowReleases] = useState(false);
  return (
    <Modal
      title={value ? "编辑版本计划" : "新建版本"}
      onClose={onClose}
      onSubmit={async (form) => {
        const result = await qualityApi.write<VersionDetail>(
          `${base}versions/${value ? value.id + "/" : ""}`,
          {
            name: form.get("name"),
            version: form.get("version"),
            description: form.get("description"),
            owner_id: form.get("owner_id") || null,
            start_date: form.get("start_date") || null,
            target_date: form.get("target_date") || null,
            cycle_id: cycle.id || null,
            quality_release_id: release || null,
            ...(value ? { expected_version: value.edit_version } : {}),
          },
          value ? "patch" : "post"
        );
        onSaved(result);
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="版本号 *">
          <input
            name="version"
            required
            readOnly={!!value}
            maxLength={120}
            defaultValue={value?.version}
            placeholder="例如 v2.1.0"
            className={fieldClass}
          />
        </Field>
        <Field label="版本名称 *">
          <input
            name="name"
            required
            maxLength={255}
            defaultValue={value?.name}
            placeholder="例如 采集稳定性改进"
            className={fieldClass}
          />
        </Field>
        <Field label="开始日期">
          <input type="date" name="start_date" defaultValue={value?.start_date || ""} className={fieldClass} />
        </Field>
        <Field label="目标发布日期">
          <input type="date" name="target_date" defaultValue={value?.target_date || ""} className={fieldClass} />
        </Field>
      </div>
      <Field label="版本负责人">
        <select name="owner_id" defaultValue={value?.owner_id || ""} className={fieldClass}>
          <option value="">未指定</option>
          {context.members.map((member) => (
            <option key={member.id} value={member.id}>
              {member.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="版本目标">
        <textarea
          name="description"
          rows={3}
          maxLength={20000}
          defaultValue={value?.description}
          className={fieldClass}
        />
      </Field>
      <details className="space-y-3 text-12 text-secondary">
        <summary className="cursor-pointer">关联迭代与发布检查（可选）</summary>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button variant="neutral-primary" onClick={() => setShowCycles(!showCycles)}>
            {cycle.name || "选择迭代周期"}
          </Button>
          {cycle.id && (
            <button type="button" className="text-12" onClick={() => setCycle({ id: "", name: "" })}>
              取消关联
            </button>
          )}
        </div>
        {showCycles && (
          <VersionRecordPicker
            base={base}
            kind="cycle"
            value={cycle.id}
            onChange={(row) => {
              setCycle(row);
              setShowCycles(false);
            }}
          />
        )}
        <Button variant="neutral-primary" onClick={() => setShowReleases(!showReleases)}>
          {release ? "已选择发布检查" : "选择发布检查"}
        </Button>
        {release && (
          <button type="button" onClick={() => setRelease("")} className="ml-2 text-12">
            取消关联
          </button>
        )}
        {showReleases && (
          <VersionRecordPicker
            base={base}
            kind="release"
            value={release}
            onChange={(row) => {
              setRelease(row.id);
              setShowReleases(false);
            }}
          />
        )}
      </details>
    </Modal>
  );
}
export function VersionNodeForm({
  base,
  version,
  node,
  context,
  onClose,
  onSaved,
}: {
  base: string;
  version: VersionDetail;
  node?: FlowNode;
  context: Context;
  onClose: () => void;
  onSaved: (version: VersionDetail) => void;
}) {
  const [kind, setKind] = useState<FlowNode["kind"]>(node?.kind || "issue");
  const [record, setRecord] = useState({ id: node?.object_id || "", name: node?.name || "" });
  const [dependencies, setDependencies] = useState(node?.depends_on || []);
  const [title, setTitle] = useState(node?.name || "");
  return (
    <Modal
      title={node ? "编辑节点" : "添加流程节点"}
      width="wide"
      onClose={onClose}
      onSubmit={async (form) => {
        if (kind !== "milestone" && !record.id) throw new Error("请先选择关联记录。");
        const value: FlowNode = {
          id: node?.id || `node-${crypto.randomUUID().slice(0, 8)}`,
          name: String(form.get("name")),
          kind,
          ...(kind !== "milestone" ? { object_id: record.id } : {}),
          owner_id: String(form.get("owner_id") || "") || null,
          depends_on: dependencies,
          join: form.get("join") === "any" ? "any" : "all",
          required: form.get("required") === "on",
          target_date: String(form.get("target_date") || "") || null,
        };
        const nodes = node
          ? version.flow_nodes.map((item) => (item.id === node.id ? value : item))
          : [...version.flow_nodes, value];
        const result = await qualityApi.write<VersionDetail>(
          `${base}versions/${version.id}/`,
          { expected_version: version.edit_version, flow_nodes: nodes },
          "patch"
        );
        onSaved(result);
      }}
    >
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-3">
          <Field label="节点类型">
            <select
              value={kind}
              className={fieldClass}
              onChange={(event) => {
                setKind(event.target.value as FlowNode["kind"]);
                setRecord({ id: "", name: "" });
              }}
            >
              {Object.entries(nodeKinds).map(([key, name]) => (
                <option key={key} value={key}>
                  {name}
                </option>
              ))}
            </select>
          </Field>
          {kind !== "milestone" && (
            <VersionRecordPicker
              base={base}
              kind={kind}
              value={record.id}
              onChange={(row) => {
                setRecord(row);
                if (!title) setTitle(row.name);
              }}
            />
          )}
          <Field label="节点名称 *">
            <input
              name="name"
              required
              maxLength={160}
              className={fieldClass}
              placeholder="如：GH 联调、统筹评审、接口开发"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </Field>
          <Field label="负责人">
            <select name="owner_id" defaultValue={node?.owner_id || ""} className={fieldClass}>
              <option value="">手动分派</option>
              {context.members.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="目标日期">
            <input type="date" name="target_date" defaultValue={node?.target_date || ""} className={fieldClass} />
          </Field>
        </div>
        <div className="space-y-3">
          <h3 className="text-13 font-medium">前置节点</h3>
          <p className="text-12 text-secondary">留空表示起始节点。</p>
          <div className="max-h-60 space-y-1 overflow-y-auto rounded border border-subtle p-2">
            {version.flow_nodes
              .filter((item) => item.id !== node?.id)
              .map((item) => (
                <label key={item.id} className="flex items-center gap-2 rounded px-2 py-2 text-12 hover:bg-layer-1">
                  <input
                    type="checkbox"
                    checked={dependencies.includes(item.id)}
                    onChange={(event) =>
                      setDependencies(
                        event.target.checked ? [...dependencies, item.id] : dependencies.filter((id) => id !== item.id)
                      )
                    }
                  />
                  {item.name}
                </label>
              ))}
            {version.flow_nodes.length === 0 && <p className="p-2 text-12 text-secondary">暂无其他节点。</p>}
          </div>
          <Field label="汇合条件">
            <select name="join" defaultValue={node?.join || "all"} className={fieldClass}>
              <option value="all">全部前置完成</option>
              <option value="any">任一前置完成</option>
            </select>
          </Field>
          <label className="flex items-center gap-2 text-12">
            <input type="checkbox" name="required" defaultChecked={node?.required ?? true} />
            发布前必须完成此节点
          </label>
          <p className="text-11 leading-5 text-tertiary">修改流程后，里程碑需重新确认。</p>
        </div>
      </div>
    </Modal>
  );
}
