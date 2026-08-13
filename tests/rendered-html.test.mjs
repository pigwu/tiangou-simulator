import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the finished local simulator", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html lang="zh-CN">/);
  assert.match(html, /<title>舔狗模拟器 · 把旧聊天练成新对话<\/title>/);
  assert.match(html, /本地项目管理/);
  assert.match(html, /还没有本地项目/);
  assert.match(html, /新建项目/);
  assert.match(html, /聊天记录、训练数据与模型默认只停留在你的电脑/);
  assert.match(html, /如何批量获取记录/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|Building your site/);
});

test("keeps product metadata and removes the disposable starter", async () => {
  const [page, layout, simulator, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/simulator.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(page, /舔狗模拟器 · 把旧聊天练成新对话/);
  assert.match(layout, /隐私优先的本地聊天角色训练与模拟器/);
  assert.match(simulator, /api\/projects/);
  assert.match(simulator, /确认本地训练/);
  assert.match(simulator, /不上传/);
  assert.doesNotMatch(`${page}\n${layout}\n${simulator}`, /codex-preview|_sites-preview|SkeletonPreview/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);

  await assert.rejects(access(new URL("../app/_sites-preview", import.meta.url)));
  await assert.rejects(access(new URL("../public/_sites-preview", import.meta.url)));
});
