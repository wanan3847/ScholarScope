import React, { useEffect, useState } from "react";
import { api, download, fetchDownload } from "./api";
import { useApp } from "./context";

function useResearchData(root, path) {
  const [data, setData] = useState(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const load = async () => { const d = await api(root + path); setData(d); return d; };
  useEffect(() => {
    let live = true;
    setData(null); setError("");
    api(root + path).then(d => live && setData(d)).catch(e => live && setError(e.message));
    return () => { live = false; };
  }, [root, path]);
  const act = async fn => {
    setBusy(true); setError("");
    try { return await fn(); } catch (e) { setError(e.message); return null; }
    finally { setBusy(false); }
  };
  return { data, setData, error, busy, load, act };
}

export function SourceCitation({ source, onSource }) {
  return <button className="text-action source-link" onClick={() => onSource(source)}>
    {source.title || "核对原文"} · {source.scope === "fulltext" ? `第 ${source.page} 页` : source.scope === "title" ? "标题依据" : "摘要依据"}
  </button>;
}

export function EvidenceMatrix({ root, editable, onSource, onSaved }) {
  const { data, setData, error, busy, load, act } = useResearchData(root, "/matrix");
  const [selected, setSelected] = useState([]), [columnFields, setColumnFields] = useState(null), [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState({ quote: "", value: "", comment: "", confirmed: false });
  const exportCSV = () => {
    const quote = v => '"' + String(v ?? "").replace(/"/g, '""') + '"';
    const table = [["文献", ...data.columns.flatMap(c => [c.label, c.label + "原文", c.label + "来源"])], ...data.rows.map(r => [r.paper.label,
      ...data.columns.flatMap(c => { const cell = r.cells[c.id], e = cell.evidence?.data;
        return [cell.value, e?.quote, e ? e.scope === "fulltext" ? `第${e.page}页` : e.scope : "未找到依据"]; })])];
    download("evidence-matrix.csv", "\ufeff" + table.map(row => row.map(quote).join(",")).join("\n"), "text/csv;charset=utf-8");
  };
  if (!data) return <p role={error ? "alert" : "status"}>{error || "正在读取证据矩阵…"}</p>;
  const selectedRows = data.rows.filter(r => selected.includes(r.paper.id));
  return <div className="matrix-workspace">
    <div className="project-toolbar"><p>按研究问题比较文献。提取保留原文片段；未找到依据的字段留空，候选结果需人工核对。</p>
      {editable && <><button className="primary-button" disabled={busy || !data.rows.length} onClick={() => act(async () => {
        setData(await api(root + "/matrix/extract", { method: "POST", data: { paper_ids: selected.length ? selected : null } })); await onSaved();
      })}>{busy ? "正在核对原文…" : selected.length ? `提取所选 ${selected.length} 篇` : "提取全部文献"}</button>
      <button className="secondary-button" onClick={() => setColumnFields(data.columns.map(c => ({ ...c })))}>设置比较字段</button></>}
      <button className="secondary-button" disabled={!data.rows.length} onClick={exportCSV}>导出矩阵 CSV</button>
      <button className="secondary-button" disabled={busy || !data.rows.length} onClick={() => act(() => fetchDownload(root + "/matrix/export/xlsx", "evidence-matrix.xlsx"))}>导出矩阵 Excel</button>
    </div>
    {error && <p role="alert" className="form-error">{error}</p>}
    {columnFields && <form className="evidence-create" onSubmit={e => { e.preventDefault(); act(async () => {
      setData(await api(root + "/matrix/columns", { method: "PUT", data: { columns: columnFields, revision: data.project_revision } })); setColumnFields(null); await onSaved();
    }); }}><h2>比较字段</h2><p className="muted">字段说明用于匹配原文。删除字段会隐藏该列，已有证据仍保留在证据库。</p>
      {columnFields.map((c, i) => <div className="column-setting" key={i}>
        <label>字段标识<input required pattern="[a-zA-Z][a-zA-Z0-9_-]*" value={c.id} onChange={e => setColumnFields(columnFields.map((x, n) => n === i ? { ...x, id: e.target.value } : x))} /></label>
        <label>字段名称<input required value={c.label} onChange={e => setColumnFields(columnFields.map((x, n) => n === i ? { ...x, label: e.target.value } : x))} /></label>
        <label>提取提示<input value={c.description} onChange={e => setColumnFields(columnFields.map((x, n) => n === i ? { ...x, description: e.target.value } : x))} /></label>
        <button type="button" className="text-action" disabled={columnFields.length === 1} onClick={() => setColumnFields(columnFields.filter((_, n) => n !== i))}>移除字段</button>
      </div>)}
      <div className="project-actions"><button type="button" className="secondary-button" disabled={columnFields.length >= 24} onClick={() => setColumnFields([...columnFields, { id: "field_" + Date.now(), label: "", description: "" }])}>添加字段</button>
        <button className="primary-button" disabled={busy}>保存字段</button><button type="button" className="secondary-button" onClick={() => setColumnFields(null)}>取消</button></div>
    </form>}
    <p className="muted">{selectedRows.length ? `已选择 ${selectedRows.length} 篇。` : "勾选文献可分批提取。"} 自动提取使用原文匹配，结果显示为待核对候选。</p>
    <div className="matrix-scroll evidence-table" tabIndex={0} aria-label="证据矩阵，可横向滚动"><table><thead><tr>
      <th><input type="checkbox" aria-label="选择全部矩阵文献" checked={!!data.rows.length && selected.length === data.rows.length} onChange={e => setSelected(e.target.checked ? data.rows.map(r => r.paper.id) : [])} /></th>
      <th>文献</th>{data.columns.map(c => <th key={c.id}>{c.label}{editable && <button className="text-action" disabled={busy || !data.rows.length} onClick={() => act(async () => {
        setData(await api(root + "/matrix/extract", { method: "POST", data: { paper_ids: selected.length ? selected : null, column_ids: [c.id] } })); await onSaved();
      })}>提取此字段</button>}</th>)}</tr></thead>
      <tbody>{data.rows.map(row => <tr key={row.paper.id}><td><input type="checkbox" aria-label={"选择 " + row.paper.label} checked={selected.includes(row.paper.id)} onChange={e => setSelected(e.target.checked ? [...selected, row.paper.id] : selected.filter(id => id !== row.paper.id))} /></td>
        <th scope="row">{row.paper.label}<small>{row.paper.data.year || "年份未提供"}</small></th>
        {data.columns.map(c => { const cell = row.cells[c.id], ev = cell.evidence?.data;
          return <td key={c.id}><p>{cell.value || (cell.status === "not_extracted" ? "待提取" : "未找到原文支持")}</p>
            {ev && <><span className={cell.source_valid ? "muted" : "form-error"}>{!cell.source_valid ? "来源已变化，需重新核对" : cell.status === "reviewed" ? "已人工核对" : "原文候选 · 待核对"}</span>
              <SourceCitation source={{ ...ev, title: row.paper.label }} onSource={onSource} /></>}
            {editable && cell.id && <button className="text-action" onClick={() => {
              setEditing({ cell, paper: row.paper, column: c }); setDraft({ ...ev, quote: ev?.quote || "", value: cell.value || "", comment: cell.comment || "", confirmed: cell.status === "reviewed" });
            }}>核对 / 编辑</button>}</td>; })}</tr>)}</tbody></table></div>
    {!data.rows.length && <p className="platform-status">先把文献加入项目，再建立比较矩阵。</p>}
    {editing && <form className="evidence-create" onSubmit={e => { e.preventDefault(); act(async () => {
      await api(root + "/matrix/cells/" + editing.cell.id, { method: "PUT", data: { data: draft, revision: editing.cell.revision } });
      setEditing(null); await load(); await onSaved();
    }); }}><h2>{editing.column.label} · 核对提取</h2><p>{editing.paper.label}</p>
      <SourceCitation source={{ ...(editing.cell.evidence?.data || { scope: "abstract", paper_id: editing.paper.id }), title: editing.paper.label }} onSource={onSource} />
      <label>原文片段<textarea aria-label="矩阵原文片段" required value={draft.quote} onChange={e => setDraft({ ...draft, quote: e.target.value })} /></label>
      <label>提取值或解释<textarea aria-label="矩阵提取值" required value={draft.value} onChange={e => setDraft({ ...draft, value: e.target.value })} /></label>
      <label>研究备注<input value={draft.comment} onChange={e => setDraft({ ...draft, comment: e.target.value })} /></label>
      <label className="check-filter"><input type="checkbox" checked={draft.confirmed} onChange={e => setDraft({ ...draft, confirmed: e.target.checked })} />我已核对原文；概括与解释由我确认</label>
      <div className="project-actions"><button className="primary-button" disabled={busy}>保存核对结果</button><button type="button" className="secondary-button" onClick={() => setEditing(null)}>取消</button></div>
    </form>}
  </div>;
}

export function ProjectQuestions({ root, rows, papers, editable, onSource, onSaved }) {
  const [question, setQuestion] = useState(""), [selected, setSelected] = useState([]), [busy, setBusy] = useState(false), [error, setError] = useState(""), [result, setResult] = useState(null);
  const history = rows.filter(r => r.kind === "answer");
  const answer = result?.data || result;
  return <div className="question-workspace">
    <form className="evidence-create" onSubmit={async e => {
      e.preventDefault(); setBusy(true); setError("");
      try { setResult(await api(root + "/questions", { method: "POST", data: { question, paper_ids: selected.length ? selected : null } })); await onSaved(); }
      catch (e) { setError(e.message); } finally { setBusy(false); }
    }}><h2>向项目资料提问</h2><p className="muted">检索摘要与已上传全文，返回相关原文及出处。模型可用时综合比较并逐项引用原文；未通过依据核验时提供原文摘录。</p>
      <label>研究问题<textarea required maxLength={4000} aria-label="项目研究问题" value={question} onChange={e => setQuestion(e.target.value)} placeholder="例如：这些方法使用什么数据，如何评价孔渗参数预测误差？" /></label>
      <details><summary>限定文献范围（默认全部）</summary><div className="paper-selection">{papers.map(p => <label className="check-filter" key={p.id}><input type="checkbox" checked={selected.includes(p.id)} onChange={e => setSelected(e.target.checked ? [...selected, p.id] : selected.filter(id => id !== p.id))} />{p.label}</label>)}</div></details>
      <button className="primary-button" disabled={busy || !papers.length}>{busy ? "正在检索项目原文…" : "查找研究依据"}</button>
      {editable && <button type="button" className="secondary-button" disabled={busy || !papers.length} onClick={async () => {
        setBusy(true); setError("");
        try { const d = await api(root + "/index", { method: "POST" }); setError(d.semantic_chunks ? "" : "语义模型暂不可用，保留关键词检索。可在模型可用后重新构建。"); }
        catch (e) { setError(e.message); } finally { setBusy(false); }
      }}>重建语义索引</button>}
    </form>
    {error && <p className="form-error" role="alert">{error}</p>}
    {answer && <article className="question-answer"><h2>{answer.question}</h2>
      <p className="muted">{answer.mode?.startsWith("verified_synthesis") ? "模型综合分析 · 引用已核验" : answer.mode?.includes("semantic") ? "语义与关键词联合检索" : "关键词检索"} · {answer.citations?.length || 0} 条可核对出处</p>
      {answer.stale && <p className="form-error">相关证据已更新，这份回答需要重新检索。</p>}
      <p className="answer-text">{answer.answer}</p>
      {answer.citations?.map(c => <div className="answer-source" key={c.number}><span>[{c.number}]</span><SourceCitation source={c} onSource={onSource} /></div>)}
      <button className="secondary-button" onClick={() => {
        const sources=(answer.citations || []).map(c => {
          const paper=papers.find(p => p.id === c.paper_id);
          const d=paper?.data || {};
          return `[${c.number}] ${c.title || paper?.label || "项目文献"}${d.doi ? " · DOI: " + d.doi : ""}\n\n` +
            `${c.page ? "原文第 " + c.page + " 页" : c.scope === "title" ? "标题依据" : "摘要依据"}\n\n> ${String(c.quote || "").replace(/\n/g,"\n> ")}`;
        });
        download("research-answer.md", "# " + answer.question + "\n\n" + answer.answer +
          (answer.stale ? "\n\n来源已变化，请重新核对回答与原文。" : "") + "\n\n## 引用与原文依据\n\n" + sources.join("\n\n"));
      }}>导出回答 Markdown</button>
    </article>}
    {!!history.length && <div className="question-history"><h2>已保存的研究问题</h2>{history.map(r => <button className="text-action" key={r.id} onClick={() => { setResult(r); setQuestion(r.data.question); }}>{r.label}{r.data.stale ? " · 证据已更新" : ""}</button>)}</div>}
  </div>;
}

const decisionLabels = { include: "纳入", exclude: "排除", uncertain: "待讨论", pending: "待完成审阅", conflict: "结论冲突" };
export function SystematicScreening({ root, editable, onSaved }) {
  const { uid } = useApp();
  const { data, setData, error, busy, act } = useResearchData(root, "/screening");
  const [suggestions, setSuggestions] = useState(null), [criteria, setCriteria] = useState(null), [selection, setSelection] = useState(null), [draft, setDraft] = useState({ decision: "include", stage: "title_abstract", reason: "" });
  if (!data) return <p role={error ? "alert" : "status"}>{error || "正在读取文献筛选记录…"}</p>;
  const exportScreening = () => download("screening-records.json", JSON.stringify(data, null, 2), "application/json");
  return <div className="screening-workspace"><div className="project-toolbar"><p>记录纳入与排除依据，保留每位成员在摘要、全文阶段的独立判断。两位成员结论不一致时显示冲突。</p>
    {editable && <button className="secondary-button" onClick={() => setCriteria({ ...data.criteria })}>设置筛选标准</button>}
    {editable && <button className="secondary-button" disabled={busy || !data.criteria.include} onClick={() => act(async () => { const r = await api(root + "/screening/suggestions", {method:"POST"}); setSuggestions(r.data); await onSaved(); })}>生成筛选建议</button>}<button className="secondary-button" onClick={exportScreening}>导出筛选记录</button></div>
    {error && <p role="alert" className="form-error">{error}</p>}
    <div className="screening-flow" aria-label="文献筛选统计">{[["identified", "项目文献"], ["included", "已纳入"], ["excluded", "已排除"], ["pending", "待完成"], ["uncertain", "待讨论"], ["conflicts", "冲突"]].map(([id, label]) => <div key={id}><strong>{data.flow[id]}</strong><span>{label}</span></div>)}</div>
    <div className="screening-criteria"><p><strong>纳入：</strong>{data.criteria.include || "尚未填写标准"}</p><p><strong>排除：</strong>{data.criteria.exclude || "尚未填写标准"}</p><p className="muted">每个阶段需 {data.criteria.reviewers || 2} 位成员完成审阅。</p></div>
    {criteria && <form className="evidence-create" onSubmit={e => { e.preventDefault(); act(async () => {
      setData(await api(root + "/screening/criteria", { method: "PUT", data: { data: criteria, revision: data.project_revision } })); setCriteria(null); await onSaved();
    }); }}><h2>文献筛选标准</h2><label>纳入标准<textarea required value={criteria.include} onChange={e => setCriteria({ ...criteria, include: e.target.value })} /></label>
      <label>排除标准<textarea required value={criteria.exclude} onChange={e => setCriteria({ ...criteria, exclude: e.target.value })} /></label>
      <label>审阅人数<select value={criteria.reviewers || 2} onChange={e => setCriteria({ ...criteria, reviewers: Number(e.target.value) })}><option value={2}>两位成员独立审阅</option><option value={1}>单人审阅</option></select></label>
      <div className="project-actions"><button className="primary-button" disabled={busy}>保存标准</button><button type="button" className="secondary-button" onClick={() => setCriteria(null)}>取消</button></div></form>}
    {data.rows.map(row => <article className="screening-paper" key={row.paper.id}><div className="project-toolbar"><span className={row.status === "conflict" ? "form-error" : "muted"}>{decisionLabels[row.status]} · {row.reviewer_count} 位成员 · {row.stage === "fulltext" ? "全文阶段" : "标题 / 摘要阶段"}</span></div>
      <h2>{row.paper.label}</h2><p>{row.paper.data.abstract || "无摘要，请通过原文进行筛选。"}</p>
      {suggestions?.suggestions.filter(s => s.paper_id === row.paper.id).map((s,i) => <div className="review-finding" key={i}><strong>辅助建议 · {decisionLabels[s.decision]}</strong><p>{s.reason}</p>{s.sources.map((r,j) => <blockquote key={j}>{r.quote}</blockquote>)}<p className="muted">尚未提交人工筛选决定</p></div>)}<div className="screening-votes">{row.decisions.map(v => <p key={v.id}><strong>{v.data.reviewer}</strong> · {v.data.stage === "fulltext" ? "全文" : "标题 / 摘要"} · {decisionLabels[v.data.decision]}<br />{v.data.reason || "未补充说明"}</p>)}</div>
      {editable && <button className="secondary-button" onClick={() => {
        setSelection(row); const old = row.decisions.find(v => v.data.reviewer === uid && v.data.stage === row.stage);
        setDraft(old ? { ...old.data } : { decision: "include", stage: row.stage, reason: "" });
      }}>记录我的筛选</button>}
      {selection?.paper.id === row.paper.id && <form className="evidence-create" onSubmit={e => { e.preventDefault(); act(async () => {
        const old = row.decisions.find(v => v.data.reviewer === uid && v.data.stage === draft.stage);
        setData(await api(root + "/screening", { method: "POST", data: { ...draft, paper_id: row.paper.id, revision: old?.revision } })); setSelection(null); await onSaved();
      }); }}><label>筛选阶段<select value={draft.stage} onChange={e => setDraft({ ...draft, stage: e.target.value })}><option value="title_abstract">标题 / 摘要</option><option value="fulltext">全文筛选</option></select></label>
        <label>筛选结论<select value={draft.decision} onChange={e => setDraft({ ...draft, decision: e.target.value })}><option value="include">纳入</option><option value="exclude">排除</option><option value="uncertain">待讨论</option></select></label>
        <label>判断依据<textarea aria-label="筛选判断依据" required={draft.decision === "exclude"} value={draft.reason} onChange={e => setDraft({ ...draft, reason: e.target.value })} placeholder="对应纳入 / 排除标准，说明具体原因" /></label>
        <div className="project-actions"><button className="primary-button" disabled={busy}>保存我的判断</button><button type="button" className="secondary-button" onClick={() => setSelection(null)}>取消</button></div></form>}
    </article>)}
  </div>;
}
