import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
test("整页按可用容器宽度重排，窄屏只保留一份有权限约束的属性", () => {
  const root = read("../core/components/issues/issue-detail/root.tsx");
  const main = read("../core/components/issues/issue-detail/main-content.tsx");
  assert.ok(root.includes("work-item-detail-workspace"));
  assert.doesNotMatch(root, /fixed right-0|window\?\.innerWidth/);
  assert.equal((root.match(/<IssueDetailsSidebar/g) || []).length, 1);
  assert.ok(root.includes("canArrange={!is_archived && businessPolicy?.can_arrange === true}"));
  assert.doesNotMatch(main, /windowSize|PeekOverviewProperties/);
  assert.ok(main.includes("propertiesPanel"));
  assert.ok(main.includes("work-item-detail-grid"));
  assert.ok(main.includes("work-item-detail-content"));
  assert.ok(main.includes("work-item-detail-activity"));
});
test("详情与预览统一三块区域，容器断点控制布局且不截断长内容", () => {
  const css = read("../styles/globals.css");
  assert.match(css, /\.work-item-detail-workspace\s*\{[^}]*container-type:\s*inline-size/s);
  assert.match(css, /@container work-item-detail \(min-width:\s*960px\)/);
  assert.ok(css.includes('grid-template-areas: "content" "properties" "activity"'));
  assert.ok(css.includes('grid-template-areas: "content properties" "activity properties"'));
  assert.match(css, /\.work-item-detail-properties[\s\S]*?min-width:\s*0/);
  const peek = read("../core/components/issues/peek-overview/view.tsx");
  assert.ok(peek.includes("work-item-detail-workspace"));
  assert.ok(peek.includes("work-item-detail-grid"));
  assert.doesNotMatch(peek, /!w-88/);
});
test("缺陷详情根据弹窗实际宽度分栏，长文字和输入框限制在内容区", () => {
  const modal = read("../core/components/quality/shared.tsx");
  const defect = read("../core/components/quality/defect-detail.tsx");
  const css = read("../styles/globals.css");
  assert.ok(modal.includes("record-detail-modal"));
  assert.ok(modal.includes("record-detail-body"));
  assert.ok(defect.includes("record-detail-grid"));
  assert.doesNotMatch(defect, /md:grid-cols-\[minmax\(0,1fr\)_220px\]/);
  assert.ok(css.includes("@container record-detail (min-width: 760px)"));
  assert.match(css, /\.record-detail-body textarea\s*\{[^}]*max-height:/s);
});

test("整页铺满可用内容区，两侧边距不因大屏增加成宽空栏", () => {
  const css = read("../styles/globals.css");
  const canvas = css.match(/\.work-item-detail-canvas\s*\{([^}]+)\}/)?.[1];
  assert.ok(canvas);
  assert.doesNotMatch(canvas, /max-width: \d+px/);
  assert.match(canvas, /max-width: none/);
  assert.match(css, /minmax\(0, 1fr\) clamp\(320px, 25cqi, 420px\)/);
});

test("超宽详情并列活动区，避免取消限宽后评论输入框再次铺成长条", () => {
  const css = read("../styles/globals.css");
  assert.match(css, /@container work-item-detail \(min-width: 1600px\)/);
  assert.ok(css.includes('grid-template-areas: "content activity properties"'));
  assert.match(css, /clamp\(420px, 32cqi, 620px\)/);
});
test("窄屏缺陷和需求的标题独占一行，不被状态及编辑按钮挤成竖排", () => {
  for (const file of ["defect-detail", "requirements-workbench"])
    assert.ok(read(`../core/components/quality/${file}.tsx`).includes("record-detail-heading"));
  const css = read("../styles/globals.css");
  assert.match(css, /\.record-detail-heading\s*\{[^}]*flex-direction:\s*column/s);
});
