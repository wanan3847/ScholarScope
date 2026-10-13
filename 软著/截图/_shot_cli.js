// 把真实命令行输出渲染成终端风格截图
// 用法: node 软著/截图/_shot_cli.js <输出文本文件> <输出png> [标题]
const { chromium } = require('/Users/yangyazhou/.hermes/hermes-agent/node_modules/playwright-core');
const fs = require('fs');
const path = require('path');
const OUT = __dirname;

const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

(async () => {
  const [src, out, title = '终端'] = process.argv.slice(2);
  const text = fs.readFileSync(src, 'utf8').replace(/\x1b\[[0-9;]*m/g, '').replace(/\s+$/, '');
  const lines = text.split('\n');
  const html = `<!doctype html><meta charset="utf-8"><style>
    body{margin:0;background:#1b1b1f;font-family:"SF Mono",Menlo,Consolas,monospace}
    .win{background:#232329;border:1px solid #3a3a42;border-radius:12px;margin:18px;overflow:hidden}
    .bar{display:flex;align-items:center;gap:8px;padding:10px 14px;background:#2b2b32;border-bottom:1px solid #3a3a42}
    .dot{width:11px;height:11px;border-radius:50%}
    .t{margin-left:12px;color:#9a9aa6;font-size:12.5px}
    pre{margin:0;padding:16px 18px;color:#e6e6ea;font-size:13px;line-height:1.55;white-space:pre-wrap;word-break:break-all}
    .k{color:#8bd4ff}.g{color:#7ee787}.y{color:#ffd580}
  </style><div class="win"><div class="bar">
    <span class="dot" style="background:#ff5f57"></span>
    <span class="dot" style="background:#febc2e"></span>
    <span class="dot" style="background:#28c840"></span>
    <span class="t">${esc(title)}</span>
  </div><pre>${esc(text)}</pre></div>`;
  fs.writeFileSync(path.join(OUT, '_cli_view.html'), html);

  const exe = process.env.HOME + '/Library/Caches/ms-playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/chrome-headless-shell';
  const browser = await chromium.launch({ executablePath: exe, headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1200, height: 800 }, deviceScaleFactor: 1 });
  await page.goto('file://' + path.join(OUT, '_cli_view.html'));
  await page.waitForTimeout(300);
  await page.locator('.win').screenshot({ path: path.join(OUT, out) });
  await browser.close();
  console.log('saved', out, 'lines=', lines.length);
})().catch(e => { console.error('FATAL', e); process.exit(1); });
