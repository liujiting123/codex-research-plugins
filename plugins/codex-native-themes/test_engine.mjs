import test from "node:test";
import assert from "node:assert/strict";
import {pathToFileURL} from "node:url";
import {isHostTarget} from "./engine.mjs";

test("recognizes the supported main and detached host pages", () => {
  assert.equal(isHostTarget({type:"page",url:"app://-/index.html#chat"}), true);
  assert.equal(isHostTarget({type:"page",url:"app://-/detached-window.html"}), true);
  assert.equal(isHostTarget({type:"page",url:"app://-/splash.html"}), false);
  assert.equal(isHostTarget({type:"webview",url:"app://-/index.html"}), false);
});

test("file targets use the discovered application, including spaces in its path", () => {
  const app = "/Users/example/Custom Apps/Research Codex.app";
  const target = {type:"page",url:pathToFileURL(app + "/Contents/Resources/app/webview/index.html").href};
  assert.equal(isHostTarget(target, app), true);
  assert.equal(isHostTarget(target), false);
  assert.equal(isHostTarget(target, "/Applications/Other.app"), false);
  assert.equal(isHostTarget({type:"page",url:pathToFileURL(app + "/Contents/Resources/app/webview/settings.html").href}, app), false);
});

test("excludes plugin frames and browser tabs from host style injection", () => {
  const urls = [
    "https://example.com/index.html", "http://127.0.0.1:9341/index.html",
    "codex-sandbox://mcp-app-abc.web-sandbox.oaiusercontent.com/index.html",
    "devtools://devtools/bundled/inspector.html", "not-a-url",
  ];
  for (const url of urls) assert.equal(isHostTarget({type:"page",url}, "/Applications/Codex.app"), false);
});
