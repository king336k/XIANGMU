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
      assert.match(link.path, /^\/(requirements|issues|defects|quality|cycles|modules|views|knowledge|versions)(\?|$)/);
      assert.ok(!link.path.includes(":") && !link.path.includes("//"));
    }
  }
});

test("每个帮助主题都有本地配图、明确图注和真实图片资源", () => {
  for (const topic of platformGuide) {
    assert.ok(topic.screenshots.length > 0, topic.id);
    for (const image of topic.screenshots) {
      assert.match(image.src, /^\/platform-guide\/[a-z-]+\.webp$/);
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
