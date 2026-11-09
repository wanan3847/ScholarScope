import React, { useEffect, useRef, useState } from "react";
import { api, download, storedText, stored, persist } from "./api";
import { useApp } from "./context";
import { SourceCitation } from "./evidence-workspaces";
import { ChartImage } from "./research-charts";

const makeId = () => "slide_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);

export default function PresentationStudio({ root, project, rows, editable, onSource, onSaved, initialId }) {
  const decks = rows.filter(r => r.kind === "presentation"), evidence = rows.filter(r => r.kind === "evidence");
  const [did, setDid] = useState(initialId || decks[0]?.id || ""), [purpose, setPurpose] = useState("meeting"), [templates, setTemplates] = useState({ purposes: {}, themes: [] }), [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { let live = true; api("/api/workspace/presentation-templates").then(d => live && setTemplates(d)).catch(e => live && setError(e.message)); return () => { live = false; }; }, []);
  return <div className="presentation-workspace"><div className="project-toolbar"><p>将项目原文整理成可编辑研究报告，逐页补充论证、核对来源，再导出 PowerPoint。</p>
    {!!decks.length && <select aria-label="切换演示文稿" value={did} onChange={e => setDid(e.target.value)}>{decks.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}</select>}
    {editable && <><select aria-label="演示用途" value={purpose} onChange={e => setPurpose(e.target.value)}>{Object.entries(templates.purposes).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select>
      <button className="primary-button" disabled={busy || !evidence.length} onClick={async () => { setBusy(true); setError(""); try {
        const d = await api(root + "/presentations/generate", { method: "POST", data: { purpose } }); await onSaved(); setDid(d.id);
      } catch (e) { setError(e.message); } finally { setBusy(false); } }}>{busy ? "正在组织报告…" : "生成 12 页研究报告"}</button></>}
  </div>{error && <p className="form-error" role="alert">{error}</p>}
    {did ? <DeckEditor key={root + did} {...{ root, project, rows, editable, onSource, onSaved, templates, did }} /> : <div className="platform-empty"><h2>让研究结果，清晰地呈现</h2><p>从已核对原文组织组会、开题、答辩或论文讲解；资料缺失时保留明确的补充提示。</p></div>}
  </div>;
}

function SlideCanvas({ slide, theme, citations = [], root }) {
  const style = { background: "#" + theme.background, color: "#" + theme.ink, "--slide-accent": "#" + theme.accent, fontFamily: theme.font + ", sans-serif" };
  return <div className={"slide-canvas layout-" + slide.layout} style={style} aria-label="演示页面预览">
    <span className="slide-eyebrow">SCHOLARSCOPE / RESEARCH</span><h2 style={{ fontFamily: theme.heading_font + ", serif" }}>{slide.title}</h2>
    {slide.subtitle && <p className="slide-subtitle">{slide.subtitle}</p>}
    <div className="slide-bullets">{slide.layout === "chart" && slide.chart_id ? <ChartImage root={root} chartId={slide.chart_id} revision={slide.chart_revision} /> : slide.bullets.map((b, i) => <p key={i}>{b.text}{[...new Set((b.evidence_refs || (b.evidence_id ? [b] : [])).map(r => citations.find(c => c.evidence_id === r.evidence_id)?.number || "引用"))].map(n => <small key={n}> [{n}]</small>)}</p>)}</div>
    {!!citations.length && <footer>{citations.slice(0, 4).map(c => `[${c.number || "?"}] ${c.title} · ${c.page ? `第 ${c.page} 页` : "摘要依据"}`).join(" | ")}</footer>}
  </div>;
}

function DeckEditor({ root, project, rows, editable, onSource, onSaved, templates, did }) {
  const { uid } = useApp();
  const [view, setView] = useState(null), [draft, setDraft] = useState(null), [page, setPage] = useState(0), [dirty, setDirty] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(""), [status, setStatus] = useState("");
  const [sourceId, setSourceId] = useState(""), [playing, setPlaying] = useState(false), [brand, setBrand] = useState(null), [history, setHistory] = useState(null);
  const current = useRef(null), revision = useRef(0), promise = useRef(null), blocked = useRef(false), alive = useRef(true), saveRef = useRef(null);
  const backupKey = `scholarscope-deck-draft:${uid}:${root}:${did}`;
  const load = async discard => {
    const d = await api(root + "/presentations/" + did);
    if (!alive.current) return;
    const backup = !discard && stored(backupKey, null);
    revision.current = d.revision; current.current = backup?.draft || d.data; setDraft(current.current); setView(d); setDirty(!!backup);
    blocked.current = !!backup && backup.revision !== d.revision;
    setError(blocked.current ? "服务器已有新版本。本地修改已保留，可导出副本后重新加载。" : "");
    setStatus(backup ? "已恢复本地修改" : `已保存 · 版本 ${d.revision}`);
    if (discard) { try { localStorage.removeItem(backupKey); } catch {} }
  };
  useEffect(() => { alive.current = true; load(false).catch(e => alive.current && setError(e.message)); return () => { alive.current = false; }; }, [root, did]);
  const change = values => {
    if (!editable) return;
    current.current = { ...current.current, ...values }; setDraft(current.current); setDirty(true); setStatus("有修改，等待保存");
    persist(backupKey, { revision: revision.current, draft: current.current });
  };
  const changeSlide = values => change({ slides: draft.slides.map((s, i) => i === page ? { ...s, ...values } : s) });
  const save = async () => {
    if (!editable || !current.current) return true;
    if (blocked.current) return false;
    if (promise.current) { if (!await promise.current) return false; }
    const snapshot = current.current, baseRevision = revision.current;
    setBusy(true);
    const operation = (async () => {
      try {
        const d = await api(root + "/presentations/" + did, { method: "PUT", data: { data: snapshot, revision: baseRevision } });
        revision.current = d.revision;
        const changed = JSON.stringify(snapshot) !== JSON.stringify(current.current);
        if (!changed) { current.current = d.data; if (alive.current) setDraft(d.data); try { localStorage.removeItem(backupKey); } catch {} }
        else persist(backupKey, { revision: d.revision, draft: current.current });
        if (alive.current) { setView(d); setDirty(changed); setStatus(`已保存 · 版本 ${d.revision}`); setError(""); }
        await onSaved(); return true;
      } catch (e) { blocked.current = true; if (alive.current) setError(e.message + "。你的修改已保留在本机。"); return false; }
      finally { promise.current = null; if (alive.current) setBusy(false); }
    })(); promise.current = operation; return operation;
  };
  saveRef.current = save;
  useEffect(() => { if (!dirty || blocked.current || !editable || busy) return; const t = setTimeout(() => saveRef.current(), 1600); return () => clearTimeout(t); }, [draft, dirty, busy]);
  useEffect(() => { if (!playing) return; const key = e => { if (e.key === "Escape") setPlaying(false); if (e.key === "ArrowRight") setPage(p => Math.min(draft.slides.length - 1, p + 1)); if (e.key === "ArrowLeft") setPage(p => Math.max(0, p - 1)); }; window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key); }, [playing, draft?.slides.length]);
  useEffect(() => { const unload = e => { if (dirty) { e.preventDefault(); e.returnValue = ""; } }; window.addEventListener("beforeunload", unload); return () => window.removeEventListener("beforeunload", unload); }, [dirty]);
  const exportFile = async fmt => {
    if (dirty && !await save()) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(root + "/presentations/" + did + "/export/" + fmt, { headers: storedText("sakura_token") ? { Authorization: "Bearer " + storedText("sakura_token") } : {} });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "演示文稿导出失败");
      const url = URL.createObjectURL(await response.blob()), a = document.createElement("a"); a.href = url; a.download = (draft.title || "research-slides") + "." + fmt; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  if (!draft) return <p role={error ? "alert" : "status"}>{error || "正在读取研究演示文稿…"}</p>;
  const slide = draft.slides[Math.min(page, draft.slides.length - 1)], evidence = rows.filter(r => r.kind === "evidence"), charts = rows.filter(r => r.kind === "chart");
  const citations = [...slide.bullets.flatMap(b => b.evidence_refs || (b.evidence_id ? [b] : [])), ...(charts.find(c => c.id === slide.chart_id)?.data.series.flatMap(s => s.sources.filter(Boolean)) || [])].map(b => view.citations.find(c => c.evidence_id === b.evidence_id) || (() => { const e = evidence.find(e => e.id === b.evidence_id); return e ? { ...e.data, evidence_id: e.id, title: rows.find(p => p.id === e.data.paper_id)?.label, valid: true } : null; })()).filter(Boolean);
  const move = direction => {
    const target = page + direction; if (target < 0 || target >= draft.slides.length) return;
    const slides = [...draft.slides]; [slides[page], slides[target]] = [slides[target], slides[page]]; change({ slides }); setPage(target);
  };
  if (playing) return <div className="slide-player" role="dialog" aria-modal="true" aria-label="研究演示播放"><SlideCanvas {...{ slide, theme: draft.theme, citations, root }} /><div className="slide-player-nav"><button className="secondary-button" disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button><span>{page + 1} / {draft.slides.length}</span><button className="secondary-button" disabled={page === draft.slides.length - 1} onClick={() => setPage(page + 1)}>下一页</button><button className="primary-button" onClick={() => setPlaying(false)}>结束播放</button></div></div>;
  return <><p className="muted" role="note">{draft.generation_mode === "verified_model_synthesis" ? "AI 综合初稿：保留原文依据，需研究者审阅。" : draft.generation_mode === "researcher_authored" ? "研究者撰写的文稿。" : "原文整理草稿：当前未获得通过核对的 AI 综合结果。"}</p>{draft.generation_coverage?.total_sections > 0 && <p className="muted">已形成有原文依据的 AI 要点：{draft.generation_coverage.supported_sections?.length || 0} / {draft.generation_coverage.total_sections} 个内容页。其余页面保留资料摘录或待补充提示。</p>}<div className="writer-status"><span role="status">{status}</span><span>{draft.slides.length} 页 · {view.validation.invalid_citations} 处待重新核对</span></div>
    {error && <div className="form-error" role="alert"><p>{error}</p><div className="project-actions"><button className="secondary-button" onClick={() => download(draft.title + "-local-copy.json", JSON.stringify(draft, null, 2))}>导出本地副本</button><button className="secondary-button" onClick={() => load(true).catch(e => setError(e.message))}>读取服务器版本</button><button className="secondary-button" disabled={busy} onClick={() => { blocked.current = false; save(); }}>重试保存</button></div></div>}
    {view.data.stale && <p className="form-error">关联来源或证据已变化，请核对演示页面中的引用。</p>}
    <div className="project-toolbar"><label className="deck-title-label">演示标题<input aria-label="演示标题" value={draft.title} readOnly={!editable} onChange={e => change({ title: e.target.value })} /></label>
      {editable && <button className="primary-button" disabled={!dirty || busy} onClick={save}>{busy ? "处理中…" : "保存演示文稿"}</button>}
      <button className="secondary-button" onClick={() => setPlaying(true)}>播放演示</button>
      {["pptx", "md", "html"].map(fmt => <button className="secondary-button" disabled={busy} key={fmt} onClick={() => exportFile(fmt)}>导出 {fmt === "md" ? "Markdown" : fmt === "html" ? "网页幻灯片" : "PPTX"}</button>)}
      {editable && <button className="secondary-button" onClick={() => setBrand({ ...draft.theme })}>项目品牌模板</button>}
      <button className="secondary-button" onClick={async () => { try { setHistory((await api(root + "/presentations/" + did + "/versions")).versions); } catch (e) { setError(e.message); } }}>演示版本历史</button>
    </div>
    {brand && <form className="evidence-create" onSubmit={async e => { e.preventDefault(); try {
      await api(root + "/presentation-brand", { method: "PUT", data: { data: brand, revision: project.revision } }); change({ theme: brand }); setBrand(null); await onSaved();
    } catch (e) { setError(e.message); } }}><h2>项目品牌模板</h2><p className="muted">颜色与字体将保存到项目，供成员和新生成的演示文稿使用。</p><label>模板名称<input value={brand.name} onChange={e => setBrand({ ...brand, name: e.target.value })} /></label>
      <div className="brand-fields">{[["background", "背景"], ["surface", "表面"], ["ink", "正文"], ["accent", "强调"]].map(([key, label]) => <label key={key}>{label}颜色<input type="color" value={"#" + brand[key]} onChange={e => setBrand({ ...brand, [key]: e.target.value.slice(1) })} /></label>)}</div>
      <label>正文字体<input value={brand.font} onChange={e => setBrand({ ...brand, font: e.target.value })} /></label><label>标题字体<input value={brand.heading_font} onChange={e => setBrand({ ...brand, heading_font: e.target.value })} /></label>
      <div className="project-actions"><button className="primary-button">保存并应用品牌</button><button type="button" className="secondary-button" onClick={() => setBrand(null)}>取消</button></div></form>}
    {history && <div className="writer-history"><h3>演示版本</h3>{history.map(v => <div key={v.id}><span>版本 {v.data.version} · {v.data.author}</span>{editable && <button className="text-action" onClick={async () => { try { if (dirty && !await save()) return; await api(root + "/presentations/" + did + "/restore", { method: "POST", data: { data: { version_id: v.id }, revision: revision.current } }); await load(true); await onSaved(); setHistory(null); } catch (e) { setError(e.message); } }}>恢复演示版本</button>}</div>)}</div>}
    <div className="deck-editor-layout"><aside className="slide-outline"><h2>演示页面</h2>{draft.slides.map((s, i) => <button aria-current={i === page ? "page" : undefined} key={s.id} onClick={() => setPage(i)}><span>{String(i + 1).padStart(2, "0")}</span>{s.title}</button>)}
      {editable && <button className="secondary-button" disabled={draft.slides.length >= 80} onClick={() => { change({ slides: [...draft.slides, { id: makeId(), title: "新页面", subtitle: "", layout: "content", bullets: [], notes: "" }] }); setPage(draft.slides.length); }}>添加页面</button>}
    </aside><section className="slide-center"><div className="project-toolbar"><span>第 {page + 1} 页</span>{editable && <><button className="secondary-button" disabled={!page} onClick={() => move(-1)}>前移</button><button className="secondary-button" disabled={page === draft.slides.length - 1} onClick={() => move(1)}>后移</button><button className="text-action" disabled={draft.slides.length === 1} onClick={() => { const slides = draft.slides.filter((_, i) => i !== page); change({ slides }); setPage(Math.min(page, slides.length - 1)); }}>删除页面</button></>}</div>
      <SlideCanvas {...{ slide, theme: draft.theme, citations, root }} />
      <div className="slide-source-list"><h3>本页研究依据</h3>{citations.map((c, i) => <div key={i}><blockquote>{c.quote}</blockquote><SourceCitation source={c} onSource={async source => { if (!dirty || await save()) onSource(source); }} /><p className="muted">{c.valid ? "来源当前有效" : "来源已变化，需复核"} · {c.confirmed || c.confirmed_by ? "已人工确认" : "待人工确认"}</p></div>)}{!citations.length && <p className="muted">本页暂未插入原文证据。研究者论证与计划需结合实际资料补充。</p>}</div>
    </section><aside className="slide-settings"><h2>页面内容与布局</h2>
      <label>页面标题<input aria-label="演示页面标题" value={slide.title} readOnly={!editable} onChange={e => changeSlide({ title: e.target.value })} /></label>
      <label>副标题<input value={slide.subtitle} readOnly={!editable} onChange={e => changeSlide({ subtitle: e.target.value })} /></label>
      <label>页面布局<select aria-label="演示页面布局" disabled={!editable} value={slide.layout} onChange={e => changeSlide({ layout: e.target.value })}><option value="title">封面</option><option value="content">正文</option><option value="two_column">双栏比较</option>{!!charts.length && <option value="chart">科研图表</option>}</select></label>
      <label>视觉模板<select aria-label="演示视觉模板" disabled={!editable} value={draft.theme.id || "custom"} onChange={e => change({ theme: templates.themes.find(t => t.id === e.target.value) || project.settings.presentation_brand || draft.theme })}>{templates.themes.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}<option value="custom">项目品牌</option></select></label>
      {slide.bullets.map((b, i) => <div className="slide-bullet-edit" key={i}><label>要点 {i + 1}<textarea aria-label={"演示要点 " + (i + 1)} value={b.text} readOnly={!editable} onChange={e => changeSlide({ bullets: slide.bullets.map((x, n) => n === i ? { ...x, text: e.target.value } : x) })} /></label>
        {b.evidence_id && <p className="muted">已关联项目证据；概括与解释需人工核对。</p>}{editable && <button className="text-action" onClick={() => changeSlide({ bullets: slide.bullets.filter((_, n) => n !== i) })}>移除要点</button>}</div>)}
      {editable && <><button className="secondary-button" disabled={slide.bullets.length >= 12} onClick={() => changeSlide({ bullets: [...slide.bullets, { text: "研究者补充" }] })}>添加要点</button>
        <label>复用项目证据<select aria-label="演示复用证据" value={sourceId} onChange={e => setSourceId(e.target.value)}><option value="">选择原文证据</option>{evidence.map(ev => <option value={ev.id} key={ev.id}>{ev.data.field} · {ev.data.quote.slice(0, 45)}</option>)}</select></label>
        <button className="secondary-button" disabled={!sourceId || slide.bullets.length >= 12} onClick={() => { const ev = evidence.find(e => e.id === sourceId); changeSlide({ bullets: [...slide.bullets, { text: ev.data.quote, evidence_id: ev.id, source_hash: ev.data.source_hash, evidence_revision: ev.revision }] }); setSourceId(""); }}>插入原文证据</button></>}
      {!!charts.length && <label>复用科研图表<select disabled={!editable} value={slide.chart_id || ""} onChange={e => changeSlide({ chart_id: e.target.value || null, chart_revision: charts.find(c => c.id === e.target.value)?.revision || null, layout: e.target.value ? "chart" : "content" })}><option value="">不使用图表</option>{charts.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select></label>}
      {slide.chart_id && editable && <button className="text-action" onClick={() => changeSlide({ chart_revision: charts.find(c => c.id === slide.chart_id)?.revision })}>核对并关联最新图表</button>}
      <label>演讲备注<textarea aria-label="演讲备注" readOnly={!editable} value={slide.notes} onChange={e => changeSlide({ notes: e.target.value })} /></label>
    </aside></div></>;
}
