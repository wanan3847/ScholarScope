/* 校验 docs/design/DESIGN.md 的 token 与形状锁定是否真的到达服务端页面。
   只读计算样式与几何，不写任何数据。需要先启动服务：
   cd src && python3 -m uvicorn web.app:app --host 127.0.0.1 --port 8765
   运行：node src/tests/ad_hoc/ui_tokens.js */
const assert = require("node:assert/strict");
const path = require("node:path");
let playwright;
try {
  playwright = require("playwright");
} catch {
  playwright = require(
    path.resolve(__dirname, "../../../.cache/ui-check/node_modules/playwright"),
  );
}
const base = process.env.SCHOLARSCOPE_URL || "http://127.0.0.1:8765";

const LADDER = [11, 12, 13, 14, 15, 20, 28];
const checks = [];
const seen = (name, ok, detail) => checks.push({ name, ok, detail });

(async () => {
  const browser = await playwright.chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(base + "/app", { waitUntil: "networkidle" });

  // 1. 形状锁定：页面内任何元素都不得有圆角、阴影、渐变、玻璃
  const shape = await page.evaluate(() => {
    const bad = { radius: [], shadow: [], glass: [] };
    for (const el of document.querySelectorAll("*")) {
      const s = getComputedStyle(el);
      const r = s.borderTopLeftRadius;
      if (r && r !== "0px") bad.radius.push(el.className + " " + r);
      if (s.boxShadow !== "none") bad.shadow.push(el.className + " " + s.boxShadow);
      if (s.backdropFilter && s.backdropFilter !== "none")
        bad.glass.push(el.className + " " + s.backdropFilter);
      if (/gradient/.test(s.backgroundImage))
        bad.glass.push(el.className + " background-image");
    }
    return bad;
  });
  seen("圆角全为 0", shape.radius.length === 0, shape.radius.slice(0, 5).join(" | "));
  seen("无阴影", shape.shadow.length === 0, shape.shadow.slice(0, 5).join(" | "));
  seen("无玻璃与渐变", shape.glass.length === 0, shape.glass.slice(0, 5).join(" | "));

  // 2. 底色白名单：不透明底色只能是 paper、hover 或主按钮的 ink，出现第三种即表示又加了一个表面色
  const grounds = await page.evaluate(() => {
    const kinds = new Map();
    for (const el of document.querySelectorAll("*")) {
      const bg = getComputedStyle(el).backgroundColor;
      if (!bg || bg === "rgba(0, 0, 0, 0)") continue;
      kinds.set(bg, (kinds.get(bg) || 0) + 1);
    }
    return [...kinds.entries()].sort((a, b) => b[1] - a[1]);
  });
  const paper = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--paper").trim(),
  );
  const toRgb = (hex) => {
    const h = hex.replace("#", "");
    const n = parseInt(h.length === 3 ? h.replace(/./g, (c) => c + c) : h, 16);
    return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
  };
  const allowed = new Set([toRgb(paper), "rgb(235, 235, 235)", "rgb(18, 18, 18)"]);
  const opaque = grounds.filter(([c]) => !c.startsWith("rgba"));
  const extra = opaque.filter(([c]) => !allowed.has(c));
  seen(
    "不透明底色只有 paper / hover / ink",
    extra.length === 0,
    extra.map(([c, n]) => `${c}x${n}`).join(", "),
  );

  // 3. 排版阶梯：可见文字字号必须落在阶梯内
  const sizes = await page.evaluate(() => {
    const found = new Set();
    for (const el of document.querySelectorAll("*")) {
      if (!el.textContent || !el.textContent.trim()) continue;
      if (el.children.length) continue;
      const s = getComputedStyle(el);
      if (s.display === "none" || s.visibility === "hidden") continue;
      found.add(Math.round(parseFloat(s.fontSize)));
    }
    return [...found].sort((a, b) => a - b);
  });
  const off = sizes.filter((s) => !LADDER.includes(s));
  seen("字号落在阶梯内", off.length === 0, `出现 ${off.join(",")}`);

  // 4. 字重只有三档
  const weights = await page.evaluate(() => {
    const found = new Set();
    for (const el of document.querySelectorAll("*")) {
      if (!el.textContent || !el.textContent.trim()) continue;
      if (el.children.length) continue;
      found.add(getComputedStyle(el).fontWeight);
    }
    return [...found].sort();
  });
  seen(
    "字重只有 400/500/700",
    weights.every((w) => ["400", "500", "700"].includes(w)),
    weights.join(","),
  );

  // 5. 深浅色两套 token 都能取到且互不相同
  const themes = {};
  for (const theme of ["light", "dark"]) {
    await page.evaluate((t) => {
      document.documentElement.dataset.theme = t;
      localStorage.setItem("scholarscope_theme_v2", t);
    }, theme);
    themes[theme] = await page.evaluate(() => {
      const s = getComputedStyle(document.documentElement);
      const read = (k) => s.getPropertyValue(k).trim();
      return {
        paper: read("--paper"),
        rule: read("--rule"),
        signal: read("--signal"),
        ink: read("--ink"),
        scrim: read("--scrim"),
      };
    });
  }
  const same = ["paper", "rule", "signal", "ink", "scrim"].filter(
    (k) => themes.light[k] === themes.dark[k],
  );
  seen("深浅色 token 两套齐备", same.length === 0, `相同项 ${same.join(",")}`);
  seen("深色无纯黑", !/^#000000$|^rgb\(0 0 0\)$/.test(themes.dark.paper), themes.dark.paper);
  seen("浅色无纯白", !/^#ffffff$/i.test(themes.light.paper), themes.light.paper);

  // 6. 五个宽度下无横向溢出
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "light";
  });
  for (const width of [1920, 1280, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(120);
    const overflow = await page.evaluate(() => {
      const de = document.documentElement;
      const over = [];
      for (const el of document.querySelectorAll("body *")) {
        const r = el.getBoundingClientRect();
        if (r.width && r.right > de.clientWidth + 1) {
          over.push(el.className + " right=" + Math.round(r.right));
        }
      }
      return { scrollX: de.scrollWidth - de.clientWidth, over: over.slice(0, 3) };
    });
    seen(
      `${width}px 无横向溢出`,
      overflow.scrollX <= 0 && overflow.over.length === 0,
      `scrollX=${overflow.scrollX} ${overflow.over.join(" | ")}`,
    );
  }

  seen("无 JS 报错", errors.length === 0, errors.join(" | "));

  await browser.close();

  const failed = checks.filter((c) => !c.ok);
  for (const c of checks) {
    console.log(`${c.ok ? "PASS" : "FAIL"}  ${c.name}${c.ok ? "" : "  <- " + c.detail}`);
  }
  console.log(`\n${failed.length ? "FAILED" : "PASS"}  ${checks.length - failed.length}/${checks.length}`);
  assert.equal(failed.length, 0, "token 校验未通过");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
