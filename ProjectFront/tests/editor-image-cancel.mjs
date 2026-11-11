import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const path = "../../packages/editor/src/core/extensions/custom-image/components/uploader.tsx";
const code = () =>
  ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
function nodes(t) {
  if (!t || typeof t !== "object") return [];
  if (Array.isArray(t)) return t.flatMap(nodes);
  return [t, ...nodes(t.props?.children)];
}

function setup({ src = null, status = "pending", uploading = false, editable = true, otherNode = false } = {}) {
  const api = {},
    effects = [],
    fileInput = new EventTarget(),
    fileMap = new Map([["image-1", { event: "insert" }]]);
  let refIndex = 0,
    deleted = 0,
    uploads = 0;
  fileInput.click = () => {};
  const node = { attrs: { id: "image-1", src, status }, type: { name: "imageComponent" } };
  const editor = {
    isEditable: editable,
    storage: { utility: {} },
    state: { doc: { nodeAt: () => (otherNode ? { ...node, attrs: { ...node.attrs, id: "other" } } : node) } },
  };
  const props = {
    editor,
    node,
    getPos: () => 3,
    deleteNode: () => {
      deleted++;
    },
    extension: { options: {} },
    setIsUploaded() {},
    updateAttributes() {},
    loadImageFromFileSystem() {},
    maxFileSize: 1024,
  };
  new Function("require", "exports", code())((id) => {
    if (id === "react")
      return {
        ...React,
        useRef: (value) => ({ current: refIndex++ === 0 ? fileInput : value }),
        useCallback: (fn) => fn,
        useMemo: (fn) => fn(),
        useEffect: (fn) => effects.push(fn),
      };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "@plane/utils") return { cn: () => "" };
    if (id === "@/constants/config") return { ACCEPTED_IMAGE_MIME_TYPES: ["image/png"] };
    if (id === "@/constants/extension") return { CORE_EXTENSIONS: { PARAGRAPH: "paragraph" } };
    if (id === "@/hooks/use-file-upload")
      return {
        useUploader: () => ({ isUploading: uploading, uploadFile() {} }),
        useDropZone: () => ({}),
        uploadFirstFileAndInsertRemaining: async () => {
          uploads++;
        },
      };
    if (id === "../types")
      return {
        ECustomImageStatus: {
          PENDING: "pending",
          UPLOADING: "uploading",
          UPLOADED: "uploaded",
          DUPLICATING: "duplicating",
        },
      };
    if (id === "../utils") return { getImageComponentImageFileMap: () => fileMap };
    return new Proxy({}, { get: () => () => null });
  }, api);
  const tree = api.CustomImageUploader(props);
  const all = nodes(tree),
    input = all.find((n) => n.type === "input"),
    cleanup = effects.map((fn) => fn());
  return {
    tree,
    all,
    input,
    fileInput,
    fileMap,
    cleanup,
    get deleted() {
      return deleted;
    },
    get uploads() {
      return uploads;
    },
  };
}
test("取消文件选择只删除本次未上传空节点，并清理临时文件映射", () => {
  const x = setup();
  x.fileInput.dispatchEvent(new Event("cancel"));
  assert.equal(x.deleted, 1);
  assert.equal(x.fileMap.has("image-1"), false);
});
test("取消不删除已存在的图片、上传中的节点、只读内容或位置已变化的其他节点", () => {
  for (const options of [
    { src: "asset-existing" },
    { status: "uploading", uploading: true },
    { editable: false },
    { otherNode: true },
  ]) {
    const x = setup(options);
    x.fileInput.dispatchEvent(new Event("cancel"));
    assert.equal(x.deleted, 0);
  }
});
test("空文件列表按取消处理，正常文件选择仍走原上传流程", async () => {
  const empty = setup();
  await empty.input.props.onChange({ preventDefault() {}, target: { files: [] } });
  assert.equal(empty.deleted, 1);
  assert.equal(empty.uploads, 0);
  const selected = setup();
  await selected.input.props.onChange({ preventDefault() {}, target: { files: [{}] } });
  assert.equal(selected.deleted, 0);
  assert.equal(selected.uploads, 1);
});
test("空图片占位框提供中文提示和明确取消入口", () => {
  const x = setup();
  assert.ok(x.all.some((n) => n.props?.children === "添加图片"));
  const cancel = x.all.find((n) => n.type === "button" && n.props["aria-label"] === "取消添加图片");
  assert.ok(cancel);
  cancel.props.onClick({ preventDefault() {}, stopPropagation() {} });
  assert.equal(x.deleted, 1);
});
