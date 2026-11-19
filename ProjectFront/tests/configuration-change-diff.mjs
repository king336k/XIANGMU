import assert from "node:assert/strict";
import test from "node:test";
import { ConfigurationChangeDiff } from "./configuration-diff-fixture.js";
const nodes = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
const text = (tree) =>
  nodes(tree)
    .flatMap((node) => [node.props?.children].flat())
    .filter((value) => typeof value === "string")
    .join("");
test("split JSON diff shows the actual path once and never copies one sides line to the other", () => {
  const tree = ConfigurationChangeDiff({
    command: {
      path: "/home/robot/config.json",
      changes: [
        {
          key: "robot_port",
          before: 18778,
          after: 18777,
          before_exists: true,
          after_exists: true,
          before_line: 4,
          after_line: 6,
        },
      ],
    },
  });
  assert.equal(nodes(tree).filter((node) => node.type === "h5").length, 1);
  assert.equal(text(tree).split("/home/robot/config.json").length - 1, 1);
  const before = nodes(tree).find((node) => node.props?.["aria-label"] === "修改前 robot_port");
  const after = nodes(tree).find((node) => node.props?.["aria-label"] === "修改后 robot_port");
  assert.match(text(before), /− 修改前.*第4行/);
  assert.doesNotMatch(text(before), /第6行/);
  assert.match(text(after), /\+ 修改后.*第6行/);
  assert.doesNotMatch(text(after), /第4行/);
  assert.equal(nodes(before).find((node) => node.type === "pre").props.children, '"robot_port": 18778');
  assert.equal(nodes(after).find((node) => node.type === "pre").props.children, '"robot_port": 18777');
  assert.match(JSON.stringify(tree), /sm:grid-cols-2/);
  assert.match(JSON.stringify(before), /bg-danger-subtle/);
  assert.match(JSON.stringify(after), /bg-success-subtle/);
});
test("new deleted null boolean and object values stay factual without invented source context", () => {
  const changes = [
    { key: "nullable", before: null, after: false, before_exists: true, after_exists: true, after_line: 7 },
    { key: "added", after: { enabled: true }, before_exists: false, after_exists: true },
    { key: "removed", before: 0, before_exists: true, after_exists: false },
  ];
  const tree = ConfigurationChangeDiff({ command: { path: "/config.json", changes } });
  assert.match(text(tree), /"nullable": null/);
  assert.match(text(tree), /"nullable": false/);
  assert.match(text(tree), /新增字段/);
  assert.match(text(tree), /删除字段/);
  assert.match(text(tree), /字段不存在/);
  assert.match(text(tree), /"added": \{\n  "enabled": true\n\}/);
  const before = nodes(tree).find((node) => node.props?.["aria-label"] === "修改前 nullable");
  assert.match(text(before), /行号未记录/);
  assert.doesNotMatch(text(before), /第7行/);
});

test("backup and checksum display friendly recorded states while long values stay in nested technical information", () => {
  const before = "a".repeat(64),
    after = "b".repeat(64),
    backup = "/home/robot/config.json.backup-95f89e89-3d92-4f6c-a6aa-9b95fddfcd88";
  const tree = ConfigurationChangeDiff({
    command: {
      status: "done",
      ok: true,
      exit_code: 0,
      path: "/home/robot/config.json",
      changes: [
        {
          key: "enabled",
          before: false,
          after: true,
          before_exists: true,
          after_exists: true,
          backup,
          before_sha256: before,
          after_sha256: after,
        },
      ],
    },
  });
  const check = nodes(tree).find((node) => node.type === "details");
  const primary = [check.props.children].flat().filter((node) => node?.type !== "details");
  assert.match(text(primary), /备份已保存/);
  assert.match(text(primary), /修改前校验值已记录/);
  assert.match(text(primary), /修改后校验值已记录/);
  assert.ok(!text(primary).includes(before) && !text(primary).includes(after) && !text(primary).includes(backup));
  assert.doesNotMatch(text(primary), /校验通过/);
  const technical = nodes(check).find((node) => node !== check && node.type === "details");
  assert.equal(technical.props.open, undefined);
  assert.match(text(technical), /config.json.backup-/);
  assert.ok(text(technical).includes(before) && text(technical).includes(after));
});
