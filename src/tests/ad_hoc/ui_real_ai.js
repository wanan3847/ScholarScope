/* Actual Ollama + previously retrieved public abstracts, isolated account/API. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const {spawn,execFileSync} = require('node:child_process');
const repo = path.resolve(__dirname,'../../..');
const {chromium} = require(path.join(repo,'.cache/ui-check/node_modules/playwright'));
const model = process.env.SCHOLARSCOPE_EVAL_MODEL || 'qwen3.5:4b';
const tmp = fs.mkdtempSync(path.join(process.env.SCHOLARSCOPE_EVAL_TEMP_ROOT || os.tmpdir(),'scholarscope-real-ai-'));
const out = path.join(repo,'.cache',process.env.SCHOLARSCOPE_EVAL_OUTPUT || 'ui-real-ai');
fs.mkdirSync(out,{recursive:true});
fs.writeFileSync(path.join(tmp,'llm_config.json'),JSON.stringify([{name:'isolated-local-check',model,base_url:'http://127.0.0.1:11434/v1',priority:100}]),{mode:0o600});
const python = path.join(repo,'.venv/bin/python');
let browser,server,base;
const report = {date:'2026-10-14',model,source:'Actual retrieved public abstracts; no synthetic papers',stages:{}};
const checkpoint = () => fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));
process.once('SIGTERM',async()=>{
  server?.kill('SIGTERM');
  if(browser)await browser.close().catch(()=>{});
  fs.rmSync(tmp,{recursive:true,force:true});process.exit(143);
});
(async()=>{
  const probe=net.createServer();
  await new Promise((resolve,reject)=>{probe.once('error',reject);probe.listen(0,'127.0.0.1',resolve);});
  const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));
  base='http://127.0.0.1:'+port;
  server=spawn(python,['-m','uvicorn','web.app:app','--host','127.0.0.1','--port',String(port),'--no-access-log'],{
    cwd:path.join(repo,'src'),env:{...process.env,SCHOLARSCOPE_WORKSPACE_DIR:tmp,SCHOLARSCOPE_DATA_DIR:tmp,
      SCHOLARSCOPE_DISABLE_AI:'0',SCHOLARSCOPE_DISABLE_EMBEDDINGS:'1',SCHOLARSCOPE_RESEARCH_CONTEXT:'8192'},stdio:'ignore'});
  for(let i=0;i<100;i++){
    try{if((await fetch(base+'/api/health')).ok)break;}catch{}
    if(server.exitCode!==null)throw Error('Isolated API exited');
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  let token;
  const api = async(url,data)=>{
    const r=await fetch(base+url,{method:data?'POST':'GET',headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:data?JSON.stringify(data):undefined});
    assert(r.ok,url+': '+r.status);return r.json();
  };
  await api('/api/auth/register',{username:'real-ai-check',password:'isolated-research-password'});
  token=(await api('/api/auth/login',{username:'real-ai-check',password:'isolated-research-password'})).token;
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:900},reducedMotion:'reduce'});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(({token})=>{localStorage.setItem('sakura_token',token);localStorage.setItem('sakura_user','real-ai-check');},{token});
  await page.goto(base+'/app#projects',{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'新建项目',exact:true}).first().click();
  await page.getByLabel('项目名称',{exact:true}).fill('真实模型：测井方法与盲井验证');
  await page.getByLabel('研究问题',{exact:true}).fill('比较测井曲线深度学习孔隙度与渗透率预测的方法和盲井验证条件');
  await page.getByRole('button',{name:'创建项目',exact:true}).click();
  await page.getByRole('heading',{name:'真实模型：测井方法与盲井验证.'}).waitFor();
  const project=(await api('/api/workspace/projects')).projects[0];
  const root='/api/workspace/projects/'+project.id;
  const retrieved=JSON.parse(fs.readFileSync(path.join(repo,'.cache/search-coverage/report.json'),'utf8')).papers;
  const dois=['10.21203/rs.3.rs-8698402/v1','10.1016/j.geoen.2024.212851'];
  for(const doi of dois){const paper=retrieved.find(p=>p.doi===doi);assert(paper?.abstract,'Real abstract unavailable');await api(root+'/papers',{paper});}
  report.papers=dois;checkpoint();
  await page.reload({waitUntil:'networkidle'});
  const run = async(button,route)=>{
    const start=Date.now();const pending=page.waitForResponse(r=>r.url().endsWith(root+route)&&r.request().method()==='POST',{timeout:230000});
    await page.getByRole('button',{name:button,exact:true}).click();const response=await pending;assert(response.ok(),route+': '+response.status());
    return {data:await response.json(),seconds:Math.round((Date.now()-start)/100)/10};
  };
  await page.getByRole('tab',{name:'证据矩阵',exact:true}).click();
  let result=await run('提取全部文献','/matrix/extract');
  fs.writeFileSync(path.join(out,'matrix.json'),JSON.stringify(result.data,null,2));
  report.stages.matrix={seconds:result.seconds,model_cells:result.data.rows.flatMap(r=>Object.values(r.cells)).filter(c=>c.extraction_mode==='verified_model').length};checkpoint();
  await page.getByRole('tab',{name:'研究问答',exact:true}).click();
  await page.getByLabel('项目研究问题').fill('well logs porosity permeability blind well validation method：两项研究的模型与盲井验证有什么区别？');
  result=await run('查找研究依据','/questions');
  const answer=result.data.data;
  fs.writeFileSync(path.join(out,'answer.json'),JSON.stringify(answer,null,2));
  assert(!/__STUDY_[A-Z]+__/.test(answer.answer),'Internal study marker reached the answer');
  assert(!/\b(?:AA|AB)\b/.test(answer.answer),'Unexplained study abbreviations reached the well-log comparison');
  assert(answer.citations.length);report.stages.answer={seconds:result.seconds,mode:answer.mode,status:answer.generation_status,answer:answer.answer};checkpoint();
  await page.locator('.question-answer').waitFor();
  await page.locator('.question-answer').getByText(answer.answer,{exact:true}).waitFor();
  await page.locator('.question-answer .answer-text').scrollIntoViewIfNeeded();
  const qaDownload=page.waitForEvent('download');await page.getByRole('button',{name:'导出回答 Markdown',exact:true}).click();
  const qaPath=path.join(out,'answer.md');await(await qaDownload).saveAs(qaPath);
  const qaText=fs.readFileSync(qaPath,'utf8');assert(qaText.includes('引用与原文依据') && answer.citations.every(c=>qaText.includes(c.quote)));
  await page.screenshot({path:path.join(out,'answer.png'),fullPage:true});
  await page.getByRole('tab',{name:'综述写作',exact:true}).click();
  result=await run('从证据生成草稿','/manuscripts/generate');
  fs.writeFileSync(path.join(out,'manuscript.json'),JSON.stringify(result.data,null,2));
  report.stages.manuscript={seconds:result.seconds,mode:result.data.data.generation_mode,coverage:result.data.data.generation_coverage};checkpoint();
  await page.getByLabel('研究文稿编辑器').waitFor();
  const word=page.waitForEvent('download');await page.getByRole('button',{name:'导出 DOCX',exact:true}).click();
  const wordPath=path.join(out,'review.docx');await(await word).saveAs(wordPath);
  const text=execFileSync(python,['-c',"from docx import Document; import sys; print('\\n'.join(p.text for p in Document(sys.argv[1]).paragraphs))",wordPath],{encoding:'utf8'});
  assert(dois.every(doi=>text.includes(doi)));assert(!text.includes('未提供渗透率')&&!text.includes('未报告渗透率'));
  assert(!/__STUDY_[A-Z]+__/.test(text),'Internal study marker reached the manuscript');
  await page.getByRole('tab',{name:'演示报告',exact:true}).click();
  result=await run('生成 12 页研究报告','/presentations/generate');
  fs.writeFileSync(path.join(out,'presentation.json'),JSON.stringify(result.data,null,2));
  report.stages.presentation={seconds:result.seconds,mode:result.data.data.generation_mode,coverage:result.data.data.generation_coverage};checkpoint();
  await page.getByLabel('演示页面标题').waitFor();
  const ppt=page.waitForEvent('download');await page.getByRole('button',{name:'导出 PPTX',exact:true}).click();
  const pptPath=path.join(out,'presentation.pptx');await(await ppt).saveAs(pptPath);
  const slides=execFileSync(python,['-c',"import zipfile,re,sys; z=zipfile.ZipFile(sys.argv[1]); print(len([n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\\d+\\.xml',n)]))",pptPath],{encoding:'utf8'}).trim();assert.equal(slides,'12');
  for(const e of(await api(root+'/items?kind=evidence')).items)assert((await api(root+'/evidence/'+e.id+'/verify')).valid);
  assert.deepEqual(errors,[]);report.engineering_status='PASS';
  report.semantic_boundary='Real calls and source integrity verified; model mode/coverage recorded. This does not establish market parity.';checkpoint();
  console.log(JSON.stringify(report,null,2));
})().catch(e=>{report.error=e.message;checkpoint();console.error(e);process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();server?.kill('SIGTERM');
  await new Promise(resolve=>{if(!server||server.exitCode!==null)return resolve();server.once('exit',resolve);setTimeout(resolve,3000);});
  fs.rmSync(tmp,{recursive:true,force:true});
});
