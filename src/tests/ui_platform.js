/* Real project/PDF/evidence UI against an isolated API process and database. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn, execFileSync } = require("node:child_process");
const { chromium } = require(
  path.resolve(__dirname, "../../.cache/ui-check/node_modules/playwright"),
);
const repo = path.resolve(__dirname, "../..");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "scholarscope-platform-"));
const python = path.join(repo, ".venv/bin/python");
const port = 18769;
const base = "http://127.0.0.1:" + port;
const out = path.join(repo, ".cache/ui-check/screenshots");
const server = spawn(
  python,
  [
    "-m",
    "uvicorn",
    "web.app:app",
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
  ],
  {
    cwd: path.join(repo, "src"),
    env: {
      ...process.env,
      SCHOLARSCOPE_WORKSPACE_DIR: tmp,
      SCHOLARSCOPE_DATA_DIR: tmp,
      SCHOLARSCOPE_DATABASE_URL: "sqlite:///" + path.join(tmp, "workspace.sqlite3"),
      SCHOLARSCOPE_DISABLE_EMBEDDINGS: "1",
      SCHOLARSCOPE_DISABLE_AI: "1",
    },
    stdio: "ignore",
  },
);
let browser;
(async () => {
  fs.mkdirSync(out, { recursive: true });
  let ready = false;
  for (let i = 0; i < 80; i++) {
    try {
      if ((await fetch(base + "/api/health")).ok) {
        ready = true;
        break;
      }
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
    if (server.exitCode !== null) break;
  }
  assert(ready, "Isolated workspace API did not start");
  const request = async (url, data, token) => {
    const response = await fetch(base + url, {
      method: data ? "POST" : "GET",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: "Bearer " + token } : {}),
      },
      body: data ? JSON.stringify(data) : undefined,
    });
    assert(response.ok, `${url}: ${response.status}`);
    return response.json();
  };
  await request("/api/auth/register", {
    username: "platform-researcher",
    password: "controlled-platform-password",
  });
  const { token } = await request("/api/auth/login", {
    username: "platform-researcher",
    password: "controlled-platform-password",
  });
  execFileSync(python, [
    "-c",
    "from reportlab.pdfgen.canvas import Canvas\nimport sys\nc=Canvas(sys.argv[1]); c.drawString(50,790,'1. Methods'); c.drawString(50,750,'A neural network predicts permeability from well logs.'); c.drawString(50,710,'RMSE = sqrt(mean squared error)'); c.showPage(); c.drawString(50,790,'2. Results'); c.drawString(50,750,'The dataset contains 120 samples.'); c.save()",
    path.join(tmp, "paper.pdf"),
  ]);
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    reducedMotion: "reduce",
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(
    ({ token }) => {
      localStorage.setItem("sakura_token", token);
      localStorage.setItem("sakura_user", "platform-researcher");
    },
    { token },
  );
  await page.goto(base + "/app#projects", { waitUntil: "networkidle" });
  await page
    .getByRole("button", { name: "新建项目", exact: true })
    .first()
    .click();
  await page
    .getByLabel("项目名称", { exact: true })
    .fill("Controlled project: well log methods");
  await page
    .getByLabel("研究问题", { exact: true })
    .fill("Neural permeability prediction from well logs");
  await page.getByRole("button", { name: "创建项目", exact: true }).click();
  await page
    .getByRole("heading", { name: "Controlled project: well log methods." })
    .waitFor();
  const { projects } = await request("/api/workspace/projects", null, token);
  assert.equal(projects.length, 1);
  const root = "/api/workspace/projects/" + projects[0].id;
  await request(
    root + "/papers",
    {
      paper: {
        title: "Controlled fixture: well log neural prediction",
        doi: "10.1000/platform-ui",
        year: 2024,
        authors: ["Test Author"],
        abstract:
          "A neural network predicts permeability from well logs. The dataset contains 120 samples.",
      },
    },
    token,
  );
  await page.reload({ waitUntil: "networkidle" });
  await page
    .getByRole("heading", {
      name: "Controlled fixture: well log neural prediction",
    })
    .waitFor();
  await page
    .locator('.upload-label input[accept="application/pdf,.pdf"]')
    .setInputFiles(path.join(tmp, "paper.pdf"));
  await page
    .getByRole("button", { name: "阅读 2 页原文" })
    .waitFor({ timeout: 60000 });
  await page.getByRole("button", { name: "阅读 2 页原文" }).click();
  await page.getByLabel("PDF 第 1 页").waitFor();
  await page.locator('.pdf-extracted summary').click();
  await page.getByRole('button',{name:/定位公式候选/}).first().click();
  await page.getByRole('heading',{name:'公式候选与对应原文'}).waitFor();
  await page.getByRole('button',{name:'辅助解读图表或公式'}).click();
  await page.getByText('视觉模型或本地页面渲染暂不可用；可继续查看原图及文字上下文。',{exact:true}).waitFor();
  await page.locator('.pdf-extracted summary').click();
  await page.getByLabel("PDF 下一页").click();
  await page.waitForFunction(() => {
    const canvas = document.querySelector('.pdf-page canvas');
    if (!canvas || canvas.width < 10) return false;
    const pixels = canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
    let dark=0;
    for (let i=0; i<pixels.length; i+=16) if(pixels[i+3]>0 && pixels[i]<100 && ++dark>25)return true;
    return false;
  });
  await page.getByLabel("PDF 证据字段").fill("sample_size");
  await page
    .getByLabel("PDF 证据片段")
    .fill("The dataset contains 120 samples.");
  await page.getByLabel("PDF 阅读批注").fill("Controlled annotation: check sample coverage before comparing models.");
  await page.getByRole("button", { name: "核对并保存证据" }).click();
  await page.getByText("已保存原文第 2 页的证据", { exact: true }).waitFor();
  const { items } = await request(root + "/items?kind=evidence", null, token);
  assert.equal(items[0].data.page, 2);
  assert.equal(items[0].data.validation, "quote_verified");
  assert.equal(items[0].data.note, "Controlled annotation: check sample coverage before comparing models.");
  await page.locator(".pdf-annotations summary").click();
  await page.getByText(items[0].data.note, { exact: true }).waitFor();
  assert.equal(
    (await request(root + "/evidence/" + items[0].id + "/verify", null, token))
      .valid,
    true,
  );
  await page.screenshot({ path: path.join(out, "platform-pdf-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    "Mobile PDF overflow",
  );
  await page.screenshot({
    path: path.join(out, "platform-pdf-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "返回项目资料" }).click();
  await page.getByRole("tab", { name: "证据库", exact: true }).click();
  await page.getByText("原文第 2 页 · 已人工确认", { exact: true }).waitFor();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("tab", { name: "证据矩阵", exact: true }).click();
  await page.getByRole("button", { name: "提取全部文献", exact: true }).click();
  const sampleCell = page.locator('.evidence-table tbody td').filter({ has: page.getByText('120 samples', {exact:true}) });
  await sampleCell.waitFor();
  await sampleCell.getByRole('button', {name:'核对 / 编辑'}).click();
  await page.getByLabel('矩阵提取值').fill('120 samples');
  await page.getByText('我已核对原文；概括与解释由我确认').click();
  await page.getByRole('button', {name:'保存核对结果'}).click();
  await sampleCell.getByText('已人工核对', {exact:true}).waitFor();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', {name:'导出矩阵 CSV'}).click();
  const matrixDownload = await downloadPromise;
  const matrixFile = path.join(tmp,'matrix.csv');
  await matrixDownload.saveAs(matrixFile);
  assert(fs.readFileSync(matrixFile,'utf8').includes('120 samples'));
  await sampleCell.getByRole('button', {name:/第 2 页/}).click();
  await page.getByLabel('PDF 第 2 页').waitFor();
  await page.getByLabel('PDF 研究问题').fill('What dataset contains samples?');
  await page.getByRole('button',{name:'查找本文依据',exact:true}).click();
  await page.locator('.pdf-evidence').getByText(/The dataset contains 120 samples/).last().waitFor();
  await page.getByRole('button',{name:'返回项目资料'}).click();
  await page.getByRole('tab', {name:'研究问答',exact:true}).click();
  await page.getByLabel('项目研究问题').fill('What dataset contains samples?');
  await page.getByRole('button',{name:'查找研究依据'}).click();
  await page.locator('.question-answer').getByText(/The dataset contains 120 samples/).waitFor();
  const qaDownload=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出回答 Markdown',exact:true}).click();
  const qaPath=path.join(tmp,'answer.md');await(await qaDownload).saveAs(qaPath);
  const qaText=fs.readFileSync(qaPath,'utf8');
  assert(qaText.includes('引用与原文依据') && qaText.includes('10.1000/platform-ui') && qaText.includes('The dataset contains 120 samples.'));
  await page.getByRole('tab', {name:'文献筛选',exact:true}).click();
  await page.getByRole('button', {name:'设置筛选标准'}).click();
  await page.getByLabel('纳入标准',{exact:true}).fill('Neural permeability or porosity prediction from well logs');
  await page.getByLabel('排除标准',{exact:true}).fill('Not related to well-log inputs');
  await page.getByLabel('审阅人数').selectOption('1');
  await page.getByRole('button', {name:'保存标准',exact:true}).click();
  await page.getByRole('button', {name:'生成筛选建议',exact:true}).click();
  await page.getByText('尚未提交人工筛选决定',{exact:true}).waitFor();
  assert.equal((await request(root+'/items?kind=screening',null,token)).items.length,0);
  await page.getByRole('button', {name:'记录我的筛选'}).click();
  await page.getByLabel('筛选判断依据').fill('Matching well logs and permeability method');
  await page.getByRole('button', {name:'保存我的判断'}).click();
  await page.getByText('纳入 · 1 位成员 · 标题 / 摘要阶段', {exact:true}).waitFor();
  await page.getByRole('tab', {name:'证据矩阵',exact:true}).click();
  await page.locator('.evidence-table').waitFor();
  await page.screenshot({path:path.join(out,'platform-matrix-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile matrix overflow');
  await page.screenshot({path:path.join(out,'platform-matrix-mobile.png'), fullPage:true});
  await page.getByRole("tab", { name: "证据库", exact: true }).click();
  await page.getByRole("button", { name: "核对来源" }).first().click();
  await page.getByText("来源与片段一致", { exact: true }).waitFor();
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("tab", { name: "证据库", exact: true }).click();
  await page.getByText("原文第 2 页 · 已人工确认", { exact: true }).first().waitFor();
  await page.setViewportSize({width:1440,height:900});
  await page.getByRole('tab',{name:'综述写作',exact:true}).click();
  await page.getByRole('button',{name:'从证据生成草稿',exact:true}).click();
  await page.getByLabel('研究文稿编辑器').waitFor();
  await page.getByText('原文整理草稿：当前未获得通过核对的 AI 综合结果。',{exact:true}).waitFor();
  await page.getByLabel('文稿标题').fill('Controlled editable review');
  await page.getByLabel('研究文稿编辑器').click();
  await page.getByLabel('研究文稿编辑器').press('Control+End');
  await page.getByLabel('研究文稿编辑器').press('Enter');
  await page.keyboard.insertText('Controlled researcher discussion for external validation.');
  await page.getByRole('button',{name:'保存文稿',exact:true}).click();
  await page.getByText(/已保存 · 版本 2/).waitFor();
  const writerDownload = page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 DOCX',exact:true}).click();
  const docFile = path.join(tmp,'review.docx');
  await (await writerDownload).saveAs(docFile);
  const docText = execFileSync(python,['-c',"from docx import Document; import sys; print('\\n'.join(p.text for p in Document(sys.argv[1]).paragraphs))",docFile],{encoding:'utf8'});
  assert(docText.includes('120 samples') && docText.includes('10.1000/platform-ui') && docText.includes('Controlled researcher discussion'));
  await page.getByLabel('文稿评论').fill('Check sample size before submission');
  await page.getByRole('button',{name:'保存评论',exact:true}).click();
  await page.getByText('Check sample size before submission',{exact:true}).waitFor();
  await page.getByRole('button',{name:'版本历史',exact:true}).click();
  await page.locator('.writer-history').getByText(/版本 1/).waitFor();
  await page.locator('.writer-history').getByRole('button',{name:'恢复为新版本'}).last().click();
  await page.waitForFunction(() => document.querySelector('input[aria-label="文稿标题"]')?.value === 'Controlled project: well log methods：研究资料综述');
  assert.equal(await page.getByLabel('文稿标题').inputValue(),'Controlled project: well log methods：研究资料综述');
  await page.screenshot({path:path.join(out,'platform-writer-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile writer overflow');
  await page.screenshot({path:path.join(out,'platform-writer-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:900});
  await page.getByRole('tab',{name:'演示报告',exact:true}).click();
  await page.getByRole('button',{name:'生成 12 页研究报告',exact:true}).click();
  await page.getByLabel('演示页面标题').waitFor();
  assert.equal(await page.locator('.slide-outline button:not(.secondary-button)').count(),12);
  await page.getByLabel('演示页面标题').fill('Controlled editable research presentation');
  await page.getByRole('button',{name:'保存演示文稿',exact:true}).click();
  await page.getByText('已保存 · 版本 2',{exact:true}).waitFor();
  const pptDownload = page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 PPTX',exact:true}).click();
  const pptFile = path.join(tmp,'research.pptx');
  await (await pptDownload).saveAs(pptFile);
  const pptCheck = JSON.parse(execFileSync(python,['-c',"import zipfile,re,json,sys; z=zipfile.ZipFile(sys.argv[1]); slides=[n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\\d+\\.xml',n)]; text='\\n'.join(z.read(n).decode() for n in slides); print(json.dumps({'slides':len(slides),'editable':'<p:sp>' in text,'title':'Controlled editable research presentation' in text,'sample':'120 samples' in text}))",pptFile],{encoding:'utf8'}));
  assert.deepEqual(pptCheck,{slides:12,editable:true,title:true,sample:true});
  await page.getByRole('button',{name:'播放演示',exact:true}).click();
  await page.getByRole('dialog',{name:'研究演示播放'}).waitFor();
  await page.getByRole('button',{name:'下一页',exact:true}).click();
  await page.getByText('2 / 12',{exact:true}).waitFor();
  await page.getByRole('button',{name:'结束播放',exact:true}).click();
  await page.getByRole('button',{name:'项目品牌模板',exact:true}).click();
  await page.getByLabel('模板名称').fill('Controlled paper brand');
  await page.getByRole('button',{name:'保存并应用品牌',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('input[type="color"]'));
  assert.equal((await request(root,null,token)).settings.presentation_brand.name,'Controlled paper brand');
  await page.screenshot({path:path.join(out,'platform-slides-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile presentation overflow');
  await page.screenshot({path:path.join(out,'platform-slides-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:900});
  await page.getByRole('tab',{name:'科研图表',exact:true}).click();
  await page.getByRole('button',{name:'新建科研图表',exact:true}).click();
  await page.getByLabel('科研图表标题').fill('Controlled sample-size chart');
  await page.getByLabel('图表横轴').fill('Study');
  await page.getByLabel('图表纵轴').fill('Sample count (samples)');
  await page.getByLabel('图表标签 1',{exact:true}).fill('Well-log study');
  await page.getByLabel('图表数值 1-1').fill('120');
  const {items:chartEvidence} = await request(root+'/items?kind=evidence',null,token);
  const sampleEvidence = chartEvidence.find(e=>e.data.field==='sample_size' && e.data.quote==='The dataset contains 120 samples.');
  assert(sampleEvidence);
  await page.getByLabel('图表证据 1-1').selectOption(sampleEvidence.id);
  await page.getByRole('button',{name:'核对并保存图表',exact:true}).click();
  await page.locator('.research-chart-image').waitFor({timeout:45000});
  const pngDownload = page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 PNG',exact:true}).click();
  const pngFile = path.join(tmp,'research-chart.png');
  await (await pngDownload).saveAs(pngFile);
  assert(fs.readFileSync(pngFile).subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])));
  await page.screenshot({path:path.join(out,'platform-chart-desktop.png')});
  await page.getByRole('tab',{name:'演示报告',exact:true}).click();
  await page.getByLabel('复用科研图表').selectOption({label:'Controlled sample-size chart'});
  await page.getByRole('button',{name:'保存演示文稿',exact:true}).click();
  await page.locator('.slide-canvas .research-chart-image').waitFor({timeout:45000});
  const chartPptDownload = page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 PPTX',exact:true}).click();
  const chartPptFile = path.join(tmp,'chart-reuse.pptx');
  await (await chartPptDownload).saveAs(chartPptFile);
  const nativeChart = execFileSync(python,['-c',"import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); print(any(n.startswith('ppt/charts/chart') and n.endswith('.xml') for n in z.namelist()) and any(n.endswith('.xlsx') for n in z.namelist()))",chartPptFile],{encoding:'utf8'}).trim();
  assert.equal(nativeChart,'True');
  await page.getByRole('tab',{name:'证据矩阵',exact:true}).click();
  const excelDownload=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出矩阵 Excel',exact:true}).click();
  const excelFile=path.join(tmp,'evidence-matrix.xlsx');
  await (await excelDownload).saveAs(excelFile);
  assert.equal(execFileSync(python,['-c',"from openpyxl import load_workbook; import sys; w=load_workbook(sys.argv[1]); print(w.sheetnames==['证据矩阵','原文出处'] and any('120 samples' in str(c.value) for s in w for r in s for c in r))",excelFile],{encoding:'utf8'}).trim(),'True');
  await page.getByRole('tab',{name:'项目知识库',exact:true}).click();
  await page.getByRole('button',{name:'获取项目可用开放全文',exact:true}).click();
  await page.getByText(/Controlled fixture: well log neural prediction · 项目已有全文/).waitFor();
  await page.getByText('建立资料集合',{exact:true}).click();
  await page.getByLabel('新集合名称').fill('Controlled methods');
  await page.getByRole('button',{name:'保存资料集合',exact:true}).click();
  await page.getByText('整理标签与集合',{exact:true}).click();
  await page.getByLabel('项目文献标签').fill('neural; well logs');
  await page.getByLabel('Controlled methods',{exact:true}).check();
  await page.getByRole('button',{name:'保存文献整理',exact:true}).click();
  await page.locator('.paper-project-tags').getByText('neural',{exact:true}).waitFor();
  await page.getByRole('button',{name:'项目收藏',exact:true}).click();
  await page.getByRole('button',{name:'已项目收藏',exact:true}).waitFor();
  await page.getByRole('button',{name:'标记项目已阅',exact:true}).click();
  await page.getByRole('button',{name:'已项目阅读',exact:true}).waitFor();
  const {items: organizedPapers}=await request(root+'/items?kind=paper',null,token);
  assert.equal(organizedPapers.length,1);
  assert.deepEqual(organizedPapers[0].data.tags,['neural','well logs']);
  fs.writeFileSync(path.join(tmp,'project-import.json'),JSON.stringify([organizedPapers[0].data]));
  await page.getByLabel('导入项目文献文件').setInputFiles(path.join(tmp,'project-import.json'));
  await page.getByText(/已导入 1 篇；0 条未导入/).waitFor();
  assert.equal((await request(root+'/items?kind=paper',null,token)).items.length,1);
  await page.getByLabel('资料导出格式').selectOption('ris');
  const risDownload=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出项目资料',exact:true}).click();
  const risFile=path.join(tmp,'project.ris');
  await (await risDownload).saveAs(risFile);
  assert(fs.readFileSync(risFile,'utf8').includes('DO  - 10.1000/platform-ui'));
  await page.getByLabel('导入项目文献文件').setInputFiles(risFile);
  await page.getByText(/已导入 1 篇；0 条未导入/).waitFor();
  await page.getByRole('tab',{name:'综述写作',exact:true}).click();
  await page.getByRole('button',{name:'配置写作模板',exact:true}).click();
  await page.getByLabel('模板名称',{exact:true}).fill('Controlled writing template');
  await page.getByLabel('模板引用格式').selectOption('author_year');
  await page.getByLabel('正文西文字体').fill('Georgia');
  await page.getByLabel('正文大小（pt）').fill('12');
  await page.getByLabel('页边距（mm）').fill('20');
  await page.getByLabel('稿件纸张').selectOption('Letter');
  await page.getByRole('button',{name:'保存写作模板',exact:true}).click();
  await page.getByText('模板已保存到项目；文稿保存时采用所选模板规范。',{exact:true}).waitFor();
  await page.getByText('摘要、关键词与写作格式',{exact:true}).click();
  await page.getByLabel('写作模板',{exact:true}).selectOption({label:'Controlled writing template'});
  await page.getByLabel('引用格式',{exact:true}).selectOption('author_year');
  await page.getByRole('button',{name:'保存文稿',exact:true}).click();
  const venueDownload=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 DOCX',exact:true}).click();
  const venueFile=path.join(tmp,'venue.docx');
  await (await venueDownload).saveAs(venueFile);
  assert.equal(execFileSync(python,['-c',"from docx import Document; import sys; d=Document(sys.argv[1]); print(d.styles['Normal'].font.name=='Georgia' and abs(d.sections[0].left_margin.mm-20)<.1 and abs(d.sections[0].page_width.mm-215.9)<.1)",venueFile],{encoding:'utf8'}).trim(),'True');
  await page.getByRole('tab',{name:'项目概览',exact:true}).click();
  await page.getByRole('button',{name:'编辑项目',exact:true}).click();
  await page.getByLabel('更新项目说明').fill('Controlled persistent project overview');
  await page.getByRole('button',{name:'保存项目修改',exact:true}).click();
  await page.getByText('Controlled persistent project overview',{exact:true}).waitFor();
  assert.equal((await request(root,null,token)).description,'Controlled persistent project overview');
  await page.getByRole('tab',{name:'文献同步',exact:true}).click();
  await page.getByLabel('数字库 ID',{exact:true}).fill('123');
  await page.getByLabel('API Key',{exact:true}).fill('ControlledContractOnlyKey123456');
  await page.getByRole('button',{name:'保存连接配置',exact:true}).click();
  await page.getByRole('heading',{name:'已保存 个人库 123 配置'}).waitFor();
  await page.getByRole('button',{name:'检查连接',exact:true}).waitFor();
  await page.getByText('尚未检查读取权限，保存配置后点击“检查连接”。',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('API Key',{exact:true}).inputValue(),'');
  assert(await page.getByRole('button',{name:'将项目文献导出到 Zotero',exact:true}).isDisabled());
  const zconfig=await request(root+'/zotero',null,token);
  assert(zconfig.configured && !Object.hasOwn(zconfig,'api_key'));
  await page.reload({waitUntil:'networkidle'});
  await page.getByRole('tab',{name:'文献同步',exact:true}).click();
  await page.getByRole('heading',{name:'已保存 个人库 123 配置'}).waitFor();
  await page.screenshot({path:path.join(out,'platform-zotero-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile Zotero overflow');
  await page.screenshot({path:path.join(out,'platform-zotero-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:900});
  await page.getByRole('button',{name:'断开此账号连接',exact:true}).click();
  await page.getByRole('heading',{name:'已保存 个人库 123 配置'}).waitFor({state:'hidden'});
  await page.getByRole('tab',{name:'研究动态',exact:true}).click();
  await page.getByLabel('保存的研究问题',{exact:true}).fill('Controlled monitor: neural well logs');
  await page.getByLabel('发表年份起始',{exact:true}).fill('2024');
  await page.getByLabel('发表年份截止',{exact:true}).fill('2026');
  await page.getByLabel('检查频率',{exact:true}).selectOption('168');
  await page.getByRole('button',{name:'保存检索关注',exact:true}).click();
  await page.getByRole('heading',{name:'Controlled monitor: neural well logs',exact:true}).waitFor();
  const monitors=(await request(root+'/items?kind=monitor',null,token)).items;
  assert.equal(monitors[0].data.interval_hours,168);
  assert(monitors[0].data.next_due>Date.now()/1000);
  await page.getByRole('button',{name:'改为手动检查',exact:true}).click();
  await page.getByRole('button',{name:'改为手动检查',exact:true}).waitFor({state:'hidden'});
  assert.equal((await request(root+'/items?kind=monitor',null,token)).items[0].data.interval_hours,0);
  await page.screenshot({path:path.join(out,'platform-monitor-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile monitor overflow');
  await page.screenshot({path:path.join(out,'platform-monitor-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:900});
  await page.getByRole('tab',{name:'研究任务',exact:true}).click();
  await page.getByLabel('自定义步骤',{exact:true}).check();
  await page.getByLabel('任务名称',{exact:true}).fill('Controlled saved workflow');
  await page.getByRole('button',{name:'保存工作流',exact:true}).click();
  await page.getByLabel('已有工作流').getByRole('option',{name:'Controlled saved workflow'}).waitFor({state:'attached'});
  await page.getByLabel('自定义步骤',{exact:true}).uncheck();
  await page.getByLabel('任务名称',{exact:true}).fill('Controlled end-to-end research task');
  await page.getByRole('button',{name:'保存计划并执行',exact:true}).click();
  await page.getByRole('button',{name:'确认本阶段并继续',exact:true}).waitFor({timeout:60000});
  const {tasks: waitingTasks} = await request(root+'/tasks',null,token);
  assert.equal(waitingTasks[0].data.status,'awaiting_confirmation');
  assert(!waitingTasks[0].data.steps.find(s=>s.tool==='manuscript').result);
  await page.getByRole('button',{name:'确认本阶段并继续',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.agent-task-heading .workspace-label')?.textContent==='已完成',{},{timeout:60000});
  const {tasks: completedTasks} = await request(root+'/tasks',null,token);
  assert.equal(completedTasks[0].data.status,'completed');
  assert.equal(completedTasks[0].data.approvals[0].actor,'platform-researcher');
  const agentDownload = page.waitForEvent('download');
  await page.locator('.agent-output').filter({hasText:'.docx'}).getByRole('button',{name:'下载文件',exact:true}).click();
  const agentDoc = path.join(tmp,'agent-review.docx');
  await (await agentDownload).saveAs(agentDoc);
  const actualAgentDoc = execFileSync(python,['-c',"from docx import Document; import sys; print('\\n'.join(p.text for p in Document(sys.argv[1]).paragraphs))",agentDoc],{encoding:'utf8'});
  assert(actualAgentDoc.includes('120 samples')&&actualAgentDoc.includes('10.1000/platform-ui'));
  const bundleDownload=page.waitForEvent('download');
  await page.getByRole('button',{name:'下载项目产物包',exact:true}).click();
  const bundleFile=path.join(tmp,'task-artifacts.zip');
  await (await bundleDownload).saveAs(bundleFile);
  const bundleVerified=execFileSync(python,['-c',"import zipfile,sys,json; z=zipfile.ZipFile(sys.argv[1]); m=json.loads(z.read('sources.json')); print(len(m['artifacts'])==2 and all(a['sources'] for a in m['artifacts']))",bundleFile],{encoding:'utf8'}).trim();
  assert.equal(bundleVerified,'True');
  await page.getByRole('heading',{name:'让每一步都有来处',exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'platform-agent-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile Agent overflow');
  await page.getByRole('heading',{name:'让每一步都有来处',exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'platform-agent-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:900});
  await page.getByRole('tab',{name:'资料审查',exact:true}).click();
  await page.getByText('批判性资料检查',{exact:true}).waitFor();
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify(
      {
        status: "PASS",
        checks: [
          "real isolated database/API",
          "project persistence",
          "PDF upload/parse/render",
          "page-grounded quote",
          "persisted PDF reading annotation",
          "verification",
          "mobile PDF",
          "refresh restore",
          "matrix extraction/manual confirmation/CSV",
          "matrix source opens correct PDF page",
          "cross-paper source question",
          "screening criteria, model-unavailable suggestions and separate human vote",
          "mobile matrix",
          "evidence draft/Tiptap edit/save/version restore/comments",
          "actual DOCX references",
          "mobile writer",
          "12 slides/edit/save/native editable PPTX",
          "online slideshow and project brand",
          "mobile presentation",
          "reported data chart/SVG preview/real PNG/native PPT chart reuse",
          "PDF-scoped research question",
          "project overview edit persistence",
          "saved whitelist workflow",
          "real Agent steps and human checkpoint",
          "Agent Word/PPTX and provenance ZIP",
          "project tags/collections/bookmarks/read/import/RIS roundtrip",
          "matrix Excel provenance workbook",
          "configured writing template with real DOCX layout",
          "account-encrypted Zotero configuration/reconnect/disconnect",
          "saved query years/scheduled monitoring/manual disable",
          "no JS errors",
        ],
      },
      null,
      2,
    ),
  );
})()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    if (browser) await browser.close();
    server.kill("SIGTERM");
    await new Promise((resolve) => {
      if (server.exitCode !== null) return resolve();
      server.once("exit", resolve);
      setTimeout(resolve, 3000);
    });
    fs.rmSync(tmp, { recursive: true, force: true });
  });
