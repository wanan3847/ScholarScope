import React, { useEffect, useRef, useState } from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Node, mergeAttributes } from "@tiptap/core";
import { api, download, stored, persist, storedText } from "./api";
import { useApp } from "./context";
import { SourceCitation } from "./evidence-workspaces";

const ResearchCitation = Node.create({
  name: "citation", group: "inline", inline: true, atom: true,
  addAttributes() { return { evidenceId: { default: "" }, sourceHash: { default: "" }, evidenceRevision: { default: 1 }, label: { default: "证据" } }; },
  parseHTML() { return [{ tag: "span[data-research-citation]" }]; },
  renderHTML({ node, HTMLAttributes }) { return ["span", mergeAttributes(HTMLAttributes, { "data-research-citation": node.attrs.evidenceId, class: "writer-citation", role: "button", tabindex: "0", title: "点击核对引用证据" }), node.attrs.label.startsWith("[") || node.attrs.label.startsWith("(") ? node.attrs.label : "[" + node.attrs.label + "]"]; },
});

export default function ReviewWriter({ root, rows, editable, onSource, onSaved, initialId }) {
  const manuscripts = rows.filter(r => r.kind === "manuscript"), evidence = rows.filter(r => r.kind === "evidence");
  const [mid, setMid] = useState(initialId || manuscripts[0]?.id || ""), [templates, setTemplates] = useState([]), [template, setTemplate] = useState("review"), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [configuring, setConfiguring] = useState(false);
  const loadTemplates = () => api(root + "/writing-templates").then(d => setTemplates(d.templates));
  useEffect(() => { let live = true; api(root + "/writing-templates").then(d => live && setTemplates(d.templates)).catch(e => live && setError(e.message)); return () => { live = false; }; }, [root]);
  const create = async generated => {
    setBusy(true); setError("");
    try {
      const m = await api(root + "/manuscripts" + (generated ? "/generate" : ""), { method: "POST", data: generated ? { template } : { data: { title: "研究文稿", template, content: { type: "doc", content: [{ type: "paragraph" }] } } } });
      await onSaved(); setMid(m.id);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <div className="writer-workspace"><div className="project-toolbar"><p>从项目证据组织大纲与草稿，再补充论证。引文和参考文献随文稿同步核对。</p>
    {!!manuscripts.length && <select aria-label="切换研究文稿" value={mid} onChange={e => setMid(e.target.value)}>{manuscripts.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}</select>}
    {editable && <><select aria-label="新文稿模板" value={template} onChange={e => setTemplate(e.target.value)}>{templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
      <button className="primary-button" disabled={busy || !evidence.length} onClick={() => create(true)}>{busy ? "正在组织证据…" : "从证据生成草稿"}</button>
      <button className="secondary-button" disabled={busy} onClick={() => create(false)}>新建空白文稿</button><button className="secondary-button" onClick={() => setConfiguring(!configuring)}>配置写作模板</button></>}
  </div>{error && <p role="alert" className="form-error">{error}</p>}
    {configuring && editable && <WritingTemplateForm root={root} templates={templates} onSaved={async () => { await loadTemplates(); await onSaved(); }} />}
    {mid ? <ManuscriptEditor key={root + mid} {...{ root, mid, rows, evidence, editable, onSource, onSaved, templates }} /> : <div className="platform-empty"><h2>把阅读积累写进研究</h2><p>先核对项目证据，再生成有来源的综述草稿；也可从空白文稿开始。</p></div>}
  </div>;
}

function WritingTemplateForm({ root, templates, onSaved }) {
  const fresh = { name: "", sections: "摘要\n引言\n方法\n结果\n讨论\n结论", citation_style: "numeric", source_url: "", font: "Arial", font_size: 11, margin_mm: 25.4, paper_size: "A4", abstract_limit: 0, abstract_unit: "characters", keyword_limit: 10 };
  const [draft, setDraft] = useState(fresh), [error, setError] = useState(""), [busy, setBusy] = useState(false), [status, setStatus] = useState("");
  return <form className="writing-template-form" onSubmit={async e => { e.preventDefault(); setBusy(true); setError(""); try { const p = await api(root); await api(root + "/writing-templates", { method: "PUT", data: { revision: p.revision, data: { ...draft, sections: draft.sections.split("\n").map(s => s.trim()).filter(Boolean) } } }); await onSaved(); setStatus("模板已保存到项目；文稿保存时采用所选模板规范。"); } catch (e) { setError(e.message); } finally { setBusy(false); } }}><h3>项目写作模板</h3><p className="muted">根据期刊或研究单位的明确规范设置；保留规范来源。内置模板为通用结构，未声称符合某一期刊。</p><label>更新已有模板<select value={draft.id || ""} onChange={e => { const t = templates.find(t => t.id === e.target.value); setDraft(t ? { ...fresh, ...t, sections: t.sections.join("\n") } : fresh); }}><option value="">建立新模板</option>{templates.filter(t => t.origin === "researcher_configured").map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label><div className="template-fields"><label>模板名称<input required maxLength={150} value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></label><label>规范来源链接<input type="url" value={draft.source_url} onChange={e => setDraft({ ...draft, source_url: e.target.value })} /></label><label>模板引用格式<select value={draft.citation_style} onChange={e => setDraft({ ...draft, citation_style: e.target.value })}><option value="numeric">顺序编码</option><option value="author_year">作者与年份</option></select></label><label>正文西文字体<input value={draft.font} onChange={e => setDraft({ ...draft, font: e.target.value })} /></label><label>正文大小（pt）<input type="number" min={8} max={20} step={.5} value={draft.font_size} onChange={e => setDraft({ ...draft, font_size: Number(e.target.value) })} /></label><label>页边距（mm）<input type="number" min={10} max={50} step={.1} value={draft.margin_mm} onChange={e => setDraft({ ...draft, margin_mm: Number(e.target.value) })} /></label><label>稿件纸张<select value={draft.paper_size} onChange={e => setDraft({ ...draft, paper_size: e.target.value })}><option>A4</option><option>Letter</option></select></label><label>摘要上限（0 为不限）<input type="number" min={0} max={20000} value={draft.abstract_limit} onChange={e => setDraft({ ...draft, abstract_limit: Number(e.target.value) })} /></label><label>摘要计数<select value={draft.abstract_unit} onChange={e => setDraft({ ...draft, abstract_unit: e.target.value })}><option value="characters">字符</option><option value="words">空格分隔词数</option></select></label><label>关键词数量上限<input type="number" min={1} max={20} value={draft.keyword_limit} onChange={e => setDraft({ ...draft, keyword_limit: Number(e.target.value) })} /></label></div><label>必须包含的章节（每行一项）<textarea required value={draft.sections} onChange={e => setDraft({ ...draft, sections: e.target.value })} /></label>{error && <p role="alert" className="form-error">{error}</p>}{status && <p role="status" className="muted">{status}</p>}<button className="primary-button" disabled={busy}>保存写作模板</button><p className="muted">DOCX 保留可编辑文字并采用纸张、页边距和西文字体设置；PDF 使用本地中文字体，保留所选字号与页面规范。</p></form>;
}

function ManuscriptEditor({ root, mid, rows, evidence, editable, onSource, onSaved, templates }) {
  const { uid } = useApp();
  const [view, setView] = useState(null), [draft, setDraft] = useState(null), [dirty, setDirty] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(""), [status, setStatus] = useState(""), [tick, setTick] = useState(0);
  const [history, setHistory] = useState(null), [insertId, setInsertId] = useState(""), [comment, setComment] = useState("");
  const revision = useRef(0), draftRef = useRef(null), savePromise = useRef(null), live = useRef(true), saveRef = useRef(null), blocked = useRef(false), editorRef = useRef(null);
  const backupKey = `scholarscope-writer-draft:${uid}:${root}:${mid}`;
  const change = values => {
    if (!editable || !draftRef.current) return;
    const next = { ...draftRef.current, ...values };
    draftRef.current = next; setDraft(next); setDirty(true); setStatus("有修改，等待保存"); setTick(t => t + 1);
    persist(backupKey, { revision: revision.current, draft: next });
  };
  const editor = useEditor({
    extensions: [StarterKit.configure({ heading: { levels: [1, 2, 3, 4] }, link: { openOnClick: false, protocols: ["http", "https"] } }), ResearchCitation],
    content: { type: "doc", content: [{ type: "paragraph" }] }, editable,
    editorProps: { attributes: { class: "research-manuscript", "aria-label": "研究文稿编辑器" }, handleClick: (view, pos, event) => {
      const id = event.target.closest?.("[data-research-citation]")?.getAttribute("data-research-citation");
      if (id) { const ev = evidence.find(e => e.id === id); if (ev) { Promise.resolve(saveRef.current?.()).then(saved => { if (saved !== false) onSource(ev.data); }); return true; } } return false;
    } },
    onUpdate: ({ editor }) => change({ content: editor.getJSON() }),
  });
  editorRef.current = editor;
  const load = async discard => {
    const m = await api(root + "/manuscripts/" + mid);
    if (!live.current) return;
    let initial = { ...m.data, title: m.label };
    const backup = !discard && stored(backupKey, null);
    revision.current = m.revision;
    blocked.current = false;
    if (backup) {
      initial = backup.draft;
      if (backup.revision !== m.revision) { blocked.current = true; setError("服务器已有其他成员的新版本。你的本地修改已保留，可导出副本后重新加载。"); }
      else { setStatus("已恢复未保存的本地修改"); setTick(t => t + 1); }
    } else { setStatus(`已保存 · 版本 ${m.revision}`); setError(""); }
    draftRef.current = initial; setDraft(initial); setView(m); setDirty(!!backup);
    editorRef.current?.commands.setContent(initial.content, { emitUpdate: false });
    if (discard) { try { localStorage.removeItem(backupKey); } catch {} }
  };
  useEffect(() => {
    live.current = true;
    load(false).catch(e => live.current && setError(e.message));
    return () => { live.current = false; };
  }, [mid, root]);
  useEffect(() => { if (editor && draftRef.current && !view?.id) editor.commands.setContent(draftRef.current.content, { emitUpdate: false }); }, [editor]);
  const save = async () => {
    if (!editable || !draftRef.current) return true;
    if (blocked.current) return false;
    if (savePromise.current) { const previous = await savePromise.current; if (!previous) return false; }
    const snapshot = { ...draftRef.current, content: editorRef.current?.getJSON() || draftRef.current.content };
    const snapshotText = JSON.stringify(snapshot);
    const baseRevision = revision.current;
    setBusy(true); setError("");
    const operation = (async () => {
      try {
        const m = await api(root + "/manuscripts/" + mid, { method: "PUT", data: { data: snapshot, revision: baseRevision } });
        revision.current = m.revision;
        const stillDirty = JSON.stringify(draftRef.current) !== snapshotText;
        if (live.current) { setView(m); setDirty(stillDirty); setStatus(`已保存 · 版本 ${m.revision}`); }
        if (stillDirty) { persist(backupKey, { revision: m.revision, draft: draftRef.current }); if (live.current) setTick(t => t + 1); }
        else { try { localStorage.removeItem(backupKey); } catch {} }
        await onSaved(); return true;
      } catch (e) {
        blocked.current = true;
        if (live.current) { setError(e.message + "。修改已保留在本机，可导出副本。"); setStatus("尚未保存到服务器"); }
        return false;
      } finally { savePromise.current = null; if (live.current) setBusy(false); }
    })();
    savePromise.current = operation;
    return operation;
  };
  saveRef.current = save;
  useEffect(() => {
    if (!draft || !dirty || blocked.current || !editable) return;
    const timeout = setTimeout(() => saveRef.current(), 1600);
    return () => clearTimeout(timeout);
  }, [tick, editable]);
  useEffect(() => {
    const unload = e => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", unload); return () => window.removeEventListener("beforeunload", unload);
  }, [dirty]);
  const exportFile = async fmt => {
    if (dirty && !await save()) return;
    setError("");
    try {
      const response = await fetch(root + "/manuscripts/" + mid + "/export/" + fmt, { headers: storedText("sakura_token") ? { Authorization: "Bearer " + storedText("sakura_token") } : {} });
      if (!response.ok) throw new Error("文稿导出失败");
      const url = URL.createObjectURL(await response.blob()), a = document.createElement("a"); a.href = url; a.download = (draft.title || "research-manuscript") + "." + fmt; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(e.message); }
  };
  if (!draft || !editor) return <p role={error ? "alert" : "status"}>{error || "正在读取研究文稿…"}</p>;
  const comments = rows.filter(r => r.kind === "comment" && r.data.manuscript_id === mid);
  return <><p className="muted" role="note">{draft.generation_mode === "verified_model_synthesis" ? "AI 综合初稿：保留原文依据，需研究者审阅。" : draft.generation_mode === "researcher_authored" ? "研究者撰写的文稿。" : "原文整理草稿：当前未获得通过核对的 AI 综合结果。"}</p>{draft.generation_coverage?.total_sections > 0 && <p className="muted">已形成有原文依据的 AI 论述：{draft.generation_coverage.supported_sections?.length || 0} / {draft.generation_coverage.total_sections} 个章节。其余章节请补充资料或撰写。</p>}<div className="writer-status"><span role="status">{status}</span>{dirty && <span>本机副本已保留</span>}</div>
    {error && <div className="form-error" role="alert"><p>{error}</p><div className="project-actions"><button className="secondary-button" onClick={() => download(draft.title + "-local-copy.json", JSON.stringify(draft, null, 2))}>导出本地副本</button><button className="secondary-button" onClick={() => load(true).catch(e => setError(e.message))}>读取服务器版本</button><button className="secondary-button" disabled={busy} onClick={() => { blocked.current = false; save(); }}>重试保存</button></div></div>}
    <div className="writer-layout"><div className="writer-main">
      <label className="writer-title">文稿标题<input aria-label="文稿标题" value={draft.title} readOnly={!editable} onChange={e => change({ title: e.target.value })} /></label>
      <details className="writer-metadata"><summary>摘要、关键词与写作格式</summary><label>摘要<textarea value={draft.abstract || ""} readOnly={!editable} onChange={e => change({ abstract: e.target.value })} /></label>
        <label>关键词（分号分隔）<input value={(draft.keywords || []).join("; ")} readOnly={!editable} onChange={e => change({ keywords: e.target.value.split(/[;；]/).map(k => k.trim()).filter(Boolean) })} /></label>
        <label>写作模板<select aria-label="写作模板" disabled={!editable} value={draft.template} onChange={e => change({ template: e.target.value })}>{templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
        <label>引用格式<select aria-label="引用格式" disabled={!editable} value={draft.citation_style || "numeric"} onChange={e => change({ citation_style: e.target.value })}><option value="numeric">顺序编码</option><option value="author_year">作者与年份</option></select></label>
      </details>
      {editable && <div className="writer-toolbar" role="toolbar" aria-label="文稿格式">
        <button className="secondary-button" aria-pressed={editor.isActive("bold")} onClick={() => editor.chain().focus().toggleBold().run()}>加粗</button>
        <button className="secondary-button" onClick={() => editor.chain().focus().toggleItalic().run()}>斜体</button>
        <button className="secondary-button" onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>章节标题</button>
        <button className="secondary-button" onClick={() => editor.chain().focus().toggleBulletList().run()}>列表</button>
        <button className="secondary-button" onClick={() => editor.chain().focus().undo().run()}>撤销</button>
        <button className="secondary-button" onClick={() => editor.chain().focus().redo().run()}>重做</button>
        <button className="primary-button" disabled={busy || !dirty} onClick={save}>{busy ? "保存中…" : "保存文稿"}</button>
      </div>}
      <EditorContent editor={editor} />
      <div className="writer-export project-actions">{["md", "docx", "pdf"].map(fmt => <button className="secondary-button" key={fmt} onClick={() => exportFile(fmt)}>导出 {fmt === "md" ? "Markdown" : fmt.toUpperCase()}</button>)}
        <button className="secondary-button" onClick={async () => { try { setHistory((await api(root + "/manuscripts/" + mid + "/versions")).versions); } catch (e) { setError(e.message); } }}>版本历史</button></div>
      {history && <div className="writer-history"><h3>文稿版本</h3>{history.map(v => <div key={v.id}><span>版本 {v.data.version} · {v.data.author} · {new Date(v.created_at * 1000).toLocaleString("zh-CN")}</span>
        {editable && <button className="text-action" disabled={busy} onClick={async () => { try {
          if (dirty && !await save()) return;
          await api(root + "/manuscripts/" + mid + "/restore", { method: "POST", data: { data: { version_id: v.id }, revision: revision.current } }); await load(true); await onSaved(); setHistory(null);
        } catch (e) { setError(e.message); } }}>恢复为新版本</button>}</div>)}</div>}
    </div><aside className="writer-aside"><h2>研究引用与核对</h2>
      {view?.data.stale && <p className="form-error">引用证据已变化，需重新核对或插入最新证据。</p>}
      <p className="muted">{view?.validation.invalid_citations || 0} 处来源变化 · {view?.validation.unconfirmed_citations || 0} 处待人工确认</p>
      {!!view?.validation.missing_sections.length && <p className="muted">模板待补章节：{view.validation.missing_sections.join("、")}</p>}
      {view?.validation.abstract_over_limit && <p className="form-error">摘要超过模板上限：{view.validation.abstract_count} / {view.validation.abstract_limit}。</p>}
      {view?.validation.keywords_over_limit && <p className="form-error">关键词数量超过所选模板上限。</p>}
      {view?.validation.citation_style_matches === false && <p className="form-error">引用格式与模板要求不同，请核对。</p>}
      {view?.template.source_url && <a className="text-action" target="_blank" rel="noreferrer noopener" href={view.template.source_url}>查看保存的模板规范 ↗</a>}
      {(view?.validation.abstract_missing || view?.validation.keywords_missing) && <p className="muted">{view.validation.abstract_missing ? "摘要待补充。" : ""}{view.validation.keywords_missing ? "关键词待补充。" : ""}</p>}
      {editable && <div className="writer-insert"><label>插入项目证据<select aria-label="插入项目证据" value={insertId} onChange={e => setInsertId(e.target.value)}><option value="">选择证据</option>{evidence.map(ev => <option value={ev.id} key={ev.id}>{ev.data.field} · {ev.data.quote.slice(0, 50)}</option>)}</select></label>
        <button className="secondary-button" disabled={!insertId} onClick={() => { const ev = evidence.find(e => e.id === insertId); editor.chain().focus().insertContent({ type: "citation", attrs: { evidenceId: ev.id, sourceHash: ev.data.source_hash, evidenceRevision: ev.revision, label: ev.data.field } }).run(); }}>在光标处插入引用</button></div>}
      {view?.references.map(ref => <p className="writer-reference" key={ref.paper_id}>{ref.label} {ref.text}</p>)}
      <details><summary>引用证据片段</summary>{view?.citations.map((c, i) => <div className="writer-evidence" key={i}><blockquote>{c.quote}</blockquote><SourceCitation source={c} onSource={async source => { if (!dirty || await save()) onSource(source); }} /></div>)}</details>
      <h2>成员讨论</h2>{comments.map(c => <div className="writer-comment" key={c.id}><strong>{c.data.author}</strong>{c.data.anchor && <blockquote>{c.data.anchor}</blockquote>}<p>{c.data.text}</p><small>文稿版本 {c.data.manuscript_revision}</small></div>)}
      {editable && <form onSubmit={async e => { e.preventDefault(); try { if (dirty && !await save()) return; const { from, to } = editor.state.selection; await api(root + "/manuscripts/" + mid + "/comments", { method: "POST", data: { text: comment, anchor: editor.state.doc.textBetween(from, to) } }); setComment(""); await onSaved(); } catch (e) { setError(e.message); } }}><label>评论<textarea aria-label="文稿评论" required maxLength={5000} value={comment} onChange={e => setComment(e.target.value)} placeholder="选择文稿文字可关联具体片段" /></label><button className="secondary-button">保存评论</button></form>}
    </aside></div></>;
}
