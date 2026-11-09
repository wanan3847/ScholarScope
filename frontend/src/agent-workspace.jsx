import React, { useEffect, useRef, useState } from "react";
import { api, fetchDownload } from "./api";

const statusText = { queued: "等待执行", running: "执行中", pending: "待执行", completed: "已完成", failed: "执行失败", cancelled: "已取消", interrupted: "执行中断", awaiting_confirmation: "待研究者确认" };
const fieldLabels = { query: "研究问题", limit: "文献数量目标", year_from: "起始年份", year_to: "结束年份", paper_ids: "文献 ID（逗号分隔；留空为全部）", column_ids: "矩阵字段（逗号分隔；留空为全部）", question: "研究问题", template: "写作模板", purpose: "演示用途", evidence_ids: "证据 ID（逗号分隔；留空为全部）", target_id: "导出来源", format: "文件格式", manuscript_id: "待检查稿件", data: "图表数据（JSON）", critical: "包含批判性资料检查" };

export default function AgentWorkspace({ root, project, editable, onSaved, onSource, onOpen }) {
  const [tasks, setTasks] = useState([]), [items, setItems] = useState([]), [registry, setRegistry] = useState({ skills: [], tools: {} });
  const [selected, setSelected] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("研究资料整理与报告"), [query, setQuery] = useState(project.query || ""), [search, setSearch] = useState(false), [deep, setDeep] = useState(true), [custom, setCustom] = useState(false);
  const [steps, setSteps] = useState([{ id: "matrix", tool: "matrix", inputs: {} }, { id: "verify", tool: "verify", inputs: {} }]);
  const mounted = useRef(true), signature = useRef("");
  const load = async () => {
    const [t, r] = await Promise.all([api(root + "/tasks"), api(root + "/items")]);
    if (!mounted.current) return;
    setTasks(t.tasks); setItems(r.items);
    setSelected(value => value && t.tasks.some(task => task.id === value) ? value : t.tasks[0]?.id || "");
    const changed = t.tasks.map(task => task.id + ":" + task.data.status).join("|");
    if (signature.current && signature.current !== changed) await onSaved();
    signature.current = changed;
  };
  useEffect(() => {
    mounted.current = true;
    let timer;
    const refresh = async () => { try { await load(); } catch (e) { if (mounted.current) setError(e.message); } finally { if (mounted.current) timer = setTimeout(refresh, 1200); } };
    refresh();
    api("/api/workspace/skills").then(d => mounted.current && setRegistry(d)).catch(e => mounted.current && setError(e.message));
    return () => { mounted.current = false; clearTimeout(timer); };
  }, [root]);
  const act = async fn => { setBusy(true); setError(""); try { await fn(); await load(); await onSaved(); } catch (e) { if (mounted.current) setError(e.message); } finally { if (mounted.current) setBusy(false); } };
  const task = tasks.find(t => t.id === selected), workflow = task?.data;
  const action = value => act(() => api(root + "/tasks/" + selected + "/" + value, { method: "POST" }));
  const outputs = workflow?.outputs.map(id => items.find(r => r.id === id)).filter(Boolean) || [];
  const savedWorkflows = items.filter(r => r.kind === "workflow");
  return <div className="agent-workspace">
    <div className="module-heading"><div><span className="workspace-label">从计划到研究产物</span><h2>让每一步都有来处</h2><p>任务实际执行项目工具，保留步骤、来源与产物。核验阶段等待你检查后继续。</p></div></div>
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="agent-layout">
      <aside className="agent-sidebar">
        {editable && <form className="agent-plan" onSubmit={e => { e.preventDefault(); act(async () => { const row = await api(root + "/tasks", { method: "POST", data: { title, query, search, deep: search && deep, ...(custom ? { steps } : {}) } }); setSelected(row.id); }); }}>
          <h3>开始一个研究任务</h3>
          <label>任务名称<input required maxLength={200} value={title} onChange={e => setTitle(e.target.value)} /></label>
          <label>任务研究问题<textarea maxLength={4000} value={query} onChange={e => setQuery(e.target.value)} /></label>
          <label className="check-row"><input type="checkbox" checked={custom} onChange={e => setCustom(e.target.checked)} />自定义步骤</label>
          {!custom && <><label className="check-row"><input type="checkbox" checked={search} onChange={e => setSearch(e.target.checked)} />先在线检索并加入真实文献</label>{search && <label className="check-row"><input type="checkbox" checked={deep} onChange={e => setDeep(e.target.checked)} />按资料缺口补检索并获取开放全文</label>}<p className="muted">规划/补检索 → 开放全文 → 语义矩阵 → 综合问答 → 资料审查 → 核验确认 → 综述 → 12 页报告 → Word 与 PPTX。</p></>}
          {custom && <WorkflowEditor {...{ steps, setSteps, registry, title, savedWorkflows, busy }} onLoad={r => { setSteps(r.data.steps); setTitle(r.label); }} onSave={() => act(() => api(root + "/workflows", { method: "POST", data: { data: { title, steps } } }))} />}
          <button className="primary-button" disabled={busy}>保存计划并执行</button>
        </form>}
        <div className="agent-task-list"><h3>项目任务</h3>{tasks.length ? tasks.map(t => <button className={selected === t.id ? "active" : ""} key={t.id} onClick={() => setSelected(t.id)}><strong>{t.label}</strong><span>{statusText[t.data.status]} · {t.data.steps.filter(s => s.status === "completed").length}/{t.data.steps.length} 步</span></button>) : <p className="muted">还没有任务记录。</p>}</div>
        <details className="skill-registry"><summary>科研技能 · {registry.skills.length} 项</summary>{registry.skills.map(s => <details key={s.id}><summary>{s.name} · {s.version}{!s.available ? " · 接口待接入" : ""}</summary><p className="muted">{s.license} · 项目原创</p><pre>{s.instructions.replace(/^---[\s\S]*?---\s*/, "")}</pre></details>)}</details>
      </aside>
      <div className="agent-main">
        {workflow ? <>
          <div className="agent-task-heading"><div><span className="workspace-label">{statusText[workflow.status]}</span><h2>{task.label}</h2><p role="status">{workflow.message}</p><span className="muted">实际执行 {Math.round(workflow.elapsed_seconds)} 秒 · 预算 {workflow.budget_seconds} 秒</span></div><div className="project-actions">{editable && ["queued", "running", "awaiting_confirmation"].includes(workflow.status) && <button disabled={busy} className="secondary-button" onClick={() => action("cancel")}>取消任务</button>}{editable && ["failed", "interrupted", "cancelled"].includes(workflow.status) && <button disabled={busy} className="primary-button" onClick={() => action(workflow.status === "failed" ? "retry" : "resume")}>从未完成步骤恢复</button>}</div></div>
          <ol className="agent-steps">{workflow.steps.map((s, i) => <li key={s.id} className={"agent-step " + s.status}><div className="agent-step-heading"><span className="agent-step-index">{String(i + 1).padStart(2, "0")}</span><div><h3>{s.label}</h3><p>{statusText[s.status]} · 单步预算 {s.budget_seconds} 秒{s.attempts ? " · 已执行 " + s.attempts + " 次" : ""}</p></div></div>{s.error && <p className="form-error">{s.error}</p>}{s.result?.message && <p className="agent-result">{s.result.message}</p>}{s.result?.citations?.map((c, j) => <button className="agent-source" key={j} onClick={() => onSource(c)}>{c.quote}<span>{c.title} · {c.page ? "第 " + c.page + " 页" : "摘要依据"}</span></button>)}{s.result?.report && <div className="agent-verification"><p>{s.result.report.evidence_count} 条证据 · {s.result.report.checks.filter(c => c.valid).length} 条原文匹配 · {s.result.report.checks.filter(c => c.confirmed).length} 条已逐项确认</p><p className="muted">{s.result.report.boundary}</p><details><summary>查看本阶段的原文依据与缺项</summary>{s.result.report.checks.map(c => <button key={c.evidence_id} className="agent-source" onClick={() => onSource(c)}>{c.quote}<span>{c.valid ? "原文匹配" : "来源已变化"} · {c.scope === "fulltext" ? "全文第 " + c.page + " 页" : "摘要或标题依据"}</span></button>)}{s.result.report.findings.map((f, j) => <p className="muted" key={j}>{f.title && <strong>{f.title}：</strong>}{f.message}</p>)}</details></div>}{s.status === "awaiting_confirmation" && editable && <div className="agent-confirmation"><p>确认表示你已检查本阶段资料；单条证据的人工确认状态仍在证据库中独立保存。</p><div className="project-actions"><button className="primary-button" disabled={busy || s.result?.report && !s.result.report.valid} onClick={() => action("approve")}>确认本阶段并继续</button><button className="secondary-button" disabled={busy} onClick={() => action("recheck")}>重新核验来源</button></div></div>}</li>)}</ol>
          {workflow.approvals.length > 0 && <p className="muted">阶段确认：{workflow.approvals.map(a => a.actor + " · " + new Date(a.at * 1000).toLocaleString()).join("；")}</p>}
          <section className="agent-outputs"><div className="project-toolbar"><h3>任务产物 · {outputs.length}</h3>{outputs.some(o => o.kind === "artifact") && <button className="secondary-button" disabled={busy} onClick={() => act(() => fetchDownload(root + "/artifact-bundle", project.title + "-产物.zip"))}>下载项目产物包</button>}</div>{outputs.map(o => <div className="agent-output" key={o.id}><div><strong>{o.label}</strong><p>{o.data.stale ? "来源已变化，需复核" : "保存在当前项目"}</p></div>{o.kind === "artifact" ? <button className="secondary-button" disabled={busy || o.data.stale} onClick={() => act(() => fetchDownload(root + "/artifacts/" + o.id + "/file", o.label))}>下载文件</button> : <button className="text-action" onClick={() => onOpen(o)}>打开产物</button>}</div>)}</section>
        </> : <div className="platform-empty"><h2>从你的研究资料开始</h2><p>建立计划后，任务会逐步执行、核验并保留可回访的产物。</p></div>}
      </div>
    </div>
  </div>;
}

function WorkflowEditor({ steps, setSteps, registry, title, savedWorkflows, onLoad, onSave, busy }) {
  const update = (index, value) => setSteps(steps.map((s, i) => i === index ? { ...s, ...value } : s));
  const input = (i, key, value) => update(i, { inputs: { ...steps[i].inputs, [key]: value } });
  return <div className="workflow-editor">
    {savedWorkflows.length > 0 && <label>已有工作流<select defaultValue="" onChange={e => { const row = savedWorkflows.find(r => r.id === e.target.value); if (row) onLoad(row); }}><option value="">选择保存的流程</option>{savedWorkflows.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}</select></label>}
    {steps.map((s, i) => <fieldset key={i}><legend>步骤 {i + 1}</legend><label>步骤名称<input value={s.id} onChange={e => update(i, { id: e.target.value })} /></label><label>研究操作<select value={s.tool} onChange={e => update(i, { tool: e.target.value, inputs: {} })}>{Object.entries(registry.tools).map(([id, t]) => <option key={id} value={id}>{t.label}</option>)}</select></label>{Object.entries(registry.tools[s.tool]?.inputs || {}).map(([key, type]) => <label key={key}>{fieldLabels[key] || key}{["target_id", "manuscript_id"].includes(key) ? <select value={s.inputs[key]?.from_step || ""} onChange={e => input(i, key, { from_step: e.target.value })}><option value="">选择前面的产物步骤</option>{steps.slice(0, i).filter(p => key === "manuscript_id" ? p.tool === "manuscript" : ["manuscript", "presentation", "chart"].includes(p.tool)).map(p => <option key={p.id} value={p.id}>{p.id}</option>)}</select> : type === "boolean" ? <input type="checkbox" checked={Boolean(s.inputs[key])} onChange={e => input(i, key, e.target.checked)} /> : type === "object" ? <textarea placeholder="请填写实际数据、轴、单位和来源" value={typeof s.inputs[key] === "string" ? s.inputs[key] : JSON.stringify(s.inputs[key] || {}, null, 2)} onChange={e => { try { input(i, key, JSON.parse(e.target.value)); } catch { input(i, key, e.target.value); } }} /> : <input type={type === "integer" ? "number" : "text"} value={type === "ids" ? (s.inputs[key] || []).join(", ") : s.inputs[key] || ""} placeholder={key === "format" ? "docx / pdf / md / pptx / svg / png" : key === "template" ? "review / imrad / proposal" : key === "purpose" ? "meeting / proposal / defense / explain" : ""} onChange={e => { if (!e.target.value) { const inputs = { ...s.inputs }; delete inputs[key]; update(i, { inputs }); } else input(i, key, type === "integer" ? Number(e.target.value) : type === "ids" ? e.target.value.split(",").map(v => v.trim()).filter(Boolean) : e.target.value); }} />}</label>)}<button type="button" className="text-action" disabled={steps.length === 1} onClick={() => setSteps(steps.filter((_, j) => j !== i))}>移除此步骤</button></fieldset>)}
    <div className="project-actions"><button type="button" className="secondary-button" onClick={() => setSteps([...steps, { id: "step" + (steps.length + 1), tool: "matrix", inputs: {} }])}>添加步骤</button><button type="button" className="secondary-button" disabled={busy || !title} onClick={onSave}>保存工作流</button></div>
    <p className="muted">生成稿件或报告前需安排核验步骤。来源产物可以引用前面已完成的步骤。</p>
  </div>;
}
