/* Real account UI and model settings against an owned isolated server.
   No API interception, cloud generation, private Zotero keys or production writes. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { chromium } = require(path.resolve(__dirname, "../../.cache/ui-check/node_modules/playwright"));
const repo = path.resolve(__dirname, "../..");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "scholarscope-account-ui-"));
const base = "http://127.0.0.1:18770";
const password = "ControlledBrowserJourneyPassword123";
const log = fs.openSync(path.join(tmp, "server.log"), "w");
const server = spawn(path.join(repo, ".venv/bin/python"), ["-m", "uvicorn", "web.app:app", "--host", "127.0.0.1", "--port", "18770"], {
  cwd: path.join(repo, "src"),
  env: { ...process.env, SCHOLARSCOPE_DATA_DIR: tmp, SCHOLARSCOPE_WORKSPACE_DIR: tmp,
    SCHOLARSCOPE_DATABASE_URL: "sqlite:///" + path.join(tmp, "workspace.sqlite3"),
    SCHOLARSCOPE_DISABLE_AI: "1", SCHOLARSCOPE_DISABLE_EMBEDDINGS: "1",
    SAKURA_ADMIN_USER: "uat-admin", SAKURA_ADMIN_PASSWORD: password },
  stdio: ["ignore", log, log],
});
let browser;
(async () => {
  let ready = false;
  for (let i = 0; i < 80; i++) {
    if (server.exitCode !== null) break;
    try { if ((await fetch(base + "/api/health")).ok) { ready = true; break; } } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(ready, "Isolated account UI server did not start");
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  const errors = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto(base + "/app", { waitUntil: "networkidle" });
  await page.locator("#login-text").click();
  await page.getByRole("button", { name: "注册账号", exact: true }).click();
  await page.getByLabel("用户名", { exact: true }).fill("uat-browser");
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.locator("#login-submit").click();
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  assert.equal(await page.locator("#login-text").innerText(), "uat-browser");
  await page.reload({ waitUntil: "networkidle" });
  assert.equal(await page.locator("#login-text").innerText(), "uat-browser");
  await page.getByLabel("模型设置", { exact: true }).click();
  await page.getByLabel("提供商", { exact: true }).selectOption("deepseek");
  await page.getByLabel("常用模型", { exact: true }).selectOption("deepseek-v4-pro");
  assert.equal(await page.getByLabel("模型 ID（可直接填写，留空使用默认）", { exact: true }).inputValue(), "deepseek-v4-pro");
  await page.getByLabel("API Key（已保存可留空保留；Ollama 无需填写）", { exact: true }).fill("ControlledBrowserConfigOnlyKey123456");
  await page.getByRole("button", { name: "添加模型", exact: true }).click();
  await page.getByText("仅管理员可配置大模型", { exact: true }).waitFor();
  await page.getByLabel("关闭面板").click();
  await page.locator("#login-text").click();
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await page.locator("#login-text").click();
  await page.getByLabel("用户名", { exact: true }).fill("uat-admin");
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.locator("#login-submit").click();
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  await page.getByLabel("模型设置", { exact: true }).click();
  await page.getByLabel("提供商", { exact: true }).selectOption("deepseek");
  await page.getByLabel("常用模型", { exact: true }).selectOption("deepseek-flash");
  await page.getByLabel("API Key（已保存可留空保留；Ollama 无需填写）", { exact: true }).fill("ControlledBrowserConfigOnlyKey123456");
  await page.getByLabel("优先级（数字越大越优先）", { exact: true }).fill("40");
  await page.getByRole("button", { name: "添加模型", exact: true }).click();
  await page.locator(".model-row").filter({ hasText: "deepseek-flash" }).waitFor();
  await page.getByLabel("常用模型", { exact: true }).selectOption("__custom__");
  await page.getByLabel("模型 ID（可直接填写，留空使用默认）", { exact: true }).fill("custom-config-only");
  await page.getByLabel("优先级（数字越大越优先）", { exact: true }).fill("41");
  await page.getByRole("button", { name: "添加模型", exact: true }).click();
  await page.locator(".model-row").filter({ hasText: "custom-config-only" }).waitFor();
  const saved = JSON.parse(fs.readFileSync(path.join(tmp, "llm_config.json"), "utf8"));
  assert.equal(saved[0].priority, 41);
  assert.equal(saved[0].api_key, "ControlledBrowserConfigOnlyKey123456");
  await page.getByLabel("本次检索使用的模型", { exact: true }).selectOption("deepseek");
  await page.getByLabel("关闭面板").click();
  await page.reload({ waitUntil: "networkidle" });
  await page.getByLabel("模型设置", { exact: true }).click();
  assert.equal(await page.getByLabel("本次检索使用的模型", { exact: true }).inputValue(), "deepseek");
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Mobile settings overflow");
  const out = path.join(repo, ".cache/ui-check/screenshots"); fs.mkdirSync(out, { recursive: true });
  await page.screenshot({ path: path.join(out, "account-model-settings-mobile.png"), fullPage: true });
  await page.getByLabel("删除模型 deepseek", { exact: true }).click();
  await page.locator(".model-row").waitFor({ state: "hidden" });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ status: "PASS", checks: ["actual UI registration/login/logout/refresh", "ordinary account denied model writes", "common and custom model selection", "saved key retained", "priority persisted", "selected model refresh", "mobile settings", "UI unregister"] }));
})().catch(e => { console.error(e.message); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  server.kill(); fs.closeSync(log);
});
