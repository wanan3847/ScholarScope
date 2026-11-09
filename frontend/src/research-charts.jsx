import React, { useEffect, useState } from "react";
import { api, storedText } from "./api";
import { SourceCitation } from "./evidence-workspaces";

export async function fetchArtifact(url) {
  const response = await fetch(url, { headers: storedText("sakura_token") ? { Authorization: "Bearer " + storedText("sakura_token") } : {} });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "文件读取失败");
  return response.blob();
}

export function ChartImage({ root, chartId, revision, onError }) {
  const [url, setUrl] = useState(""), [error, setError] = useState("");
  useEffect(() => {
    let live = true, image;
    setUrl(""); setError("");
    fetchArtifact(root + "/charts/" + chartId + "/export/svg").then(blob => { image = URL.createObjectURL(blob); if (live) setUrl(image); else URL.revokeObjectURL(image); }).catch(e => { if (live) { setError(e.message); onError?.(e.message); } });
    return () => { live = false; if (image) URL.revokeObjectURL(image); };
  }, [root, chartId, revision]);
  return url ? <img className="research-chart-image" src={url} alt="科研图表，数值与来源见下方记录" /> : <p role={error ? "alert" : "status"} className={error ? "form-error" : "muted"}>{error || "正在绘制科研图表…"}</p>;
}

const emptyDraft = () => ({ title: "", type: "bar", origin: "reported", x_label: "", y_label: "", provenance_note: "", labels: [""], series: [{ name: "数据", values: [""], evidence_ids: [null] }] });
export default function ResearchCharts({ root, rows, editable, onSource, onSaved }) {
  const charts = rows.filter(r => r.kind === "chart"), evidence = rows.filter(r => r.kind === "evidence");
  const [draft, setDraft] = useState(null), [editing, setEditing] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const updateSeries = (n, values) => setDraft({ ...draft, series: draft.series.map((s, i) => i === n ? { ...s, ...values } : s) });
  const downloadChart = async (c, fmt) => { setError(""); try { const url = URL.createObjectURL(await fetchArtifact(root + "/charts/" + c.id + "/export/" + fmt)), a = document.createElement("a"); a.href = url; a.download = c.label + "." + fmt; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); } catch (e) { setError(e.message); } };
  return <div className="charts-workspace"><div className="project-toolbar"><p>使用真实报告值或明确注明来源的研究数据绘图。原文报告值逐点核对，计算与换算保留方法说明。</p>
    {editable && <button className="primary-button" onClick={() => { setDraft(emptyDraft()); setEditing(null); }}>新建科研图表</button>}</div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {draft && <form className="evidence-create chart-form" onSubmit={async e => { e.preventDefault(); setBusy(true); setError(""); try {
      await api(root + "/charts" + (editing ? "/" + editing.id : ""), { method: editing ? "PUT" : "POST", data: { data: draft, revision: editing?.revision } }); setDraft(null); setEditing(null); await onSaved();
    } catch (e) { setError(e.message); } finally { setBusy(false); } }}><h2>{editing ? "编辑并重新核对图表" : "建立有来源的科研图表"}</h2>
      <label>图表标题<input required aria-label="科研图表标题" value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} /></label>
      <div className="evidence-fields"><label>横轴名称与单位<input required aria-label="图表横轴" value={draft.x_label} onChange={e => setDraft({ ...draft, x_label: e.target.value })} /></label><label>纵轴名称与单位<input required aria-label="图表纵轴" value={draft.y_label} onChange={e => setDraft({ ...draft, y_label: e.target.value })} /></label></div>
      <div className="evidence-fields"><label>图表类型<select value={draft.type} onChange={e => setDraft({ ...draft, type: e.target.value })}><option value="bar">柱状图</option><option value="line">折线图</option></select></label><label>数据来源<select aria-label="图表数据来源" value={draft.origin} onChange={e => setDraft({ ...draft, origin: e.target.value })}><option value="reported">原文报告值（逐点核对）</option><option value="researcher_data">研究者提供数据</option><option value="derived">计算 / 换算的派生数据</option></select></label></div>
      <label>来源与计算说明<textarea aria-label="图表来源说明" required={draft.origin !== "reported"} value={draft.provenance_note} onChange={e => setDraft({ ...draft, provenance_note: e.target.value })} /></label>
      <div className="matrix-scroll chart-data-table"><table><thead><tr><th>数据标签</th>{draft.series.map((s, n) => <th key={n}><label>数据组 {n + 1}<input aria-label={"图表数据组 " + (n + 1)} required value={s.name} onChange={e => updateSeries(n, { name: e.target.value })} /></label>{draft.series.length > 1 && <button type="button" className="text-action" onClick={() => setDraft({ ...draft, series: draft.series.filter((_, i) => i !== n) })}>移除此组</button>}</th>)}<th>操作</th></tr></thead><tbody>
        {draft.labels.map((label, i) => <tr key={i}><td><input aria-label={"图表标签 " + (i + 1)} required value={label} onChange={e => setDraft({ ...draft, labels: draft.labels.map((v, j) => j === i ? e.target.value : v) })} /></td>
          {draft.series.map((s, n) => <td key={n}><input type="number" step="any" required aria-label={`图表数值 ${n + 1}-${i + 1}`} value={s.values[i]} onChange={e => updateSeries(n, { values: s.values.map((v, j) => j === i ? e.target.value : v) })} />
            <select aria-label={`图表证据 ${n + 1}-${i + 1}`} required={draft.origin === "reported"} value={s.evidence_ids[i] || ""} onChange={e => updateSeries(n, { evidence_ids: s.evidence_ids.map((v, j) => j === i ? e.target.value || null : v) })}><option value="">{draft.origin === "reported" ? "选择报告该值的证据" : "可选：关联原文证据"}</option>{evidence.map(e => <option key={e.id} value={e.id}>{e.data.field} · {e.data.quote.slice(0, 70)}</option>)}</select></td>)}
          <td><button type="button" className="text-action" disabled={draft.labels.length === 1} onClick={() => setDraft({ ...draft, labels: draft.labels.filter((_, j) => j !== i), series: draft.series.map(s => ({ ...s, values: s.values.filter((_, j) => j !== i), evidence_ids: s.evidence_ids.filter((_, j) => j !== i) })) })}>移除此行</button></td></tr>)}
      </tbody></table></div>
      <div className="project-actions"><button type="button" className="secondary-button" disabled={draft.labels.length >= 500} onClick={() => setDraft({ ...draft, labels: [...draft.labels, ""], series: draft.series.map(s => ({ ...s, values: [...s.values, ""], evidence_ids: [...s.evidence_ids, null] })) })}>添加数据行</button>
        <button type="button" className="secondary-button" disabled={draft.series.length >= 8} onClick={() => setDraft({ ...draft, series: [...draft.series, { name: "数据 " + (draft.series.length + 1), values: draft.labels.map(() => ""), evidence_ids: draft.labels.map(() => null) }] })}>添加数据组</button>
        <button className="primary-button" disabled={busy}>{busy ? "正在核对…" : "核对并保存图表"}</button><button type="button" className="secondary-button" onClick={() => setDraft(null)}>取消</button></div>
    </form>}
    {charts.map(c => <article className="research-chart" key={c.id}><h2>{c.label}</h2><p className="muted">{c.data.origin === "reported" ? "原文报告值" : c.data.origin === "derived" ? "研究者计算 / 换算" : "研究者提供数据"} · {c.data.provenance_note || "每个数据点关联原文证据"}</p>
      <ChartImage root={root} chartId={c.id} revision={c.revision} />
      <div className="project-actions"><button className="secondary-button" onClick={() => downloadChart(c, "svg")}>导出 SVG</button><button className="secondary-button" onClick={() => downloadChart(c, "png")}>导出 PNG</button>{editable && <button className="secondary-button" onClick={() => { setEditing(c); setDraft(structuredClone(c.data)); }}>编辑图表数据</button>}</div>
      <details><summary>数据与来源记录</summary><div className="matrix-scroll"><table><thead><tr><th>{c.data.x_label}</th>{c.data.series.map((s, i) => <th key={i}>{s.name}</th>)}</tr></thead><tbody>{c.data.labels.map((l, i) => <tr key={i}><td>{l}</td>{c.data.series.map((s, n) => <td key={n}>{s.values[i]}{s.evidence_ids[i] && <SourceCitation source={evidence.find(e => e.id === s.evidence_ids[i])?.data || {}} onSource={onSource} />}</td>)}</tr>)}</tbody></table></div></details>
    </article>)}
    {!charts.length && !draft && <div className="platform-empty"><h2>从数据到可核对的图表</h2><p>图表可复用到演示页面，并保留原文报告值与研究者计算的区别。</p></div>}
  </div>;
}
