/* Verify the new React UI against controlled API responses. No writes to the real library. */
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
    title: "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
    arxiv_id: "2005.11401",
    doi: "10.5555/3495724.3496517",
    year: 2020,
    venue: "NeurIPS",
    authors: ["Patrick Lewis", "Ethan Perez", "Aleksandra Piktus"],
    abstract:
      "Retrieval-augmented generation combines retrieval with text generation for knowledge-intensive NLP tasks. This work introduces a model that combines a pretrained sequence-to-sequence model with a dense vector index of Wikipedia, accessed with a pretrained neural retriever.",
    url: "https://arxiv.org/abs/2005.11401",
    source: "arxiv, openalex",
    recommendation_reason: "研究检索与生成相结合的方法，贴合知识密集型任务。",
    evidence: "combines retrieval with text generation",
    evidence_level: "abstract",
  },
  {
    title: "Retrieval-Augmented Generation for Large Language Models: A Survey",
    doi: "10.48550/arxiv.2312.10997",
    year: 2023,
    venue: "arXiv",
    authors: ["Yunfan Gao"],
    abstract:
      "A survey of retrieval-augmented generation for large language models. This paper reviews the key concepts, research directions and applications of retrieval-augmented generation.",
    url: "https://arxiv.org/abs/2312.10997",
    source: "arxiv",
    recommendation_reason: "综述检索增强生成方法，适合梳理研究方向。",
    evidence: "retrieval-augmented generation",
    evidence_level: "abstract",
  },
];
const fixture = {
  papers,
  stats: {
    elapsed_seconds: 3.2,
    backends_used: ["arxiv", "openalex"],
    ranking_mode: "practical_agent_selection",
  },
  relationships: [],
  intent: { keyword_query: "retrieval augmented generation survey" },
};
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await playwright.chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let library = [],
    folders = [],
    read = [],
    searchResponse = fixture,
    lastImport;
  await page.route("**/api/search", (r) => r.fulfill({ json: searchResponse }));
  await page.route("**/api/favorites**", async (r) => {
    const req = r.request(),
      url = new URL(req.url()),
      id = decodeURIComponent(url.pathname.replace("/api/favorites/", ""));
    if (req.method() === "GET")
      return r.fulfill({ json: { favorites: library, total: library.length } });
    if (url.pathname.endsWith("/import")) {
      lastImport = req.postDataJSON();
      library.push(...lastImport.items.map((p) => ({ ...p, paper_id: p.id })));
      return r.fulfill({
        json: { status: "ok", imported: lastImport.items.length },
      });
    }
    if (req.method() === "POST") {
      library.push({ ...req.postDataJSON().paper_meta, paper_id: id });
      return r.fulfill({ json: { status: "ok" } });
    }
    library = library.filter((p) => p.paper_id !== id);
    return r.fulfill({ json: { status: "ok" } });
  });
  await page.route("**/api/read_papers**", (r) => {
    const req = r.request();
    if (req.method() === "GET")
      return r.fulfill({
        json: { papers: read.map((paper_id) => ({ paper_id })) },
      });
    const id = decodeURIComponent(
      new URL(req.url()).pathname.replace("/api/read_papers/", ""),
    );
    read =
      req.method() === "POST" ? [...read, id] : read.filter((x) => x !== id);
    return r.fulfill({ json: { status: "ok" } });
  });
  await page.route("**/api/folders**", (r) => {
    const req = r.request(),
      url = new URL(req.url());
    if (url.pathname.endsWith("/default"))
      return r.fulfill({ json: { status: "ok", folder_id: "" } });
    if (req.method() === "GET") return r.fulfill({ json: { folders } });
    if (req.method() === "POST" && url.pathname === "/api/folders")
      folders.push({ id: "test-folder", name: req.postDataJSON().name });
    return r.fulfill({ json: { status: "ok" } });
  });
  await page.addInitScript(() => {
    localStorage.setItem("scholarscope_theme", "dark");
  });
  await page.goto(base + "/", { waitUntil: "networkidle" });
  assert.match(await page.locator("h1").innerText(), /把研究问题/);
  assert.equal(
    await page.locator(".hero .primary").getAttribute("href"),
    "/app",
  );
  assert.equal(await page.locator(".workbench").count(), 0);
  await page.getByRole("button", { name: "深入" }).click();
  assert.equal(await page.locator(".path-card:visible").count(), 2);
  await page.getByRole("button", { name: "全部" }).click();
  await page.getByLabel("下一研究场景").click();
  assert.equal(
    await page.locator("#scenario-open").getAttribute("href"),
    "/app#favorites",
  );
  await page.getByLabel("上一研究场景").click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: path.join(out, "homepage-desktop.png"),
    fullPage: true,
  });
  await page.goto(base + "/app", { waitUntil: "networkidle" });
  assert.equal(await page.locator("html").getAttribute("data-theme"), "light");
  assert.match(await page.locator("h1").innerText(), /文献检索/);
  assert.equal(await page.locator(".suggestion").count(), 2);
  await page.screenshot({
    path: path.join(out, "workspace-desktop.png"),
    fullPage: true,
  });
  await page.click("#settings-btn");
  await page.getByRole("dialog").waitFor();
  await page.getByText("配置检索模型", { exact: true }).click();
  assert.match(await page.getByRole("dialog").innerText(), /检索模型/);
  await page.getByLabel("关闭面板").click();
  await page.click("#docs-btn");
  await page.getByRole("dialog").waitFor();
  await page.locator("#docs-body h3").first().waitFor();
  assert.match(await page.locator("#docs-body").innerText(), /检索文献/);
  await page.getByLabel("关闭面板").click();
  await page.click("#login-btn");
  await page.getByRole("dialog").waitFor();
  await page.getByRole("textbox", { name: "用户名", exact: true }).waitFor();
  await page.getByLabel("关闭面板").click();
  await page.fill("#query-input", "retrieval augmented generation survey");
  await page.fill("#year-from", "2020");
  await page.fill("#year-to", "2025");
  const requestPromise = page.waitForRequest((r) =>
    r.url().endsWith("/api/search"),
  );
  await page.click("#search-btn");
  const request = await requestPromise;
  assert.equal(request.postDataJSON().year_from, 2020);
  assert.equal(request.postDataJSON().year_to, 2025);
  await page.locator(".paper-card").first().waitFor();
  assert.equal(await page.locator(".paper-card").count(), 2);
  assert.match(await page.locator(".paper-reader").innerText(), /与查询的关联/);
  assert.equal(await page.getByText(/相关度 \d/).count(), 0);
  await page.screenshot({
    path: path.join(out, "results-desktop.png"),
    fullPage: true,
  });
  await page.locator(".paper-select").nth(1).click();
  await page
    .locator(".paper-reader h2")
    .filter({ hasText: "A Survey" })
    .waitFor();
  await page
    .locator(".paper-reader")
    .getByRole("button", { name: "收藏", exact: true })
    .click();
  await page
    .locator(".paper-reader")
    .getByRole("button", { name: "已收藏", exact: true })
    .waitFor();
  assert.equal(library[0].paper_id, "10.48550/arxiv.2312.10997");
  await page
    .locator(".paper-reader")
    .getByRole("button", { name: "标记已阅", exact: true })
    .click();
  await page
    .locator(".paper-reader")
    .getByRole("button", { name: "已阅", exact: true })
    .waitFor();
  assert(read.includes("10.48550/arxiv.2312.10997"));
  await page.setViewportSize({ width: 390, height: 844 });
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: path.join(out, "reader-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "返回列表", exact: true }).click();
  await page.screenshot({
    path: path.join(out, "results-mobile.png"),
    fullPage: true,
  });
  await page.click("#settings-btn");
  await page.getByRole("dialog").waitFor();
  await page.getByText("配置检索模型", { exact: true }).click();
  await page.getByLabel("关闭面板").click();
  await page.click("#fav-btn");
  await page.locator("h1").filter({ hasText: "我的文献库" }).waitFor();
  assert.equal(await page.locator(".paper-card").count(), 1);
  await page.getByRole("button", { name: "导入", exact: true }).click();
  await page.getByRole("dialog").waitFor();
  await page.locator("input[type=file]").setInputFiles({
    name: "references.bib",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "@article{sample2026,title={A practical literature import},author={Researcher, Test},year={2026},doi={10.1000/import-test}}",
    ),
  });
  await page.getByRole("button", { name: "加入文献库", exact: true }).waitFor();
  await page.getByRole("button", { name: "加入文献库", exact: true }).click();
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  assert.equal(lastImport.items.length, 1);
  assert.equal(lastImport.items[0].title, "A practical literature import");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出", exact: true }).click();
  assert((await downloadPromise).suggestedFilename().endsWith(".bib"));
  await page.click("#search-nav");
  searchResponse = { papers: [], stats: { ranking_mode: "no_results" } };
  await page.fill("#query-input", "unmatched request");
  await page.click("#search-btn");
  await page.getByText("暂未找到可推荐的文献", { exact: true }).waitFor();
  await page.goto(base + "/app", { waitUntil: "networkidle" });
  await page.screenshot({
    path: path.join(out, "workspace-mobile.png"),
    fullPage: true,
  });
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  assert.equal(await page.locator("html").getAttribute("data-theme"), "light");
  await page.screenshot({
    path: path.join(out, "workspace-mobile-light.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: path.join(out, "workspace-desktop-light.png"),
    fullPage: true,
  });
  await page.getByLabel("切换深色").click();
  await page.screenshot({
    path: path.join(out, "workspace-desktop-dark.png"),
    fullPage: true,
  });
  await page.getByLabel("切换浅色").click();
  assert.equal(await page.locator("html").getAttribute("data-theme"), "light");
  assert.equal(await page.locator(".search-art").count(), 0);
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify(
      {
        status: "PASS",
        checks: [
          "new React frontend",
          "search/year filters",
          "split reading pane",
          "grounded reading reasons",
          "DOI favorite/read",
          "library",
          "BibTeX import",
          "BibTeX export",
          "settings/models",
          "docs",
          "login dialog",
          "desktop/mobile",
          "light/dark",
          "empty results",
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
