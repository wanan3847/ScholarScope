/* Production landing/workspace navigation and viewport regression; no real data writes. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(
  path.resolve(__dirname, "../../.cache/ui-check/node_modules/playwright"),
);
const base = process.env.SCHOLARSCOPE_URL || "http://127.0.0.1:8765";
const out = path.resolve(__dirname, "../../.cache/ui-check/screenshots");
const viewports = [
  [360, 800],
  [390, 844],
  [430, 932],
  [600, 960],
  [820, 1180],
  [1024, 768],
  [1366, 768],
  [1440, 900],
  [1920, 1080],
];
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  const errors = [],
    external = [],
    missing = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (!request.url().startsWith(base) && /^https?:/.test(request.url()))
      external.push(request.url());
  });
  page.on("response", (response) => {
    if (response.status() >= 400) missing.push(response.url());
  });
  let searched = "";
  await page.route("**/api/**", (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/search") {
      searched = route.request().postDataJSON().query;
      return route.fulfill({
        json: {
          papers: [
            {
              title: "Controlled fixture: retrieval methods survey",
              doi: "10.1000/landing-test",
              abstract: "This survey reviews retrieval methods.",
              year: 2023,
              authors: ["Test author"],
              recommendation_reason: "标题和摘要讨论检索方法综述。",
              evidence: "reviews retrieval methods",
              source: "arxiv",
            },
          ],
          stats: {
            ranking_mode: "practical_agent_selection",
            backends_used: ["arxiv"],
          },
        },
      });
    }
    return route.fulfill({
      json: {
        favorites: [],
        papers: [],
        folders: [],
        models: [],
        folder_id: "",
        logged_in: false,
      },
    });
  });
  for (const [width, height] of viewports) {
    await page.setViewportSize({ width, height });
    for (const [url, name] of [
      ["/", "landing"],
      ["/app", "atelier-workspace"],
    ]) {
      await page.goto(base + url, { waitUntil: "networkidle" });
      await page.evaluate(() => document.fonts.ready);
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        `${name} overflow at ${width}`,
      );
      assert.equal(
        await page.evaluate(
          () => getComputedStyle(document.body).backgroundColor,
        ),
        "rgb(239, 231, 210)",
      );
      assert(
        await page.evaluate(async () => {
          await document.fonts.load('500 16px "Inter Tight"');
          return document.fonts.check('500 16px "Inter Tight"');
        }),
      );
      await page.screenshot({ path: path.join(out, `${name}-${width}.png`) });
    }
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(base + "/", { waitUntil: "networkidle" });
  await page.getByLabel("展开导航").click();
  assert.equal(
    await page.getByLabel("收起导航").getAttribute("aria-expanded"),
    "true",
  );
  await page
    .getByRole("link", { name: "使用方法", exact: true })
    .first()
    .click();
  assert.equal(
    await page.getByLabel("展开导航").getAttribute("aria-expanded"),
    "false",
  );
  await page.getByRole("button", { name: "整理" }).click();
  assert.equal(await page.locator(".path-card:visible").count(), 1);
  await page.locator(".path-card:visible a").click();
  await page
    .getByRole("heading", { name: "我的文献库", exact: true })
    .waitFor();
  await page.goto(base + "/");
  await page.getByLabel("导入已有研究资料").click();
  await page.getByRole("dialog").waitFor();
  assert.match(await page.getByRole("dialog").innerText(), /导入文献/);
  await page.getByLabel("关闭面板").click();
  await page.goto(base + "/app#login");
  await page.getByRole("textbox", { name: "用户名", exact: true }).waitFor();
  await page.getByLabel("关闭面板").click();
  await page.goto(base + "/");
  await page.getByLabel("检索领域综述").click();
  await page.locator(".paper-card").waitFor();
  assert.equal(searched, "retrieval augmented generation survey");
  await page.locator(".paper-select").click();
  await page.getByRole("button", { name: "返回列表", exact: true }).waitFor();
  assert.match(
    await page.locator(".paper-reader").innerText(),
    /reviews retrieval methods/,
  );
  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
  assert.deepEqual(missing, []);
  console.log(
    JSON.stringify(
      {
        status: "PASS",
        viewports: viewports.map(([w]) => w),
        checks: [
          "landing fidelity tokens",
          "local fonts/assets",
          "no overflow",
          "mobile navigation",
          "research path filter",
          "library/import/login entries",
          "prefilled live search",
          "mobile reading",
          "no external resources",
          "no JS errors",
        ],
        screenshots: out,
      },
      null,
      2,
    ),
  );
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
