// 软著操作手册截图脚本：对运行中的 Web 服务逐屏截图
// 用法: node 软著/截图/_shot_ui.js
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

  // 1. 首页
  await page.goto('http://127.0.0.1:8765/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await shot('01_首页.png');

  // 2. 检索主界面（空态）
  await page.goto('http://127.0.0.1:8765/app', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  await shot('02_检索主界面.png');

  // 3. 大模型配置
  await page.click('#model-btn');
  await page.waitForTimeout(500);
  await shot('03_大模型配置.png');
  await page.evaluate(() => closeModelModal());
  await page.waitForTimeout(300);

  // 4. 设置抽屉（检索后端）
  await page.click('#settings-btn');
  await page.waitForTimeout(600);
  await shot('04_数据源与检索后端设置.png');
  // 5. 创新模块
  const tabs = await page.$$('#drawer-tabs .drawer-tab, #drawer-tabs button');
  if (tabs[1]) { await tabs[1].click(); await page.waitForTimeout(600); }
  await shot('05_创新模块面板.png');
  await page.click('#drawer-overlay');
  await page.waitForTimeout(400);

  // 6. 使用文档
  await page.click('#docs-btn');
  await page.waitForTimeout(700);
  await shot('06_内置帮助文档.png');
  await page.keyboard.press('Escape');
  await page.mouse.click(20, 500);
  await page.waitForTimeout(400);

  // 7. 登录 / 注册
  await page.click('#login-btn');
  await page.waitForTimeout(500);
  await shot('07_账号登录注册.png');
  // 注册一个演示账号
  const uname = 'sakura_demo';
  const pwd = 'demo1234';
  await page.click('#login-modal .modal-tab:nth-child(2)');
  await page.fill('#login-username', uname);
  await page.fill('#login-password', pwd);
  await page.click('#login-submit');
  await page.waitForTimeout(1500);
  // 若已注册过则直接登录
  if (await page.$('#login-modal.show')) {
    await page.click('#login-modal .modal-tab:nth-child(1)');
    await page.fill('#login-username', uname);
    await page.fill('#login-password', pwd);
    await page.click('#login-submit');
    await page.waitForTimeout(1500);
  }
  console.log('login text =', await page.textContent('#login-text'));

  // 8. 搜索中（加载态）
  await page.fill('#query-input', 'graph neural network for drug discovery');
  await page.click('#search-btn');
  await page.waitForTimeout(9000);
  await shot('08_检索进行中.png');
  await page.waitForFunction(() => !document.getElementById('loading').classList.contains('show'), null, { timeout: 120000 });
  await page.waitForTimeout(1500);

  // 9. 检索结果主界面
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(400);
  await shot('09_检索结果列表.png');

  // 10. 查询规划区
  const qu = await page.$('#query-understanding');
  if (qu) await shot('10_查询规划与意图理解.png', { clip: await qu.boundingBox().then(b => ({ x: b.x - 10, y: b.y - 60, width: b.width + 20, height: b.height + 70 })) });

  // 11. 文献星图（关系图）
  const graph = await page.$('#relation-graph');
  if (graph) {
    const box = await page.evaluate(() => {
      const b = document.getElementById('relation-graph').closest('.side-card').getBoundingClientRect();
      return { x: Math.max(0, b.x - 2), y: Math.max(0, b.y - 2), width: b.width + 4, height: b.height + 4 };
    });
    await shot('11_文献星图关系图.png', { clip: box });
  }

  // 12. 论文卡片（展开速读）
  await page.click('#result-list .paper-card .paper-actions button:nth-child(4)');
  await page.waitForTimeout(500);
  const card0 = await page.$('#result-list .paper-card');
  if (card0) await shot('12_单篇论文卡片与摘要速览.png', { clip: await card0.boundingBox() });

  // 13. 收藏一篇 + 打开收藏夹
  await page.click('#result-list .paper-card .paper-actions button:nth-child(2)');
  await page.waitForTimeout(1200);
  await page.click('#fav-btn');
  await page.waitForTimeout(1000);
  await shot('13_我的收藏夹.png');
  await page.click('#drawer-overlay');
  await page.waitForTimeout(400);

  // 14. 搜索历史
  await page.click('#history-btn');
  await page.waitForTimeout(800);
  await shot('14_搜索历史.png');
  await page.click('#drawer-overlay');
  await page.waitForTimeout(400);

  await browser.close();
  console.log('ALL DONE');
})().catch(e => { console.error('FATAL', e); process.exit(1); });
