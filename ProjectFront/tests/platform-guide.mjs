import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const code = ts.transpileModule(
  readFileSync(new URL("../core/components/workspace/sidebar/help-section/platform-guide.ts", import.meta.url), "utf8"),
  {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  }
).outputText;
const { platformGuide, findGuideTopics } = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`
);
test("文档搜索覆盖正文、多词、空格、大小写与无匹配", () => {
  assert.equal(findGuideTopics("  ").length, platformGuide.length);
  assert.ok(findGuideTopics("模型 密钥").some((topic) => topic.id === "knowledge"));
  assert.ok(findGuideTopics("daq").some((topic) => topic.id === "integrations"));
  assert.ok(findGuideTopics("日志").some((topic) => topic.id === "defects"));
  assert.deepEqual(findGuideTopics("不存在的帮助主题XYZ"), []);
});
test("项目快捷入口始终为当前项目内相对地址", () => {
  for (const topic of platformGuide) {
    for (const link of topic.links) {
      assert.ok(
        /^\/(requirements|issues|defects|quality|cycles|modules|views|knowledge|versions)(\?|$)/.test(link.path) ||
          /^\/settings\/(connections|daq-projects)\/$/.test(link.path),
        link.path
      );
      assert.ok(!link.path.includes(":") && !link.path.includes("//"));
    }
  }
});

test("每个帮助主题都有本地配图、明确图注和真实图片资源", () => {
  for (const topic of platformGuide) {
    assert.ok(topic.screenshots.length > 0, topic.id);
    for (const image of topic.screenshots) {
      assert.match(image.src, /^\/platform-guide\/[a-z-]+\.(webp|svg)$/);
      assert.ok(image.title && image.caption);
      assert.ok(existsSync(new URL(`../public${image.src}`, import.meta.url)), image.src);
    }
  }
});

test("成员说明明确基础反馈能力，无独立数采员业务岗位", () => {
  const roles = platformGuide.find((topic) => topic.id === "roles");
  const text = [roles.summary, ...roles.paragraphs, ...roles.steps, ...roles.screenshots.map((s) => s.caption)].join(
    " "
  );
  assert.match(text, /可写项目成员.*反馈/);
  assert.doesNotMatch(text, /数采员|五类|仅可查看/);
});

test("帮助按公共操作和角色指南分组，支持按组检索角色和图注", () => {
  assert.ok(platformGuide.every((topic) => ["common", "roles"].includes(topic.section)));
  for (const id of ["administrator", "project-manager", "technician", "tester", "reporter"]) {
    const topic = platformGuide.find((row) => row.id === id);
    assert.equal(topic?.section, "roles", id);
    assert.ok(topic.checkpoints.length && topic.related.length, id);
  }
  assert.ok(findGuideTopics("", "common").every((topic) => topic.section === "common"));
  assert.ok(findGuideTopics("", "roles").every((topic) => topic.section === "roles"));
  assert.equal(findGuideTopics("", "roles").length, 5);
  assert.ok(findGuideTopics("修复方案 审核", "roles").some((row) => row.id === "technician"));
  for (const topic of platformGuide) {
    for (const id of topic.related)
      assert.ok(
        platformGuide.some((row) => row.id === id),
        id
      );
    assert.ok(findGuideTopics(topic.screenshots[0].title).some((row) => row.id === topic.id));
  }
});
test("缺陷文档说明本轮审核验收门禁和页内阶段图，不再指导状态直接关闭", () => {
  const topic = platformGuide.find((row) => row.id === "defects");
  const text = JSON.stringify(topic);
  for (const term of ["修复方案", "审核", "人工验证", "用例回归", "验收关闭", "阶段图", "轮次"])
    assert.ok(text.includes(term), term);
  assert.doesNotMatch(text, /列表.*直接更新处理状态|验证通过后关闭/);
});

test("测试帮助覆盖无法判定及证据说明，报告目标区分经理与系统连接配置", () => {
  const tester = JSON.stringify(platformGuide.find((topic) => topic.id === "tester"));
  assert.match(tester, /无法判定/);
  assert.match(tester, /原因分类.*说明.*下一步/);
  assert.match(
    JSON.stringify(platformGuide.find((topic) => topic.id === "integrations")),
    /项目报告接收目标.*项目经理或管理员/
  );
});
