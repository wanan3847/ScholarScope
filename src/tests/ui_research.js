/* Controlled UI regression for research interactions. All account/library APIs are intercepted. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
let playwright;
try {
  playwright = require("playwright");
} catch {
  playwright = require(
    path.resolve(__dirname, "../../.cache/ui-check/node_modules/playwright"),
  );
}
const base = process.env.SCHOLARSCOPE_URL || "http://127.0.0.1:8765";
const out = path.resolve(__dirname, "../../.cache/ui-check/screenshots");
const papers = [
  {
    doi: "10.1000/test-retrieval",
    title: "Test fixture: retrieval with pretrained neural models",
    authors: ["Researcher A"],
    year: 2020,
    venue: "Test venue",
    source: "arxiv, openalex",
    abstract:
      "We introduce a pretrained neural retriever for knowledge-intensive tasks. The model retrieves relevant documents. Results demonstrate improved retrieval on the test benchmark.",
    citation_count: 120,
    code_url: "https://github.com/example/test-fixture",
    dataset: "Test benchmark",
    recommendation_reason: "方法研究，提供检索模型。",
    evidence: "pretrained neural retriever",
  },
  {
    doi: "10.1000/test-survey",
    title: "Test fixture: retrieval methods survey",
    authors: ["Researcher B"],
    year: 2023,
    venue: "Test venue",
    source: "arxiv",
    abstract:
      "This survey reviews retrieval methods and their limitations. It compares neural models for retrieval.",
    citation_count: 15,
  },
  {
    doi: "10.1000/test-graph",
    title: "Test fixture: graph neural pretraining",
    authors: ["Researcher C"],
    year: 2025,
    venue: "Test venue",
    source: "semantic_scholar",
    abstract: "We propose graph neural pretraining for molecular prediction.",
  },
];
const relationships = [
  { src: papers[0].doi, dst: papers[1].doi, relation: "similar", weight: 0.6 },
  { src: papers[1].doi, dst: papers[0].doi, relation: "cite", weight: 1 },
];
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await playwright.chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
  });
  const errors = [];
  context.on("page", (p) => p.on("pageerror", (e) => errors.push(e.message)));
  let empty = false,
    failing = false,
    hold = false;
  await context.route("**/api/**", async (route) => {
    const u = new URL(route.request().url());
    if (u.pathname === "/api/search") {
      if (failing)
        return route.fulfill({
          status: 503,
          json: { detail: "Controlled source failure" },
        });
      if (hold) {
        await new Promise((resolve) => setTimeout(resolve, 300));
      }
      return route.fulfill({
        json: {
          papers: empty ? [] : papers,
          relationships: empty ? [] : relationships,
          stats: {
            elapsed_seconds: 1.2,
            backends_used: ["arxiv", "openalex"],
            ranking_mode: "practical_agent_selection",
          },
        },
      });
    }
    const bodies = {
      "/api/favorites": { favorites: [] },
      "/api/read_papers": { papers: [] },
      "/api/folders": { folders: [] },
      "/api/folders/default": { folder_id: "" },
      "/api/llm/models": { models: [] },
      "/api/auth/me": { logged_in: true, username: "Researcher" },
    };
    return route.fulfill({ json: bodies[u.pathname] || { status: "ok" } });
  });
  const page = await context.newPage();
  await page.goto(base + "/app", { waitUntil: "networkidle" });
  await page.keyboard.press("Control+k");
  assert.equal(
    await page
      .locator("#query-input")
      .evaluate((e) => e === document.activeElement),
    true,
  );
  await page.fill("#query-input", "research methods");
  await page.fill("#year-from", "2025");
  await page.fill("#year-to", "2020");
  await page.click("#search-btn");
  await page.getByRole("alert").filter({ hasText: "有效的年份范围" }).waitFor();
  await page.fill("#year-from", "2020");
  await page.fill("#year-to", "2025");
  await page.getByRole("button", { name: "保存检索", exact: true }).click();
  await page.locator(".saved-query").waitFor();
  await page.fill("#query-input", "different query");
  await page.locator(".saved-query>button").first().click();
  assert.equal(await page.inputValue("#query-input"), "research methods");
  assert.equal(await page.inputValue("#year-from"), "2020");
  await page.locator("#query-input").press("Enter");
  await page.locator(".paper-card").nth(2).waitFor();
  await page.locator("#result-list").focus();
  await page.keyboard.press("ArrowDown");
  assert.match(await page.locator(".paper-reader h2").innerText(), /survey/);
  await page.keyboard.press("ArrowUp");
  assert.match(
    await page.locator(".paper-reader h2").innerText(),
    /pretrained/,
  );
  await page.locator(".paper-select").first().focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  assert.match(await page.locator(".paper-reader h2").innerText(), /survey/);
  await page.getByRole("button", { name: "方法对比视图" }).click();
  assert.equal(await page.locator(".method-comparison tbody tr").count(), 3);
  await page.screenshot({ path: path.join(out, "method-comparison.png") });
  await page.getByRole("button", { name: "文献列表视图" }).click();
  await page.getByRole("button", { name: "高级筛选", exact: true }).click();
  await page.selectOption('[aria-label="数据库"]', "semantic_scholar");
  assert.equal(await page.locator(".paper-card").count(), 1);
  assert.match(await page.locator(".paper-title").innerText(), /graph neural/);
  await page.selectOption('[aria-label="数据库"]', "");
  await page.selectOption('[aria-label="最低引用次数"]', "100");
  assert.equal(await page.locator(".paper-card").count(), 1);
  await page.selectOption('[aria-label="最低引用次数"]', "");
  await page.getByLabel("有代码链接").check();
  assert.equal(await page.locator(".paper-card").count(), 1);
  await page.selectOption('[aria-label="方法类别"]', "Survey");
  await page.getByText("没有符合筛选条件的文献", { exact: true }).waitFor();
  await page.getByRole("button", { name: /清除 2 项/ }).click();
  assert.equal(await page.locator(".paper-card").count(), 3);
  await page.getByRole("tab", { name: "知识上下文" }).click();
  assert.equal(await page.locator(".relation-graph .graph-node").count(), 2);
  assert.equal(await page.locator(".concept-map").count(), 1);
  await page.getByRole("button", { name: "引文", exact: true }).click();
  assert.equal(
    await page.locator(".relation-graph line[marker-end]").count(),
    1,
  );
  await page.screenshot({ path: path.join(out, "knowledge-context.png") });
  await page.getByRole("button", { name: "关联", exact: true }).click();
  assert.equal(
    await page.locator(".relation-graph line[marker-end]").count(),
    0,
  );
  await page.locator(".graph-node").nth(1).focus();
  await page.keyboard.press("Enter");
  await page.getByRole("tab", { name: "文献详情" }).click();
  assert.match(await page.locator(".paper-reader h2").innerText(), /survey/);
  await page
    .getByLabel("阅读笔记", { exact: true })
    .fill("比较检索方法的适用条件");
  await page.getByLabel("阅读进度", { exact: true }).selectOption("reading");
  await page.getByLabel("笔记标签", { exact: true }).fill("核心阅读, 方法比较");
  assert.equal(await page.locator(".tag-nav .folder-button").count(), 2);
  await page.evaluate(() => {
    const el = document.querySelector(".paper-abstract");
    const range = document.createRange();
    range.selectNodeContents(el);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  });
  await page.getByRole("button", { name: "保存选中摘要", exact: true }).click();
  assert.equal(await page.locator(".saved-excerpt").count(), 1);
  const popupPromise = page.waitForEvent("popup");
  await page.getByRole("link", { name: "独立阅读窗口" }).click();
  const popup = await popupPromise;
  await popup.waitForLoadState("networkidle");
  assert.equal(
    await popup
      .locator(".paper-title")
      .isVisible()
      .catch(() => false),
    false,
  );
  assert.match(await popup.locator(".paper-reader h2").innerText(), /survey/);
  assert.equal(
    await popup.getByLabel("阅读笔记", { exact: true }).inputValue(),
    "比较检索方法的适用条件",
  );
  await popup.screenshot({ path: path.join(out, "standalone-reader.png") });
  await popup.close();
  await page.locator(".tag-nav .folder-button").first().click();
  assert.equal(await page.locator(".paper-card").count(), 1);
  await page.fill("#query-input", "research methods");
  await page.click("#search-btn");
  await page.locator(".paper-card").nth(2).waitFor();
  assert.equal(await page.locator(".paper-card").count(), 3);
  assert.equal(await page.getByLabel("清除标签筛选").count(), 0);
  await page.getByRole("button", { name: "展开阅读器" }).click();
  assert.equal(await page.locator(".paper-list").isVisible(), false);
  await page.getByRole("button", { name: "收起阅读器" }).click();
  assert.equal(await page.locator(".paper-list").isVisible(), true);
  await page.reload({ waitUntil: "networkidle" });
  assert.equal(await page.locator(".saved-query").count(), 1);
  await page.click("#history-btn");
  await page.locator(".history-open").first().click();
  await page.locator(".paper-select").nth(1).click();
  assert.equal(
    await page.getByLabel("阅读笔记", { exact: true }).inputValue(),
    "比较检索方法的适用条件",
  );
  assert.equal(
    await page.getByLabel("阅读进度", { exact: true }).inputValue(),
    "reading",
  );
  assert.equal(await page.locator(".saved-excerpt").count(), 1);
  await page.getByLabel("切换深色").click();
  await page.screenshot({ path: path.join(out, "research-results-dark.png") });
  await page.getByRole("tab", { name: "知识上下文" }).click();
  await page.screenshot({ path: path.join(out, "knowledge-context-dark.png") });
  await page.getByRole("tab", { name: "文献详情" }).click();
  await page.getByLabel("切换浅色").click();
  for (const width of [1920, 1280, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      `overflow at ${width}`,
    );
  }
  await page.screenshot({
    path: path.join(out, "notes-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "返回列表", exact: true }).click();
  failing = true;
  await page.fill("#query-input", "controlled failure");
  await page.click("#search-btn");
  await page
    .getByRole("alert")
    .filter({ hasText: "Controlled source failure" })
    .waitFor();
  failing = false;
  hold = true;
  await page.click("#search-btn");
  await page.getByRole("button", { name: "取消检索", exact: true }).click();
  await page.getByRole("button", { name: "检索文献", exact: true }).waitFor();
  hold = false;
  empty = true;
  await page.click("#search-btn");
  await page.getByText("暂未找到可推荐的文献", { exact: true }).waitFor();
  await page.evaluate(() => {
    localStorage.setItem("sakura_token", "controlled-test-token");
    localStorage.setItem("sakura_user", "Researcher");
  });
  await page.goto(base + "/app", { waitUntil: "networkidle" });
  assert.equal(await page.locator(".saved-query").count(), 0);
  assert.equal(await page.locator(".tag-nav .folder-button").count(), 0);
  empty = false;
  await page.fill("#query-input", "research methods");
  await page.click("#search-btn");
  await page.locator(".paper-select").nth(1).click();
  assert.equal(
    await page.getByLabel("阅读笔记", { exact: true }).inputValue(),
    "",
  );
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify(
      {
        status: "PASS",
        checks: [
          "quick search",
          "year validation",
          "saved search restore",
          "keyboard navigation",
          "source/method/citation/code filters",
          "method comparison",
          "real relationship graphs",
          "concept map",
          "reading notes/excerpts/progress",
          "tag filtering",
          "independent reader",
          "reload persistence",
          "account separation",
          "large screen/tablet/mobile",
          "dark mode",
          "error/empty/cancellation",
          "no JS errors",
        ],
        screenshots: out,
      },
      null,
      2,
    ),
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
