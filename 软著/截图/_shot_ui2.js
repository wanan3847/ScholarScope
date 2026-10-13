// 补充截图：文献星图、收藏夹文件夹管理、导入导出、运行统计
const { chromium } = require('/Users/yangyazhou/.hermes/hermes-agent/node_modules/playwright-core');
const path = require('path');
const OUT = __dirname;

(async () => {
  const exe = process.env.HOME + '/Library/Caches/ms-playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/chrome-headless-shell';
  const browser = await chromium.launch({ executablePath: exe, headless: true, args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1, locale: 'zh-CN' });
  const page = await ctx.newPage();
  page.on('dialog', d => d.accept());
  const shot = async (name, opts = {}) => {
    await page.screenshot({ path: path.join(OUT, name), ...opts });
    console.log('saved', name);
  };

  await page.goto('http://127.0.0.1:8765/app', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);

  // 直接调用同一后端接口并渲染（与手动搜索同一代码路径）
  await page.evaluate(async () => {
    const r = await fetch('/api/search', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: 'graph neural network for drug discovery', format: 'three_part', llm_model: '' }),
    });
    const result = await r.json();
    window.__result = result;
    renderResult(result);
  });
  await page.waitForTimeout(2500);

  // 收藏星图侧栏（滚动到可视区域后再裁剪，避免裁到视口外）
  await page.evaluate(() => document.getElementById('relation-graph').scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(800);
  const sideCards = await page.$$('.sidebar .side-card');
  if (sideCards[1]) {
    await shot('11_文献星图关系图.png', { clip: await sideCards[1].boundingBox() });
  }
  if (sideCards[0]) {
    await shot('15_运行统计面板.png', { clip: await sideCards[0].boundingBox() });
  }

  // 收藏 3 篇，便于展示收藏夹
  await page.evaluate(() => {
    const btns = document.querySelectorAll('#result-list .paper-card .paper-actions button:nth-child(2)');
    for (let i = 0; i < Math.min(3, btns.length); i++) btns[i].click();
  });
  await page.waitForTimeout(2000);

  // 收藏夹 → 管理文件夹
  await page.click('#fav-btn');
  await page.waitForTimeout(1200);
  const ftabs = await page.$$('#drawer-tabs .drawer-tab');
  if (ftabs[1]) { await ftabs[1].click(); await page.waitForTimeout(900); await shot('16_收藏夹文件夹管理.png'); }
  if (ftabs[2]) { await ftabs[2].click(); await page.waitForTimeout(900); await shot('17_收藏导入导出.png'); }
  if (ftabs[0]) { await ftabs[0].click(); await page.waitForTimeout(900); await shot('13_我的收藏夹.png'); }
  await page.click('#drawer-overlay');
  await page.waitForTimeout(500);

  await browser.close();
  console.log('DONE2');
})().catch(e => { console.error('FATAL', e); process.exit(1); });
