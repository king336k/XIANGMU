// SPDX-License-Identifier: AGPL-3.0-only
export function flowLayers<T extends { id: string; depends_on: string[] }>(nodes: T[]): T[][] {
  const ids = new Set(nodes.map((node) => node.id));
  if (ids.size !== nodes.length) throw new Error("流程节点编号重复。");
  if (nodes.some((node) => node.depends_on.some((id) => !ids.has(id)))) throw new Error("前置节点不存在。");
  const layers: T[][] = [];
  const done = new Set<string>();
  while (done.size < nodes.length) {
    const ready = nodes.filter((node) => !done.has(node.id) && node.depends_on.every((id) => done.has(id)));
    if (!ready.length) throw new Error("流程存在循环依赖。");
    layers.push(ready);
    for (const node of ready) done.add(node.id);
  }
  return layers;
}
