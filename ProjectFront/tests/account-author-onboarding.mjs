import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const Tour = () => null,
  Button = () => null;
function load(file, mocks = {}) {
  const e = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/components/" + file, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
    }).outputText
  )(
    (id) =>
      mocks[id] ??
      (["react", "react/jsx-runtime"].includes(id) ? require(id) : new Proxy({}, { get: () => () => null })),
    e
  );
  return e;
}
const nodes = (t) =>
  !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
test("first home visit never automatically mounts a welcome tour, while help remains manually reachable", () => {
  const { WorkspaceHomeView } = load("home/root.tsx", {
    "mobx-react": { observer: (f) => f },
    "next/navigation": { useParams: () => ({ workspaceSlug: "w" }) },
    "@/hooks/store/user": {
      useUserProfile: () => ({
        data: { is_onboarded: true, is_navigation_tour_completed: true, is_tour_completed: false },
      }),
    },
    "@/hooks/store/use-home": { useHome: () => ({ fetchWidgets() {} }) },
    "../onboarding/tour/root": { TourRoot: Tour },
  });
  assert.equal(nodes(WorkspaceHomeView()).filter((n) => n.type === Tour).length, 0);
  const source = readFileSync(
    new URL("../core/components/workspace/sidebar/help-section/root.tsx", import.meta.url),
    "utf8"
  );
  assert.match(source, /onClick=\{\(\) => setShowDocumentation\(true\)\}/);
  assert.match(source, /PlatformHelp/);
});
test("ordinary non-authors cannot edit or submit and receive a short reason on reachable buttons", () => {
  const notices = [],
    writes = [];
  const { SolutionCard } = load("quality/solution-card.tsx", {
    "@plane/ui": { Button },
    "@plane/propel/toast": { setToast: (value) => notices.push(value), TOAST_TYPE: { INFO: "info" } },
    "./solution-data": { currentSolutionRevision: () => null, solutionStatus: {}, solutionTone: {} },
  });
  for (const actor of ["manager", "other-tech"]) {
    const tree = SolutionCard({
      solution: {
        id: "s",
        title: "方案",
        status: "draft",
        created_by_id: "author",
        can_edit: true,
        can_submit: true,
        can_review: false,
        revisions: [],
      },
      context: { user_id: actor, members: [], is_administrator: actor === "admin" },
      onEdit: () => writes.push("edit"),
      onSubmit: () => writes.push("submit"),
    });
    const buttons = nodes(tree).filter((n) => n.type === Button);
    assert.equal(buttons.length, 2);
    for (const button of buttons) {
      assert.equal(button.props["aria-disabled"], true);
      assert.notEqual(button.props.disabled, true);
      button.props.onClick();
    }
  }
  assert.deepEqual(writes, []);
  assert.equal(notices.length, 4);
  assert.ok(notices.every((n) => n.message === "仅方案创建人可操作"));
});
test("account identity uses current business roles, deduplicates multi-duty and never treats access levels as roles", () => {
  const { accountDutyLabel } = load("settings/member-management-data.ts");
  assert.equal(accountDutyLabel({ is_administrator: true, business_roles: ["TECHNICIAN"] }), "管理员");
  assert.equal(
    accountDutyLabel({ business_roles: ["REGRESSION_TESTER", "TECHNICIAN", "TECHNICIAN"] }),
    "技术员、测试员"
  );
  assert.equal(accountDutyLabel({ business_roles: ["PROJECT_MANAGER", "TECHNICIAN"] }), "项目经理、技术员");
  assert.equal(accountDutyLabel({ business_roles: [], role: 20 }), "未分配岗位");
});

test("solution creator actions still require server capability while author review remains unchanged", () => {
  const actions = [];
  const { SolutionCard } = load("quality/solution-card.tsx", {
    "@plane/ui": { Button },
    "./solution-data": { currentSolutionRevision: () => null, solutionStatus: {}, solutionTone: {} },
  });
  const props = {
    solution: {
      id: "s",
      title: "方案",
      status: "draft",
      created_by_id: "author",
      can_edit: true,
      can_submit: true,
      can_review: true,
      revisions: [],
    },
    context: { user_id: "author", members: [] },
    onEdit: () => actions.push("edit"),
    onSubmit: () => actions.push("submit"),
    onReview: () => actions.push("review"),
  };
  const buttons = nodes(SolutionCard(props)).filter((n) => n.type === Button);
  for (const button of buttons) button.props.onClick();
  assert.deepEqual(actions, ["edit", "submit", "review"]);
  const locked = SolutionCard({
    ...props,
    solution: { ...props.solution, can_edit: false, can_submit: false, can_review: false },
  });
  assert.equal(nodes(locked).filter((n) => n.type === Button).length, 0);
});

test("canonical platform administrators may handle another author's solution, workspace access role alone does not grant it", () => {
  const actions = [],
    notices = [];
  const { SolutionCard } = load("quality/solution-card.tsx", {
    "@plane/ui": { Button },
    "@plane/propel/toast": { setToast: (notice) => notices.push(notice), TOAST_TYPE: { INFO: "info" } },
    "./solution-data": { currentSolutionRevision: () => null, solutionStatus: {}, solutionTone: {} },
  });
  const solution = {
    id: "s",
    title: "方案",
    status: "draft",
    created_by_id: "other",
    can_edit: true,
    can_submit: true,
    can_review: false,
    revisions: [],
  };
  for (const context of [
    { user_id: "admin", is_administrator: true },
    { user_id: "admin", business_roles: ["PLATFORM_ADMIN"] },
  ]) {
    const buttons = nodes(
      SolutionCard({
        solution,
        context: { ...context, members: [] },
        onEdit: () => actions.push("edit"),
        onSubmit: () => actions.push("submit"),
      })
    ).filter((n) => n.type === Button);
    for (const button of buttons) {
      assert.equal(button.props["aria-disabled"], false);
      button.props.onClick();
    }
  }
  assert.deepEqual(actions, ["edit", "submit", "edit", "submit"]);
  const denied = nodes(
    SolutionCard({
      solution,
      context: {
        user_id: "manager",
        is_administrator: false,
        business_roles: ["PLATFORM_ADMIN"],
        role: 20,
        members: [],
      },
      onEdit: () => actions.push("bad"),
      onSubmit: () => actions.push("bad"),
    })
  ).filter((n) => n.type === Button);
  denied.forEach((button) => button.props.onClick());
  assert.equal(actions.length, 4);
  assert.equal(notices.length, 2);
});
