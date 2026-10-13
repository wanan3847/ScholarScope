const { chromium } = require('/Users/yangyazhou/.hermes/hermes-agent/node_modules/playwright-core');

(async () => {
  const exe = process.env.HOME + '/Library/Caches/ms-playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/chrome-headless-shell';
  const browser = await chromium.launch({ executablePath: exe, headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 200)); });
  page.on('pageerror', e => errors.push('pageerror: ' + String(e.message).slice(0, 200)));
  page.on('dialog', d => d.accept());

  const results = {};
  const step = async (name, fn) => {
    try { await fn(); results[name] = 'PASS'; }
    catch (e) { results[name] = 'FAIL: ' + String(e.message).split('\n')[0]; }
  };

  await step('homepage', async () => {
    await page.goto('http://127.0.0.1:8765/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);
    const h1 = await page.textContent('h1');
    if (!h1.includes('文献检索')) throw new Error('h1=' + h1.trim());
  });

  await step('app-load-clean', async () => {
    await page.goto('http://127.0.0.1:8765/app', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);
  });

  await step('settings-drawer', async () => {
    await page.click('#settings-btn');
    await page.waitForTimeout(250);
    const shown = await page.$eval('#drawer', el => el.classList.contains('show'));
    if (!shown) throw new Error('drawer not shown');
    const tabs = await page.textContent('#drawer-tabs');
    if (!tabs.includes('创新模块')) throw new Error('tabs=' + tabs);
    await page.click('#drawer-overlay');
    await page.waitForTimeout(200);
  });

  await step('model-modal', async () => {
    await page.click('#model-btn');
    await page.waitForTimeout(250);
    const shown = await page.$eval('#model-modal', el => el.classList.contains('show'));
    if (!shown) throw new Error('model modal not shown');
    await page.evaluate(() => closeModelModal());
  });

  await step('loading-close-button', async () => {
    await page.evaluate(() => document.getElementById('loading').classList.add('show'));
    await page.click('#loading-close');
    await page.waitForTimeout(100);
    const shown = await page.$eval('#loading', el => el.classList.contains('show'));
    if (shown) throw new Error('loading still shown');
  });

  const uname = 'uitest' + Date.now() % 1000000;
  const pwd = 'test1234';

  await step('login-register', async () => {
    await page.click('#login-btn');
    await page.waitForSelector('#login-modal', { state: 'visible', timeout: 5000 });
    await page.click('.login-tab:last-child');
    await page.fill('#login-username', uname);
    await page.fill('#login-password', pwd);
    await page.click('#login-submit');
    await page.waitForFunction(
      u => document.getElementById('login-text').textContent === u,
      uname, { timeout: 8000 }
    );
  });

  await step('login-logout', async () => {
    await page.click('#login-btn'); // confirm 登出
    await page.waitForFunction(() => document.getElementById('login-text').textContent === '登录', null, { timeout: 8000 });
  });

  await step('login-login-again', async () => {
    await page.click('#login-btn');
    await page.waitForSelector('#login-modal', { state: 'visible', timeout: 5000 });
    await page.fill('#login-username', uname);
    await page.fill('#login-password', pwd);
    await page.click('#login-submit');
    await page.waitForFunction(
      u => document.getElementById('login-text').textContent === u,
      uname, { timeout: 8000 }
    );
  });

  await step('search-mock', async () => {
    await page.fill('#query-input', 'retrieval augmented generation survey');
    await page.click('#search-btn');
    await page.waitForFunction(() => !document.getElementById('loading').classList.contains('show'), null, { timeout: 60000 });
    await page.waitForSelector('#result-list .paper-card', { timeout: 20000 });
    const n = await page.$$eval('#result-list .paper-card', els => els.length);
    if (n === 0) throw new Error('no results');
    const meta = await page.textContent('#stat-meta');
    if (!meta.includes('创新模块')) throw new Error('stat-meta missing innovations');
  });

  await step('favorite-read-buttons', async () => {
    await page.click('.paper-card .paper-actions button:nth-child(2)'); // 收藏
    await page.waitForFunction(() => {
      const t = document.getElementById('toast');
      return t && t.textContent.includes('已加入收藏夹');
    }, null, { timeout: 8000 });
    await page.click('.paper-card .paper-actions button:nth-child(1)'); // 已阅
    await page.waitForFunction(() => {
      const t = document.getElementById('toast');
      return t && t.textContent.includes('已标记已阅');
    }, null, { timeout: 8000 });
    const cnt = await page.textContent('#fav-count');
    if (!cnt || cnt === '0') throw new Error('fav count=' + cnt);
  });

  console.log('USER=' + uname);
  console.log(JSON.stringify(results, null, 1));
  console.log('CONSOLE_ERRORS=' + JSON.stringify(errors));
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
