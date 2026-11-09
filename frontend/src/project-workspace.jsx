import React, { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  FolderSimple,
  Plus,
  ArrowRight,
  FilePdf,
  Check,
  ArrowLeft,
  UploadSimple,
  Users,
  MagnifyingGlass,
} from "@phosphor-icons/react";
import { api, stored, persist, storedText, paperUrl, download, citation, csv, fetchDownload } from "./api";
import { useApp } from "./context";
import { EvidenceMatrix, ProjectQuestions, SystematicScreening } from "./evidence-workspaces";
import ResearchMonitor, { RelatedPapers } from "./research-monitor";
import "./project-workspace.css";

const PDFReader = lazy(() => import("./pdf-reader"));
const ReviewWriter = lazy(() => import("./review-writer"));
const PresentationStudio = lazy(() => import("./presentation-studio"));
const ResearchCharts = lazy(() => import("./research-charts"));
const AgentWorkspace = lazy(() => import("./agent-workspace"));
const ZoteroSync = lazy(() => import("./zotero-sync"));
export const projectPath = (pid) =>
  "/api/workspace/projects/" + encodeURIComponent(pid);

export function AddToProject({ paper }) {
  const { uid, projectId, navigate, notify, runAction } = useApp();
  return (
    <button
      className="secondary-button"
      onClick={() => {
        if (!projectId) {
          persist("scholarscope-pending-paper:" + uid, paper);
          navigate("projects");
          notify("文献已暂存；建立或选择项目后会加入资料");
          return;
        }
        runAction(async () => {
          await api(projectPath(projectId) + "/papers", {
            method: "POST",
            data: { paper },
          });
          notify("文献已加入当前科研项目");
        });
      }}
    >
      <FolderSimple size={15} />
      加入项目
    </button>
  );
}

export default function ProjectWorkspace() {
  const { uid, projectId, setProjectId, navigate, notify } = useApp();
  const [projects, setProjects] = useState([]),
    [rows, setRows] = useState([]),
    [project, setProject] = useState(null);
  const [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false),
    [tab, setTab] = useState("knowledge"),
    [reader, setReader] = useState(null);
  const [archived, setArchived] = useState(false),
    [membersOpen, setMembersOpen] = useState(false);
  const [draft, setDraft] = useState({ title: "", query: "", description: "" });
  const [sourceExcerpt, setSourceExcerpt] = useState(null);
  const [openItem, setOpenItem] = useState(null);
  const [libraryFilter, setLibraryFilter] = useState({ query: "", collection: "", tag: "", state: "" });
  const root = projectId ? projectPath(projectId) : "";
  const selection = useRef(null);
  selection.current = { uid, projectId, archived };
  const load = async () => {
    const list = await api("/api/workspace/projects", { params: { archived } });
    const stillCurrent = () =>
      selection.current.uid === uid &&
      selection.current.projectId === projectId &&
      selection.current.archived === archived;
    if (!stillCurrent()) return;
    setProjects(list.projects || []);
    if (projectId) {
      const [p, r] = await Promise.all([api(root), api(root + "/items")]);
      if (!stillCurrent()) return;
      setProject(p);
      setRows(r.items || []);
    } else {
      setProject(null);
      setRows([]);
    }
  };
  const act = async (fn) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError("");
    setReader(null);
    setSourceExcerpt(null);
    load()
      .catch((e) => live && setError(e.message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [uid, projectId, archived]);
  const papers = rows.filter((r) => r.kind === "paper"),
    documents = rows.filter((r) => r.kind === "document"),
    evidence = rows.filter((r) => r.kind === "evidence");
  const editable = project && project.role !== "viewer";
  const collections = rows.filter(r => r.kind === "collection");
  const visiblePapers = papers.filter(p => (!libraryFilter.query || (p.label + " " + (p.data.abstract || "")).toLowerCase().includes(libraryFilter.query.toLowerCase())) && (!libraryFilter.collection || p.data.collection_ids?.includes(libraryFilter.collection)) && (!libraryFilter.tag || p.data.tags?.includes(libraryFilter.tag)) && (!libraryFilter.state || p.data[libraryFilter.state]));
  const openSource = source => {
    const doc = documents.find(d => d.id === source.document_id);
    if (doc) { setReader({ ...doc, initialPage: source.page || 1, highlightQuote: source.quote || "" }); return; }
    const paper = papers.find(p => p.id === source.paper_id);
    if (paper) setSourceExcerpt({ paper, scope: source.scope || "abstract", quote: source.quote });
  };
  const openProject = (id) => {
    setProjectId(id);
    setTab("knowledge");
    setOpenItem(null);
    setLibraryFilter({ query: "", collection: "", tag: "", state: "" });
    setMembersOpen(false);
  };
  useEffect(() => {
    const pending = stored("scholarscope-pending-paper:" + uid, null);
    if (!projectId || !editable || !pending) return;
    let live = true;
    api(root + "/papers", { method: "POST", data: { paper: pending } }).then(async () => {
      persist("scholarscope-pending-paper:" + uid, null);
      if (live) { notify("暂存文献已加入当前项目"); await load(); }
    }).catch(e => live && setError(e.message));
    return () => { live = false; };
  }, [uid, projectId, editable]);
  if (reader)
    return (
      <div className="platform-screen">
        <button className="text-action" onClick={() => setReader(null)}>
          <ArrowLeft size={16} />
          返回项目资料
        </button>
        <Suspense fallback={<p role="status">正在加载 PDF 阅读器…</p>}>
          <PDFReader
            key={reader.id}
            pid={projectId}
            document={reader}
            papers={papers}
            editable={editable}
            onSaved={load}
            onSource={openSource}
          />
        </Suspense>
      </div>
    );
  return (
    <div className="platform-screen">
      <header className="project-heading">
        <div>
          <span className="workspace-label">研究项目 / 文献与证据</span>
          <h1>
            {project ? project.title : "让研究，有自己的脉络"}
            <span className="editorial-dot">.</span>
          </h1>
          <p>
            {project
              ? project.description ||
                project.query ||
                "文献、证据与研究产物保存在同一个项目。"
              : "从一个课题出发，积累真实文献和可回溯的证据。"}
          </p>
        </div>
        <div className="project-actions">
          {project && (
            <button
              className="secondary-button"
              onClick={() => openProject("")}
            >
              全部项目
            </button>
          )}
          <button
            className="primary-button"
            onClick={() => setCreating(!creating)}
          >
            <Plus size={15} />
            新建项目
          </button>
        </div>
      </header>
      {error && (
        <p className="form-error" role="alert">
          {error}
          <button className="text-action" onClick={() => act(async () => {})}>
            重新加载
          </button>
        </p>
      )}
      {creating && (
        <form
          className="project-create"
          onSubmit={(e) => {
            e.preventDefault();
            act(async () => {
              const p = await api("/api/workspace/projects", {
                method: "POST",
                data: draft,
              });
              setCreating(false);
              setDraft({ title: "", query: "", description: "" });
              openProject(p.id);
            });
          }}
        >
          <label>
            项目名称
            <input
              required
              maxLength={500}
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              placeholder="例如：测井曲线与孔渗参数预测"
            />
          </label>
          <label>
            研究问题
            <textarea
              value={draft.query}
              onChange={(e) => setDraft({ ...draft, query: e.target.value })}
              placeholder="写明研究主题、方法、对象和明确约束"
            />
          </label>
          <label>
            项目说明
            <input
              value={draft.description}
              onChange={(e) =>
                setDraft({ ...draft, description: e.target.value })
              }
            />
          </label>
          <div className="project-actions">
            <button className="primary-button" disabled={busy}>
              创建项目
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => setCreating(false)}
            >
              取消
            </button>
          </div>
          <p className="muted">
            {uid === "web-anonymous"
              ? "未登录项目保存在共享匿名空间；登录后可建立个人项目。"
              : "项目由当前账号拥有，可添加编辑者与阅读者。"}
          </p>
        </form>
      )}
      {loading && (
        <p className="platform-status" role="status">
          正在读取项目资料…
        </p>
      )}
      {!project && !loading && (
        <>
          <div className="project-toolbar">
            <span>
              {projects.length} 个{archived ? "已归档" : "研究"}项目
            </span>
            <button
              className="secondary-button"
              onClick={() => setArchived(!archived)}
            >
              {archived ? "查看进行中" : "查看已归档"}
            </button>
          </div>
          <div className="project-grid">
            {projects.map((p) => (
              <button
                className="project-card"
                key={p.id}
                onClick={() => openProject(p.id)}
              >
                <div className="project-card-top">
                  <FolderSimple size={22} />
                  <span>
                    {p.role === "owner"
                      ? "我的项目"
                      : p.role === "editor"
                        ? "共享编辑"
                        : "共享阅读"}
                  </span>
                </div>
                <h2>{p.title}</h2>
                <p>{p.query || p.description || "整理文献，建立证据。"}</p>
                <div className="project-card-meta">
                  <span>
                    {p.counts.paper} 篇文献 · {p.counts.evidence} 条证据
                  </span>
                  <ArrowRight size={17} />
                </div>
              </button>
            ))}
          </div>
          {!projects.length && (
            <div className="platform-empty">
              <h2>{archived ? "还没有归档项目" : "建立你的第一个科研项目"}</h2>
              <p>保存研究问题，将检索文献加入项目，再上传原文建立证据。</p>
              <button
                className="secondary-button"
                onClick={() => setCreating(true)}
              >
                新建项目
              </button>
            </div>
          )}
        </>
      )}
      {project && !loading && (
        <>
          <div className="project-toolbar">
            <select
              aria-label="切换科研项目"
              value={projectId}
              onChange={(e) => openProject(e.target.value)}
            >
              {projects.map((p) => (
                <option value={p.id} key={p.id}>
                  {p.title}
                </option>
              ))}
            </select>
            <span>
              {papers.length} 篇文献 · {documents.length} 份原文 ·{" "}
              {evidence.length} 条证据
            </span>
            <button
              className="secondary-button"
              onClick={() => setMembersOpen(!membersOpen)}
            >
              <Users size={15} />
              成员与权限
            </button>
            {project.role === "owner" && (
              <button
                className="secondary-button"
                onClick={() =>
                  act(async () => {
                    await api(root, {
                      method: "PATCH",
                      data: {
                        revision: project.revision,
                        data: { archived: project.archived ? 0 : 1 },
                      },
                    });
                    openProject("");
                  })
                }
              >
                {project.archived ? "恢复项目" : "归档项目"}
              </button>
            )}
          </div>
          {membersOpen && <MemberPanel project={project} onError={setError} />}
          <div
            className="project-tabs"
            role="tablist"
            aria-label="科研项目模块"
          >
            {[
              ["overview", "项目概览"],
              ["knowledge", "项目知识库"],
              ["evidence", "证据库"],
              ["matrix", "证据矩阵"],
              ["questions", "研究问答"],
              ["screening", "文献筛选"],
              ["writer", "综述写作"],
              ["presentation", "演示报告"],
              ["charts", "科研图表"],
              ["agent", "研究任务"],
              ["review", "资料审查"],
              ["activity", "研究动态"],
              ["zotero", "文献同步"],
            ].map(([id, label]) => (
              <button
                role="tab"
                aria-selected={tab === id}
                key={id}
                onClick={() => { setOpenItem(null); setTab(id); }}
              >
                {label}
              </button>
            ))}
          </div>
          <section className="project-content" role="tabpanel">
            {tab === "overview" && <ProjectDashboard {...{ project, rows, editable, root, act, busy }} onNavigate={setTab} />}
            {sourceExcerpt && <div className="source-excerpt" role="region" aria-label="引用来源原文">
              <div className="project-toolbar"><strong>{sourceExcerpt.scope === "title" ? "标题依据" : "摘要依据"}</strong><button className="text-action" onClick={() => setSourceExcerpt(null)}>关闭来源</button></div>
              <h2>{sourceExcerpt.paper.label}</h2>
              {sourceExcerpt.quote && <blockquote>{sourceExcerpt.quote}</blockquote>}
              <p>{sourceExcerpt.scope === "title" ? sourceExcerpt.paper.label : sourceExcerpt.paper.data.abstract || "尚无摘要"}</p>
            </div>}
            {tab === "knowledge" && (
              <>
                <ProjectLibraryTools {...{ root, project, papers, collections, editable, act, busy, libraryFilter, setLibraryFilter }} />
                <div className="project-toolbar">
                  <p>从检索或文献库加入文献；上传 PDF 后，可按页核对与摘录。</p>
                  <button
                    className="secondary-button"
                    onClick={() => navigate("search")}
                  >
                    <MagnifyingGlass size={15} />
                    发现文献
                  </button>
                  <button
                    className="secondary-button"
                    disabled={!papers.length}
                    onClick={() =>
                      download(
                        project.title + ".bib",
                        papers.map((p) => citation(p.data)).join("\n\n"),
                      )
                    }
                  >
                    导出引用
                  </button>
                </div>
                {visiblePapers.map((p) => (
                  <article className="project-paper" key={p.id}>
                    <div>
                      <span className="muted">
                        {p.data.year || "年份未提供"} ·{" "}
                        {(p.data.authors || []).slice(0, 3).join(", ") ||
                          "作者未提供"}
                      </span>
                      <h2>{p.label}</h2>
                      {p.data.scope_notes?.map((note,i) => <p className="muted" key={i}>{note}</p>)}
                      <p>
                        {p.data.abstract ||
                          "未提供摘要；上传原文后可阅读全文。"}
                      </p>
                      {p.data.related_versions?.length > 0 && <details><summary>关联的预印本 / 出版版本（不重复计数）</summary>{p.data.related_versions.map((v,i) => <p key={i}>{v.title}{v.doi && <a href={"https://doi.org/" + encodeURI(v.doi)} target="_blank" rel="noreferrer"> · DOI {v.doi}</a>}</p>)}</details>}<PaperOrganization {...{ root, paper: p, collections, editable, act, busy }} />
                      <PaperSources {...{ root, paper: p, editable, act, busy }} />
                      <RelatedPapers {...{ root, paper: p, editable, act, busy }} />
                      <div className="project-actions">
                        {paperUrl(p.data) && (
                          <a
                            className="secondary-button"
                            href={paperUrl(p.data)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            打开来源 ↗
                          </a>
                        )}
                        {editable && (
                          <label className="secondary-button upload-label">
                            <UploadSimple size={15} />
                            上传 PDF
                            <input
                              type="file"
                              accept="application/pdf,.pdf"
                              disabled={busy}
                              onChange={(e) => {
                                const file = e.target.files[0];
                                e.target.value = "";
                                if (!file) return;
                                act(async () => {
                                  const body = new FormData();
                                  body.append("file", file);
                                  const response = await fetch(
                                    root + "/papers/" + p.id + "/pdf",
                                    {
                                      method: "POST",
                                      headers: storedText("sakura_token")
                                        ? {
                                            Authorization:
                                              "Bearer " +
                                              storedText("sakura_token"),
                                          }
                                        : {},
                                      body,
                                    },
                                  );
                                  const result = await response.json();
                                  if (!response.ok)
                                    throw new Error(
                                      result.detail || "PDF 上传失败",
                                    );
                                  notify("PDF 已解析并保存到项目");
                                });
                              }}
                            />
                          </label>
                        )}
                        {documents
                          .filter((d) => d.data.paper_id === p.id)
                          .map((d) => (
                            <button
                              key={d.id}
                              className="secondary-button"
                              onClick={() => setReader(d)}
                            >
                              <FilePdf size={15} />
                              阅读 {d.data.page_count} 页原文
                            </button>
                          ))}
                        {editable && p.data.abstract && (
                          <button
                            className="secondary-button"
                            onClick={() => {
                              setTab("evidence");
                            }}
                          >
                            摘录证据
                          </button>
                        )}
                      </div>
                    </div>
                  </article>
                ))}
                {!papers.length && (
                  <div className="platform-empty">
                    <h2>把第一篇文献带进课题</h2>
                    <p>在检索结果或文献库的阅读面板点击“加入项目”。</p>
                    <button
                      className="primary-button"
                      onClick={() => navigate("search")}
                    >
                      开始文献检索
                    </button>
                  </div>
                )}
              </>
            )}
            {tab === "evidence" && (
              <EvidenceLibrary
                {...{ root, papers, documents, evidence, editable, act, busy }} onSource={openSource}
              />
            )}
            {tab === "matrix" && <EvidenceMatrix root={root} editable={editable} onSource={openSource} onSaved={load} />}
            {tab === "questions" && <ProjectQuestions root={root} rows={rows} papers={papers} editable={editable} onSource={openSource} onSaved={load} />}
            {tab === "screening" && <SystematicScreening root={root} editable={editable} onSaved={load} />}
            {tab === "writer" && <Suspense fallback={<p role="status">正在加载综述编辑器…</p>}><ReviewWriter root={root} rows={rows} editable={editable} onSource={openSource} onSaved={load} initialId={openItem?.kind === "manuscript" ? openItem.id : ""} /></Suspense>}
            {tab === "presentation" && <Suspense fallback={<p role="status">正在加载演示编辑器…</p>}><PresentationStudio root={root} project={project} rows={rows} editable={editable} onSource={openSource} onSaved={load} initialId={openItem?.kind === "presentation" ? openItem.id : ""} /></Suspense>}
            {tab === "charts" && <Suspense fallback={<p role="status">正在加载科研图表…</p>}><ResearchCharts root={root} rows={rows} editable={editable} onSource={openSource} onSaved={load} /></Suspense>}
            {tab === "activity" && <><Suspense fallback={<p role="status">正在加载文献动态…</p>}><ResearchMonitor {...{ root, rows, project, editable, act, busy }} onSaved={load} onTask={() => setTab("agent")} /></Suspense><ProjectActivity root={root} /></>}
            {tab === "agent" && <Suspense fallback={<p role="status">正在加载研究任务…</p>}><AgentWorkspace root={root} project={project} editable={editable} onSaved={load} onSource={openSource} onOpen={item => { setOpenItem(item); setTab(({ manuscript: "writer", presentation: "presentation", chart: "charts", answer: "questions", review: "review", search_report: "knowledge" })[item.kind] || "knowledge"); }} /></Suspense>}
            {tab === "review" && <ProjectReview {...{ root, rows, editable, act, busy }} onSource={openSource} />}
            {tab === "zotero" && <Suspense fallback={<p role="status">正在加载文献同步…</p>}><ZoteroSync root={root} editable={editable} onSaved={load} /></Suspense>}
          </section>
        </>
      )}
    </div>
  );
}

function ProjectLibraryTools({ root, project, papers, collections, editable, act, busy, libraryFilter, setLibraryFilter }) {
  const { notify } = useApp();
  const [format, setFormat] = useState("bib"), [collectionTitle, setCollectionTitle] = useState(""), [report, setReport] = useState(null);
  const [doi, setDOI] = useState(""), [acquisition, setAcquisition] = useState(null);
  const tags = [...new Set(papers.flatMap(p => p.data.tags || []))].sort();
  return <div className="project-library-tools">{editable && <div className="project-actions"><button className="secondary-button" disabled={busy || !papers.length} onClick={() => act(async () => { const r = await api(root + "/acquire", {method:"POST"}); setAcquisition(r); notify("本轮取得 " + r.downloaded + " 份全文；未取得的资料可继续查找或上传。"); })}>获取项目可用开放全文</button></div>}{acquisition && <details open><summary>{acquisition.message}</summary>{acquisition.records.map((r, i) => <p key={i}>{papers.find(p => p.id === r.paper_id)?.label || "项目文献"} · {{downloaded:"已取得全文",already_available:"项目已有全文",no_open_link:"未找到开放全文",budget_exhausted:"本轮预算已用完，可继续获取",download_failed:"下载或解析未成功"}[r.status] || r.status}</p>)}</details>}<div className="library-filters"><label>查找项目文献<input value={libraryFilter.query} onChange={e => setLibraryFilter({ ...libraryFilter, query: e.target.value })} placeholder="标题、摘要" /></label><label>资料集合<select value={libraryFilter.collection} onChange={e => setLibraryFilter({ ...libraryFilter, collection: e.target.value })}><option value="">全部集合</option>{collections.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select></label><label>文献标签<select value={libraryFilter.tag} onChange={e => setLibraryFilter({ ...libraryFilter, tag: e.target.value })}><option value="">全部标签</option>{tags.map(t => <option key={t} value={t}>{t}</option>)}</select></label><label>项目阅读状态<select value={libraryFilter.state} onChange={e => setLibraryFilter({ ...libraryFilter, state: e.target.value })}><option value="">全部文献</option><option value="bookmarked">项目收藏</option><option value="read">项目已阅</option></select></label></div>
    <div className="project-toolbar"><label>资料导出格式<select value={format} onChange={e => setFormat(e.target.value)}><option value="bib">BibTeX</option><option value="ris">RIS</option><option value="json">JSON</option><option value="csv">CSV</option></select></label><button className="secondary-button" disabled={busy || !papers.length} onClick={() => act(() => fetchDownload(root + "/references/export/" + format + (libraryFilter.collection ? "?collection_id=" + encodeURIComponent(libraryFilter.collection) : ""), project.title + "." + format))}>导出项目资料</button>{editable && <label className="secondary-button upload-label">导入文献文件<input type="file" aria-label="导入项目文献文件" accept=".bib,.bibtex,.ris,.csv,.json,.xml" disabled={busy} onChange={e => { const file = e.target.files[0]; e.target.value = ""; if (!file) return; act(async () => { if (file.size > 5 * 1024 * 1024) throw new Error("文献文件不得超过 5 MB"); const { parseImport } = await import("./import"); const papers = parseImport(await file.text(), file.name); const result = await api(root + "/paper-import", { method: "POST", data: { data: { papers } } }); setReport(result); notify("已导入 " + result.imported + " 篇项目文献"); }); }} /></label>}</div>
    {report && <p className="muted" role="status">已导入 {report.imported} 篇；{report.failures.length} 条未导入{report.failures.slice(0, 3).map(f => " · 第 " + f.row + " 条：" + f.reason).join("")}</p>}
    {editable && <><details><summary>建立资料集合</summary><form className="collection-create" onSubmit={e => { e.preventDefault(); act(async () => { await api(root + "/collections", { method: "POST", data: { data: { title: collectionTitle } } }); setCollectionTitle(""); }); }}><label>新集合名称<input required maxLength={100} value={collectionTitle} onChange={e => setCollectionTitle(e.target.value)} /></label><button className="secondary-button" disabled={busy}>保存资料集合</button></form></details><details><summary>按 DOI 加入真实文献</summary><form className="collection-create" onSubmit={e => { e.preventDefault(); act(async () => { await api(root + "/doi", { method: "POST", data: { data: { doi } } }); setDOI(""); notify("DOI 书目信息已加入项目"); }); }}><label>文献 DOI<input required value={doi} onChange={e => setDOI(e.target.value)} placeholder="10.xxxx/..." /></label><button className="secondary-button" disabled={busy}>查找并加入 DOI 文献</button></form></details></>}
  </div>;
}

function PaperSources({ root, paper, editable, act, busy }) {
  const [links, setLinks] = useState(null), [url, setURL] = useState(""), [error, setError] = useState(""), [finding, setFinding] = useState(false);
  const resolve = async () => { setFinding(true); setError(""); try { setLinks(await api(root + "/papers/" + paper.id + "/oa")); } catch (e) { setError(e.message); } finally { setFinding(false); } };
  return <details className="paper-sources"><summary>开放全文与来源</summary><button className="secondary-button" disabled={finding} onClick={resolve}>{finding ? "正在查找开放链接…" : "查找开放全文"}</button>{error && <p role="alert" className="form-error">{error}</p>}{links && <><p className="muted">{links.message}</p>{links.links.map(l => <div className="oa-link" key={l.url}><div><a href={l.url} target="_blank" rel="noreferrer noopener">{l.source} · 打开来源 ↗</a><p className="muted">{l.license}</p></div>{editable && <button className="secondary-button" disabled={busy} onClick={() => act(() => api(root + "/papers/" + paper.id + "/remote-pdf", { method: "POST", data: { data: { url: l.url } } }))}>下载并解析开放 PDF</button>}</div>)}</>}{editable && <form className="collection-create" onSubmit={e => { e.preventDefault(); act(async () => { await api(root + "/papers/" + paper.id + "/remote-pdf", { method: "POST", data: { data: { url } } }); setURL(""); }); }}><label>可公开读取的 PDF 链接<input type="url" required value={url} onChange={e => setURL(e.target.value)} placeholder="https://..." /></label><button className="secondary-button" disabled={busy}>保存链接中的 PDF</button></form>}<p className="muted">文件取得后核对内容与所选文献是否一致；需要登录或无可读取全文时，使用本地上传。</p></details>;
}

function PaperOrganization({ root, paper, collections, editable, act, busy }) {
  const [draft, setDraft] = useState({ tags: (paper.data.tags || []).join("; "), collection_ids: paper.data.collection_ids || [] });
  useEffect(() => setDraft({ tags: (paper.data.tags || []).join("; "), collection_ids: paper.data.collection_ids || [] }), [paper.id, paper.revision]);
  const save = data => act(() => api(root + "/papers/" + paper.id + "/organization", { method: "PUT", data: { data, revision: paper.revision } }));
  return <div className="paper-organization">{!!paper.data.tags?.length && <div className="paper-project-tags">{paper.data.tags.map(t => <span key={t}>{t}</span>)}</div>}{editable ? <><div className="project-actions"><button className="text-action" disabled={busy} aria-pressed={Boolean(paper.data.bookmarked)} onClick={() => save({ bookmarked: !paper.data.bookmarked })}>{paper.data.bookmarked ? "已项目收藏" : "项目收藏"}</button><button className="text-action" disabled={busy} aria-pressed={Boolean(paper.data.read)} onClick={() => save({ read: !paper.data.read })}>{paper.data.read ? "已项目阅读" : "标记项目已阅"}</button></div><details><summary>整理标签与集合</summary><form onSubmit={e => { e.preventDefault(); save({ ...draft, tags: draft.tags.split(/[;；,，]/).map(v => v.trim()).filter(Boolean) }); }}><label>项目文献标签<input value={draft.tags} onChange={e => setDraft({ ...draft, tags: e.target.value })} placeholder="分号分隔" /></label><div className="paper-collections">{collections.map(c => <label key={c.id}><input type="checkbox" checked={draft.collection_ids.includes(c.id)} onChange={e => setDraft({ ...draft, collection_ids: e.target.checked ? [...draft.collection_ids, c.id] : draft.collection_ids.filter(id => id !== c.id) })} />{c.label}</label>)}</div><button className="secondary-button" disabled={busy}>保存文献整理</button></form></details></> : <p className="muted">{paper.data.bookmarked ? "项目收藏 · " : ""}{paper.data.read ? "项目已阅" : ""}{(paper.data.collection_ids || []).map(id => collections.find(c => c.id === id)?.label).filter(Boolean).join(" · ")}</p>}</div>;
}

function ProjectDashboard({ project, rows, editable, root, act, busy, onNavigate }) {
  const [editing, setEditing] = useState(false), [draft, setDraft] = useState({ title: project.title, query: project.query, description: project.description });
  const tasks = rows.filter(r => r.kind === "task"), recent = [...rows].sort((a, b) => b.updated_at - a.updated_at).slice(0, 6);
  const counts = [["paper", "项目文献", "knowledge"], ["document", "原文文档", "knowledge"], ["evidence", "研究证据", "evidence"], ["task", "研究任务", "agent"]];
  return <div className="project-dashboard"><div className="module-heading"><div><span className="workspace-label">当前课题</span><h2>研究，沿着证据展开</h2><p>{project.query || "写下研究问题，明确资料收集与分析的范围。"}</p></div>{editable && <button className="secondary-button" onClick={() => { setDraft({ title: project.title, query: project.query, description: project.description }); setEditing(!editing); }}>编辑项目</button>}</div>
    {editing && <form className="project-create" onSubmit={e => { e.preventDefault(); act(async () => { await api(root, { method: "PATCH", data: { revision: project.revision, data: draft } }); setEditing(false); }); }}><label>更新项目名称<input required maxLength={500} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} /></label><label>更新研究问题<textarea maxLength={10000} value={draft.query} onChange={e => setDraft({ ...draft, query: e.target.value })} /></label><label>更新项目说明<input maxLength={10000} value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} /></label><div className="project-actions"><button disabled={busy} className="primary-button">保存项目修改</button><button type="button" className="secondary-button" onClick={() => setEditing(false)}>取消</button></div></form>}
    <div className="dashboard-stats">{counts.map(([kind, label, tab]) => <button key={kind} onClick={() => onNavigate(tab)}><span>{label}</span><strong>{rows.filter(r => r.kind === kind).length}</strong></button>)}</div>
    <div className="dashboard-columns"><section><div className="project-toolbar"><h3>近期研究任务</h3><button className="text-action" onClick={() => onNavigate("agent")}>查看任务</button></div>{tasks.length ? tasks.slice(0, 4).map(t => <button className="dashboard-row" key={t.id} onClick={() => onNavigate("agent")}><strong>{t.label}</strong><span>{t.data.message}</span></button>) : <p className="muted">从项目资料开始证据整理、综述与报告任务。</p>}<div className="project-toolbar"><h3>当前待复核资料</h3></div>{rows.filter(r => r.data.stale).slice(0, 8).map(r => <p key={r.id}>{r.label} · 来源发生变化</p>)}{!rows.some(r => r.data.stale) && <p className="muted">当前没有因来源变化而标记的产物。</p>}</section><section><div className="project-toolbar"><h3>近期资料变化</h3><button className="text-action" onClick={() => onNavigate("activity")}>查看记录</button></div>{recent.map(r => <div className="dashboard-row" key={r.id}><strong>{r.label}</strong><time>{new Date(r.updated_at * 1000).toLocaleString()}</time></div>)}{!recent.length && <p className="muted">还没有资料。先加入文献，再上传原文与建立证据。</p>}</section></div>
  </div>;
}

function ProjectReview({ root, rows, editable, act, busy, onSource }) {
  const reviews = rows.filter(r => r.kind === "review");
  return <div className="project-review"><div className="module-heading"><div><span className="workspace-label">检查依据与覆盖范围</span><h2>把结论放回资料中核对</h2><p>检查来源、原文范围、研究者解释及稿件缺项。建议保留实际证据，供你回查。</p></div>{editable && <button className="primary-button" disabled={busy} onClick={() => act(() => api(root + "/review", { method: "POST" }))}>检查当前项目资料</button>}</div>{!reviews.length && <div className="platform-empty"><h3>还没有资料审查记录</h3><p>建立项目证据后，可检查出处与覆盖范围。</p></div>}{reviews.map(r => <article key={r.id} className="review-report"><span className="workspace-label">{new Date(r.created_at * 1000).toLocaleString()} · {r.data.stale ? "来源变化，待重查" : "已保存检查"}</span><h3>{r.label}</h3><p>{r.data.paper_count} 篇文献 · {r.data.evidence_count} 条证据</p><p className="muted">{r.data.boundary}</p>{r.data.findings.map((f, i) => <div className="review-finding" key={i}>{f.title && <strong>{f.title}</strong>}<p>{f.message}</p>{f.evidence_ids.map(id => { const c = r.data.checks.find(c => c.evidence_id === id); return c && <button className="text-action" key={id} onClick={() => onSource(c)}>核对原文：{c.quote.slice(0, 100)}</button>; })}{f.source_passages?.map((c, j) => <button className="text-action" key={"passage-" + j} onClick={() => onSource(c)}>回查原文：{c.quote.slice(0, 180)}</button>)}</div>)}{r.data.outputs.map(o => <div className="review-finding" key={o.id}><strong>{o.title}</strong><p>失效引用 {o.validation.invalid_citations} · 尚未逐项确认 {o.validation.unconfirmed_citations}</p>{o.validation.missing_sections?.length > 0 && <p>待补章节：{o.validation.missing_sections.join("、")}</p>}{o.validation.abstract_missing && <p>摘要尚未填写</p>}{o.validation.keywords_missing && <p>关键词尚未填写</p>}</div>)}</article>)}</div>;
}

function MemberPanel({ project, onError }) {
  const [members, setMembers] = useState([]),
    [username, setUsername] = useState(""),
    [role, setRole] = useState("viewer");
  const root = projectPath(project.id);
  const load = () => api(root + "/members").then((d) => setMembers(d.members));
  useEffect(() => {
    load().catch((e) => onError(e.message));
  }, [project.id]);
  return (
    <div className="member-panel">
      <h2>项目成员</h2>
      {members.map((m) => (
        <div className="member-row" key={m.username}>
          <strong>{m.username}</strong>
          <span>
            {m.role === "owner"
              ? "拥有者"
              : m.role === "editor"
                ? "编辑者"
                : "阅读者"}
          </span>
          {project.role === "owner" && m.role !== "owner" && (
            <button
              className="secondary-button"
              onClick={async () => {
                try {
                  await api(root + "/members", {
                    method: "PUT",
                    data: { username: m.username, role: "remove" },
                  });
                  await load();
                } catch (e) {
                  onError(e.message);
                }
              }}
            >
              移除
            </button>
          )}
        </div>
      ))}
      {project.role === "owner" && (
        <form
          className="member-form"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api(root + "/members", {
                method: "PUT",
                data: { username, role },
              });
              setUsername("");
              await load();
            } catch (e) {
              onError(e.message);
            }
          }}
        >
          <label className="visually-hidden">已注册的成员账号</label>
          <input
            aria-label="已注册的成员账号"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            placeholder="成员账号"
          />
          <select
            aria-label="成员角色"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            <option value="viewer">阅读者</option>
            <option value="editor">编辑者</option>
          </select>
          <button className="secondary-button">添加成员</button>
        </form>
      )}
      <p className="muted">
        阅读者只能查看；编辑者可更新研究资料；拥有者可管理成员与归档。
      </p>
    </div>
  );
}

function EvidenceLibrary({ root, papers, documents, evidence, editable, act, busy, onSource }) {
  const [draft, setDraft] = useState({
      paper_id: "",
      field: "finding",
      quote: "",
      value: "",
      confirmed: false,
    }),
    [editing, setEditing] = useState(null),
    [verify, setVerify] = useState({});
  const selected = papers.find((p) => p.id === draft.paper_id);
  const sourceText = draft.document_id ? documents.find(d => d.id === draft.document_id)?.data.pages.find(p => p.number === draft.page)?.text : draft.scope === "title" ? selected?.label : selected?.data.abstract;
  return (
    <>
      <div className="project-toolbar">
        <p>证据只接受能在指定原文中核对的片段；没有全文时标记摘要依据。</p>
        <button
          className="secondary-button"
          disabled={!evidence.length}
          onClick={() =>
            download("evidence.json", JSON.stringify(evidence, null, 2))
          }
        >
          导出证据
        </button>
      </div>
      {editable && (
        <form
          className="evidence-create"
          onSubmit={(e) => {
            e.preventDefault();
            act(async () => {
              await api(
                root + "/evidence" + (editing ? "/" + editing.id : ""),
                {
                  method: editing ? "PUT" : "POST",
                  data: {
                    data: { ...draft, value: draft.value || draft.quote },
                    revision: editing?.revision,
                  },
                },
              );
              setDraft({
                paper_id: "",
                field: "finding",
                quote: "",
                value: "",
                confirmed: false,
              });
              setEditing(null);
            });
          }}
        >
          <h2>{editing ? "修改并重新核对证据" : "建立一条摘要证据"}</h2>
          {editing?.data.scope === "fulltext" && <p className="muted">正在编辑原文第 {draft.page} 页的证据。</p>}
          <div className="evidence-fields">
            <label>
              文献
              <select
                required
                disabled={!!editing}
                value={draft.paper_id}
                onChange={(e) =>
                  setDraft({ ...draft, paper_id: e.target.value })
                }
              >
                <option value="">选择项目文献</option>
                {papers.map((p) => (
                  <option value={p.id} key={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              提取字段
              <input
                value={draft.field}
                onChange={(e) => setDraft({ ...draft, field: e.target.value })}
                required
              />
            </label>
          </div>
          {selected && (
            <blockquote className="source-preview">
              {sourceText ||
                "该文献没有摘要，请上传 PDF 后在阅读器摘录。"}
            </blockquote>
          )}
          <label>
            原文片段
            <textarea
              aria-label="证据原文片段"
              value={draft.quote}
              required
              onChange={(e) => setDraft({ ...draft, quote: e.target.value })}
              placeholder="从摘要复制原句；系统会核对来源"
            />
          </label>
          <label>
            提取值或解释
            <input
              value={draft.value}
              onChange={(e) => setDraft({ ...draft, value: e.target.value })}
              placeholder="留空使用原文片段；解释会单独标记"
            />
          </label>
          <label className="check-filter">
            <input
              type="checkbox"
              checked={draft.confirmed}
              onChange={(e) =>
                setDraft({ ...draft, confirmed: e.target.checked })
              }
            />
            我已核对这条证据
          </label>
          <div className="project-actions">
            <button className="primary-button" disabled={busy}>
              {editing ? "保存新版本" : "保存证据"}
            </button>
            {editing && (
              <button
                type="button"
                className="secondary-button"
                onClick={() => setEditing(null)}
              >
                取消修改
              </button>
            )}
          </div>
        </form>
      )}
      {evidence.map((e) => (
        <article className="evidence-row" key={e.id}>
          <div className="project-toolbar">
            <strong>{e.data.field}</strong>
            <span className="muted">
              {e.data.scope === "fulltext"
                ? `原文第 ${e.data.page} 页`
                : e.data.scope === "title"
                  ? "标题依据"
                  : "摘要依据"}{" "}
              · {e.data.confirmed_by ? "已人工确认" : "待人工确认"}
            </span>
          </div>
          <h3>{papers.find((p) => p.id === e.data.paper_id)?.label}</h3>
          <blockquote>{e.data.quote}</blockquote>
          <p>
            {e.data.value_status === "interpretation"
              ? "解释（需要研究者判断）："
              : "提取："}
            {e.data.value}
          </p>
          <div className="project-actions">
            <button className="secondary-button" onClick={() => onSource({ ...e.data, title: papers.find(p => p.id === e.data.paper_id)?.label })}>查看引用原文</button>
            <button
              className="secondary-button"
              onClick={() =>
                act(async () => {
                  const d = await api(root + "/evidence/" + e.id + "/verify");
                  setVerify({ ...verify, [e.id]: d.valid });
                })
              }
            >
              <Check size={14} />
              核对来源
            </button>
            {verify[e.id] !== undefined && (
              <span>
                {verify[e.id] ? "来源与片段一致" : "来源已变化，需重新核对"}
              </span>
            )}
            {editable && (
              <button
                className="secondary-button"
                onClick={() => {
                  setEditing(e);
                  setDraft({ ...e.data, confirmed: !!e.data.confirmed_by });
                }}
              >
                修改证据
              </button>
            )}
          </div>
        </article>
      ))}
      {!evidence.length && (
        <p className="platform-status">
          尚未建立证据。可从摘要摘录，或在 PDF 阅读器选择原文。
        </p>
      )}
    </>
  );
}

function ProjectActivity({ root }) {
  const [events, setEvents] = useState([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    api(root + "/events").then((d) => live && setEvents(d.events)).catch(e => live && setError(e.message));
    return () => { live = false; };
  }, [root]);
  const names = {
    "project.created": "建立项目",
    "project.updated": "更新项目",
    "paper.created": "加入文献",
    "paper.updated": "更新文献",
    "document.created": "上传原文",
    "evidence.created": "建立证据",
    "evidence.updated": "修改证据",
    "member.viewer": "添加阅读者",
    "member.editor": "添加编辑者",
    "member.remove": "移除成员",
  };
  return (
    <div className="activity-list">
      <h2>项目操作记录</h2>
      {error && <p role="alert" className="form-error">{error}</p>}
      {events.map((e) => (
        <div key={e.id}>
          <time>{new Date(e.created_at * 1000).toLocaleString("zh-CN")}</time>
          <strong>{names[e.action] || e.action}</strong>
          <span>{e.actor}</span>
        </div>
      ))}
    </div>
  );
}
