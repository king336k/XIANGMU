import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
function load(path, mocks) {
  const exports = {};
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", code)((id) => mocks[id] || require(id), exports);
  return exports;
}
test("公共头像等比裁剪，加载失败回退姓名占位，更换图片后可以重新加载", () => {
  let failed;
  const { Avatar } = load("../../packages/ui/src/avatar/avatar.tsx", {
    react: {
      ...React,
      useState: () => [
        failed,
        (value) => {
          failed = value;
        },
      ],
    },
    "@plane/propel/tooltip": { Tooltip: () => null },
    "../utils": { cn: (...values) => values.filter((x) => typeof x === "string").join(" ") },
    "./helper": {
      getSizeInfo: () => ({ avatarSize: "size-5", fontSize: "text-11" }),
      getBorderRadius: () => "rounded-full",
      isAValidNumber: (value) => typeof value === "number",
    },
  });
  const image = Avatar({ name: "demo", src: "/old.png" }).props.children.props.children;
  assert.equal(image.type, "img");
  assert.match(image.props.className, /object-cover/);
  image.props.onError();
  const fallback = Avatar({ name: "demo", src: "/old.png" }).props.children.props.children;
  assert.equal(fallback.type, "div");
  assert.equal(fallback.props.children, "D");
  assert.equal(Avatar({ name: "demo", src: "/new.png" }).props.children.props.children.type, "img");
});
test("头像保存后同步已加载成员缓存，其他页面无需刷新；不创建额外成员", async () => {
  const Stub = class {};
  const { UserStore } = load("../core/store/user/index.ts", {
    "lodash-es": {
      cloneDeep: structuredClone,
      set: (obj, key, value) => {
        obj[key] = value;
      },
    },
    mobx: { makeObservable() {}, runInAction: (fn) => fn(), observable: { ref: null }, action: null, computed: null },
    "@plane/constants": { EUserPermissions: {}, API_BASE_URL: "" },
    "@/store/user/base-permissions.store": { UserPermissionStore: Stub },
    "@/services/auth.service": { AuthService: Stub },
    "@/services/user.service": {
      UserService: class {
        async updateUser(data) {
          return { id: "self", ...data };
        }
      },
    },
    "@/store/user/profile.store": { ProfileStore: Stub },
    "./settings.store": { UserSettingsStore: Stub },
  });
  const memberMap = {
    self: { id: "self", avatar_url: "/old.png", display_name: "demo" },
    other: { id: "other", avatar_url: "/other.png" },
  };
  const user = new UserStore({ memberRoot: { memberMap } });
  user.data = { id: "self", avatar_url: "/old.png" };
  await user.updateCurrentUser({ avatar_url: "/new.png" });
  assert.equal(memberMap.self.avatar_url, "/new.png");
  assert.equal(memberMap.other.avatar_url, "/other.png");
  delete memberMap.self;
  await user.updateCurrentUser({ avatar_url: "" });
  assert.equal(memberMap.self, undefined);
});

test("头像上传等待资料保存完成，保存失败保留所选文件供重试", async () => {
  const slots = [],
    notifications = [];
  let cursor = 0,
    accept,
    save,
    selected;
  const { UserImageUploadModal } = load("../core/components/core/modals/user-image-upload-modal.tsx", {
    react: {
      ...React,
      useEffect() {},
      useState: (initial) => {
        const index = cursor++;
        if (!(index in slots)) slots[index] = initial;
        return [
          slots[index],
          (value) => {
            slots[index] = value;
          },
        ];
      },
    },
    "mobx-react": { observer: (fn) => fn },
    "react-dropzone": {
      useDropzone: (options) => {
        accept = options.onDrop;
        return { getRootProps: () => ({}), getInputProps: () => ({}), fileRejections: [] };
      },
    },
    "@plane/constants": { MAX_FILE_SIZE: 5 * 1024 * 1024, ACCEPTED_AVATAR_IMAGE_MIME_TYPES_FOR_REACT_DROPZONE: {} },
    "@plane/propel/button": { Button: "button" },
    "@plane/propel/icons": { UserCirclePropertyIcon: () => null },
    "@plane/propel/toast": { TOAST_TYPE: { ERROR: "error" }, setToast: (value) => notifications.push(value) },
    "@plane/types": { EFileAssetType: { USER_AVATAR: "USER_AVATAR" } },
    "@plane/ui": { ModalCore: "dialog", EModalPosition: {}, EModalWidth: {} },
    "@plane/utils": {},
    "@/services/file.service": {
      FileService: class {
        async uploadUserAsset() {
          return { asset_url: "/new.png" };
        }
      },
    },
  });
  function render() {
    cursor = 0;
    return UserImageUploadModal({
      isOpen: true,
      value: null,
      onClose() {},
      handleRemove() {},
      onSuccess: () =>
        new Promise((resolve, reject) => {
          save = { resolve, reject };
        }),
    });
  }
  function buttons(node, found = []) {
    if (!node || typeof node !== "object") return found;
    if (Array.isArray(node)) {
      node.forEach((child) => buttons(child, found));
      return found;
    }
    if (node.type === "button") found.push(node);
    buttons(node.props?.children, found);
    return found;
  }
  render();
  selected = { name: "avatar.png" };
  accept([selected]);
  const submission = buttons(render()).at(-1).props.onClick();
  let completed = false;
  submission.then(() => {
    completed = true;
  });
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(completed, false);
  save.reject(new Error("profile unavailable"));
  await submission;
  assert.equal(slots[0], selected);
  assert.equal(slots[2], false);
  assert.equal(notifications[0].title, "头像上传失败");
  const retry = buttons(render()).at(-1).props.onClick();
  await Promise.resolve();
  await Promise.resolve();
  save.resolve();
  await retry;
  assert.equal(slots[0], null);
});
