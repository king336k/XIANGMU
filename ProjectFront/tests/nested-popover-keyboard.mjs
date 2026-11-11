import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
function AIService() {}
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
test("编辑器助手只响应自身键盘事件，外层快捷键和内层取消不串层", () => {
  const listeners = [],
    panel = { addEventListener: (...a) => listeners.push({ target: "panel", args: a }), removeEventListener() {} };
  let state = 0,
    closes = 0;
  const exports = {};
  const old = globalThis.window;
  globalThis.window = {
    addEventListener: (...a) => listeners.push({ target: "window", args: a }),
    removeEventListener() {},
  };
  try {
    new Function(
      "require",
      "exports",
      ts.transpileModule(
        readFileSync(new URL("../core/components/core/modals/gpt-assistant-popover.tsx", import.meta.url), "utf8"),
        { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }
      ).outputText
    )((id) => {
      if (id === "react")
        return {
          ...React,
          useEffect: (fn) => fn(),
          useRef: () => ({ current: null }),
          useState: (x) => [state++ === 3 ? panel : x, () => {}],
        };
      if (id === "react-hook-form")
        return {
          useForm: () => ({
            handleSubmit: () => () => {},
            control: {},
            reset() {},
            setFocus() {},
            formState: { isSubmitting: false },
          }),
          Controller: "controller",
        };
      if (id === "react-popper") return { usePopper: () => ({ styles: {}, attributes: {} }) };
      if (id === "@headlessui/react")
        return { Popover: Object.assign(() => null, { Button: "b", Panel: "panel" }), Transition: "transition" };
      if (id.includes("ai.service")) return { AIService };
      if (id.includes("rich-text")) return { RichTextEditor: "editor" };
      if (id.includes("propel/button")) return { Button: "button" };
      if (id.includes("propel/toast")) return { TOAST_TYPE: {}, setToast() {} };
      if (id === "@plane/ui") return { Input: "input" };
      return require(id);
    }, exports);
    exports.GptAssistantPopover({ isOpen: true, handleClose: () => closes++, onResponse() {}, button: "AI" });
    assert.equal(listeners.filter((x) => x.target === "window" && x.args[0] === "keydown").length, 0);
    const onEscape = listeners.filter((x) => x.target === "panel")[1].args[1];
    onEscape({ key: "Escape", defaultPrevented: true, preventDefault() {}, stopPropagation() {} });
    assert.equal(closes, 0);
    let stopped = false;
    onEscape({
      key: "Escape",
      defaultPrevented: false,
      preventDefault() {},
      stopPropagation() {
        stopped = true;
      },
    });
    assert.equal(closes, 1);
    assert.equal(stopped, true);
  } finally {
    globalThis.window = old;
  }
});
