import React, { useState, useEffect, useRef } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import {
  MagnifyingGlass,
  ArrowUpRight,
  ArrowLeft,
  BookmarkSimple,
  Check,
  Quotes,
  Graph,
  FileText,
  NotePencil,
  Table,
  ListBullets,
  Code,
  ArrowsOutSimple,
  ArrowsInSimple,
  Highlighter,
  ClockCounterClockwise,
  Books,
  FolderSimple,
  ArrowRight,
  X,
  SlidersHorizontal,
} from "@phosphor-icons/react";
import { paperId, paperUrl, safeUrl, stored, persist } from "./api";
import { useApp } from "./context";
import { AddToProject } from "./project-workspace";

const methodRules = [
  ["Retrieval", /retriev(?:al|er|e)|检索/i],
  ["Graph learning", /graph neural|graph learning|图神经/i],
  ["Transformer", /transformer/i],
  ["Pretraining", /pre.?train|预训练/i],
  ["Diffusion", /diffusion|扩散模型/i],
  ["Reinforcement learning", /reinforcement learning|强化学习/i],
  ["Contrastive learning", /contrastive|对比学习/i],
  ["Survey", /survey|systematic review|综述/i],
];
const strings = (v) =>
  (Array.isArray(v) ? v : v ? [v] : [])
    .map((x) => (typeof x === "string" ? x : x?.name || x?.title || ""))
    .filter(Boolean);
export const methods = (p) => [
  ...new Set([
    ...strings(p.method_tags || p.methods),
    ...methodRules
      .filter(([, re]) => re.test(`${p.title} ${p.abstract || ""}`))
      .map(([label]) => label),
  ]),
];
export const datasets = (p) => strings(p.datasets || p.dataset);
export const codeUrl = (p) =>
  safeUrl(p.code_url || p.code_repository || p.repository_url) ||
  safeUrl(
    (p.abstract || "")
      .match(/https?:\/\/(?:github\.com|gitlab\.com)\/[^\s<>"{}]+/i)?.[0]
      ?.replace(/[.,;)]+$/, ""),
  );
export const citationCount = (p) => {
  const n = p.citation_count ?? p.citationCount ?? p.citations_count;
  return n !== null && n !== undefined && n !== "" && Number.isFinite(Number(n))
    ? Number(n)
    : null;
};
export const sourceMatches = (p, source) => {
  const aliases = {
    semantic_scholar: [
      "semantic_scholar",
      "semantic scholar",
      "s2",
      "semanticscholar",
    ],
    local: ["local", "本地", "local_index"],
  };
  const values = String(p.source || "")
    .toLowerCase()
    .split(/[,;/]+/)
    .map((x) => x.trim());
  return (
    !source || (aliases[source] || [source]).some((x) => values.includes(x))
  );
};
export function filterPapers(papers, filters) {
  return papers.filter(
    (p) =>
      sourceMatches(p, filters.source) &&
      (!filters.method || methods(p).includes(filters.method)) &&
      (!filters.code || !!codeUrl(p)) &&
      (!filters.citations ||
        (citationCount(p) !== null &&
          citationCount(p) >= Number(filters.citations))),
  );
}
export function FilterPanel({ filters, setFilters, availableMethods }) {
  const count = Object.values(filters).filter(Boolean).length;
  return (
    <div className="metadata-filters">
      <span className="filter-caption">
        <SlidersHorizontal size={15} />
        结果筛选
      </span>
      <label>
        <span className="visually-hidden">数据库</span>
        <select
          aria-label="数据库"
          value={filters.source}
          onChange={(e) => setFilters({ ...filters, source: e.target.value })}
        >
          <option value="">全部数据库</option>
          {[
            ["arxiv", "arXiv"],
            ["openalex", "OpenAlex"],
            ["crossref", "Crossref"],
            ["semantic_scholar", "Semantic Scholar"],
            ["europe_pmc", "Europe PMC"],
            ["scopus", "Scopus（授权）"],
            ["local", "本地索引"],
          ].map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </label>
      <select
        aria-label="方法类别"
        value={filters.method}
        onChange={(e) => setFilters({ ...filters, method: e.target.value })}
      >
        <option value="">所有方法</option>
        {availableMethods.map((m) => (
          <option key={m}>{m}</option>
        ))}
      </select>
      <select
        aria-label="最低引用次数"
        value={filters.citations}
        onChange={(e) => setFilters({ ...filters, citations: e.target.value })}
      >
        <option value="">引用次数不限</option>
        <option value="10">至少 10 次引用</option>
        <option value="100">至少 100 次引用</option>
        <option value="1000">至少 1,000 次引用</option>
      </select>
      <label className="check-filter">
        <input
          type="checkbox"
          checked={filters.code}
          onChange={(e) => setFilters({ ...filters, code: e.target.checked })}
        />
        <Code size={15} />
        有代码链接
      </label>
      {!!count && (
        <button
          className="reset-filters"
          onClick={() =>
            setFilters({ source: "", method: "", citations: "", code: false })
          }
        >
          <X size={13} />
          清除 {count} 项
        </button>
      )}
      <span className="filter-note">基于已返回元数据</span>
    </div>
  );
}
export function ResearchStart({
  examples,
  history,
  restore,
  setQuery,
  favorites,
  read,
  folders,
}) {
  const { setDialog } = useApp();
  return (
    <div className="start-workspace">
      <section className="start-main">
        <div className="section-bar">
          <span>
            <Books size={16} />
            研究工作区
          </span>
          <span>从一个明确的研究问题开始</span>
        </div>
        <div className="start-title">
          <span className="workspace-label">为研究者，重新整理知识</span>
          <h2>
            把研究问题，
            <br />
            <em>
              变成知识线索<span className="editorial-dot">.</span>
            </em>
          </h2>
          <p>检索方法、追溯证据，把值得阅读的论文归入你的课题。</p>
        </div>
        <div className="search-guidance">
          <span>研究问题</span>
          <p>研究对象 + 方法或任务 + 明确约束</p>
          <span>例如</span>
          <p>分子性质预测中，哪些图神经网络预训练方法适用于小样本数据？</p>
        </div>
        <section className="suggestions">
          <h3>探索一个研究方向</h3>
          {examples.map((e) => (
            <button
              className="suggestion"
              key={e.query}
              onClick={() => {
                setQuery(e.query);
                document.getElementById("query-input")?.focus();
              }}
            >
              <MagnifyingGlass size={17} />
              <span>
                <strong>{e.title}</strong>
                <small>{e.query}</small>
              </span>
              <ArrowUpRight size={16} />
            </button>
          ))}
        </section>
        <section className="recent-search">
          <div className="section-title">
            <h3>继续最近的研究</h3>
            <span>{history.length} 条检索记录</span>
          </div>
          {history.length ? (
            history.slice(0, 4).map((h, i) => (
              <button key={i} onClick={() => restore(h)}>
                <ClockCounterClockwise size={16} />
                <span>{h.query}</span>
                <small>{h.result?.papers?.length ?? ""}</small>
                <ArrowRight size={14} />
              </button>
            ))
          ) : (
            <p className="subtle-empty">
              完成检索后，可在这里恢复结果和阅读上下文。
            </p>
          )}
        </section>
        <div className="start-foot">
          <kbd>⌘ / Ctrl K</kbd>
          <span>快捷检索</span>
          <kbd>↑ ↓</kbd>
          <span>浏览结果</span>
          <kbd>Enter</kbd>
          <span>打开阅读器</span>
        </div>
      </section>
      <aside className="start-context">
        <div className="section-bar">
          <span>
            <Graph size={16} />
            知识上下文
          </span>
        </div>
        <figure className="workspace-art">
          <img
            src="/static/brand/research-collage.jpg"
            alt="书页、雕塑与树木构成知识生长的意象"
            width="1536"
            height="1024"
          />
          <figcaption>知识的生长 / 研索</figcaption>
        </figure>
        <section>
          <h3>你的研究资料</h3>
          <dl className="workspace-stats">
            <div>
              <dt>收藏文献</dt>
              <dd>{favorites.length}</dd>
            </div>
            <div>
              <dt>已阅文献</dt>
              <dd>{read.size}</dd>
            </div>
            <div>
              <dt>课题文件夹</dt>
              <dd>{folders.length}</dd>
            </div>
          </dl>
        </section>
        <section>
          <h3>从文献到知识</h3>
          <div className="workflow-step">
            <FileText size={18} />
            <div>
              <strong>阅读与核对</strong>
              <p>摘要、研究用途与可追溯的原文片段。</p>
            </div>
          </div>
          <div className="workflow-step">
            <Graph size={18} />
            <div>
              <strong>发现研究联系</strong>
              <p>探索关联文献、概念与发表时间分布。</p>
            </div>
          </div>
          <div className="workflow-step">
            <NotePencil size={18} />
            <div>
              <strong>积累阅读笔记</strong>
              <p>记录摘录、方法与下一步研究问题。</p>
            </div>
          </div>
        </section>
        <section>
          <h3>已有文献资料？</h3>
          <p>导入 BibTeX、RIS、CSV 或 JSON，继续整理你的文献库。</p>
          <button
            className="secondary-button"
            onClick={() => setDialog("import")}
          >
            <FolderSimple size={15} />
            导入文献资料
          </button>
        </section>
        <div className="context-foot">所有研究判断，请回到原文核对。</div>
      </aside>
    </div>
  );
}

function getEdges(papers, relationships, type) {
  const ids = new Map();
  papers.forEach((p, i) =>
    [
      paperId(p),
      p.id,
      p.doi,
      p.arxiv_id,
      p.s2_corpus_id,
      p.title,
      ...(p.ids || []),
    ]
      .filter(Boolean)
      .forEach((id) => ids.set(String(id), i)),
  );
  return relationships
    .map((e) => ({
      ...e,
      a: ids.get(String(e.src)),
      b: ids.get(String(e.dst)),
    }))
    .filter(
      (e) =>
        e.a !== undefined &&
        e.b !== undefined &&
        e.a !== e.b &&
        (type === "cite"
          ? ["cite", "citation", "cites", "co-cite"].includes(e.relation)
          : !["cite", "citation", "cites", "co-cite"].includes(e.relation)),
    );
}
function RelationGraph({ papers, relationships, selected, onSelect }) {
  const [type, setType] = useState("similar");
  const edges = getEdges(papers, relationships, type);
  const connected = [...new Set(edges.flatMap((e) => [e.a, e.b]))].slice(0, 12);
  const positions = new Map(
    connected.map((idx, i) => [
      idx,
      {
        x:
          150 +
          Math.cos((2 * Math.PI * i) / connected.length - Math.PI / 2) * 103,
        y:
          116 +
          Math.sin((2 * Math.PI * i) / connected.length - Math.PI / 2) * 78,
      },
    ]),
  );
  return (
    <section className="context-section">
      <div className="section-title">
        <h3>文献关系</h3>
        <div className="mini-switch">
          <button
            className={type === "similar" ? "active" : ""}
            onClick={() => setType("similar")}
          >
            关联
          </button>
          <button
            className={type === "cite" ? "active" : ""}
            onClick={() => setType("cite")}
          >
            引文
          </button>
        </div>
      </div>
      {connected.length ? (
        <>
          <svg
            className="relation-graph"
            viewBox="0 0 300 230"
            role="group"
            aria-label={
              type === "cite"
                ? "检索结果中的引文关系图"
                : "检索结果中的文献关联图"
            }
          >
            <defs>
              <marker
                id="citation-arrow"
                viewBox="0 0 10 10"
                refX="19"
                refY="5"
                markerWidth="5"
                markerHeight="5"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
              </marker>
            </defs>
            {edges
              .filter((e) => positions.has(e.a) && positions.has(e.b))
              .map((e, i) => (
                <line
                  key={i}
                  x1={positions.get(e.a).x}
                  y1={positions.get(e.a).y}
                  x2={positions.get(e.b).x}
                  y2={positions.get(e.b).y}
                  markerEnd={
                    type === "cite" && e.relation !== "co-cite"
                      ? "url(#citation-arrow)"
                      : undefined
                  }
                  className={e.relation === "author" ? "author-edge" : ""}
                />
              ))}
            {connected.map((idx) => {
              const pos = positions.get(idx);
              return (
                <g
                  key={idx}
                  role="button"
                  tabIndex={0}
                  aria-label={papers[idx].title}
                  className={
                    paperId(papers[idx]) === paperId(selected)
                      ? "graph-node selected"
                      : "graph-node"
                  }
                  onClick={() => onSelect(idx)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(idx);
                    }
                  }}
                >
                  <title>{papers[idx].title}</title>
                  <circle cx={pos.x} cy={pos.y} r={10} />
                  <text x={pos.x} y={pos.y + 3}>
                    {idx + 1}
                  </text>
                  <text className="graph-year" x={pos.x} y={pos.y + 24}>
                    {papers[idx].year || ""}
                  </text>
                </g>
              );
            })}
          </svg>
          <p className="chart-caption">
            {type === "cite"
              ? "仅显示返回数据中的引文关系。"
              : "实线为文本关联，虚线为共同作者。节点编号对应文献列表。"}
          </p>
        </>
      ) : (
        <div className="graph-empty">
          <Graph size={27} />
          <p>
            {type === "cite"
              ? "当前结果未提供引文关系"
              : "当前结果未提供文献关联"}
          </p>
          <small>
            {type === "cite"
              ? "相似文献不代表引用关系。"
              : "选择下方概念，继续聚焦研究主题。"}
          </small>
        </div>
      )}
    </section>
  );
}
function Timeline({ papers }) {
  const counts = new Map();
  papers.forEach((p) => {
    const y = Number(p.year);
    if (y > 1400 && y <= 2100) counts.set(y, (counts.get(y) || 0) + 1);
  });
  const years = [...counts.keys()].sort((a, b) => a - b);
  const max = Math.max(1, ...counts.values());
  return (
    <section className="context-section">
      <div className="section-title">
        <h3>发表时间分布</h3>
        <span>
          {years.length ? `${years[0]}-${years.at(-1)}` : "年份未提供"}
        </span>
      </div>
      {years.length ? (
        <>
          <svg
            className="timeline-chart"
            viewBox="0 0 300 116"
            role="img"
            aria-label={years
              .map((y) => `${y} 年 ${counts.get(y)} 篇`)
              .join("，")}
          >
            <line x1="18" y1="88" x2="282" y2="88" />
            {years.map((y, i) => {
              const x =
                26 +
                (years.length === 1 ? 120 : (i * 248) / (years.length - 1));
              const h = (counts.get(y) / max) * 62;
              return (
                <g key={y}>
                  <title>
                    {y} 年：{counts.get(y)} 篇
                  </title>
                  <line
                    className="timeline-stem"
                    x1={x}
                    x2={x}
                    y1={88 - h}
                    y2="87"
                  />
                  <circle cx={x} cy={88 - h} r="3" />
                  <text x={x} y="108">
                    {years.length <= 7 || i === 0 || i === years.length - 1
                      ? y
                      : ""}
                  </text>
                </g>
              );
            })}
          </svg>
          <p className="chart-caption">
            当前 {papers.length} 篇结果的发表分布，不代表全领域趋势。
          </p>
        </>
      ) : (
        <p className="subtle-empty">文献包含年份时显示时间分布。</p>
      )}
    </section>
  );
}
function KnowledgeContext({
  papers,
  selected,
  relationships,
  onSelect,
  onMethod,
}) {
  const concepts = [...new Set(papers.flatMap(methods))].slice(0, 8);
  const selectedMethods = new Set(methods(selected));
  const edges = getEdges(papers, relationships, "similar");
  const similar = papers
    .map((p, i) => ({
      p,
      i,
      overlap: methods(p).filter((m) => selectedMethods.has(m)).length,
      linked: edges.some(
        (e) =>
          (papers[e.a] === selected && e.b === i) ||
          (papers[e.b] === selected && e.a === i),
      ),
    }))
    .filter((x) => x.p !== selected && (x.linked || x.overlap))
    .sort(
      (a, b) => Number(b.linked) - Number(a.linked) || b.overlap - a.overlap,
    )
    .slice(0, 4);
  return (
    <div className="knowledge-content">
      <RelationGraph {...{ papers, relationships, selected, onSelect }} />
      <section className="context-section">
        <div className="section-title">
          <h3>研究概念</h3>
          <span>标题 / 摘要</span>
        </div>
        <ConceptMap papers={papers} />
        <div className="concept-list">
          {concepts.map((m) => (
            <button key={m} onClick={() => onMethod?.(m)}>
              {m}
              <span>{papers.filter((p) => methods(p).includes(m)).length}</span>
            </button>
          ))}
        </div>
        {!concepts.length && (
          <p className="subtle-empty">当前文本尚未识别到方法类别。</p>
        )}
      </section>
      <Timeline papers={papers} />
      <section className="context-section">
        <h3>相关文献</h3>
        {similar.length ? (
          similar.map(({ p, i, linked }) => (
            <button
              className="related-paper"
              key={paperId(p)}
              onClick={() => onSelect(i)}
            >
              <span>{String(i + 1).padStart(2, "0")}</span>
              <div>
                <strong>{p.title}</strong>
                <small>
                  {p.year || "年份未提供"} /{" "}
                  {linked ? "返回数据中的关联" : "共享方法词"}
                </small>
              </div>
              <ArrowUpRight size={14} />
            </button>
          ))
        ) : (
          <p className="subtle-empty">当前结果没有可核对的关联文献。</p>
        )}
      </section>
    </div>
  );
}
function ReadingNotes({ paper }) {
  const { uid, notify } = useApp();
  const key = `scholarscope_notes:${uid}:${paperId(paper)}`;
  const [entry, setEntry] = useState(() =>
    stored(key, { text: "", tags: "", excerpts: [], progress: "unread" }),
  );
  useEffect(() => {
    const sync = (e) => {
      if (e.key === key)
        setEntry(
          stored(key, { text: "", tags: "", excerpts: [], progress: "unread" }),
        );
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, [key]);
  const update = (patch) => {
    const next = { ...entry, ...patch };
    setEntry(next);
    persist(key, next);
    if (patch.tags !== undefined) {
      const tagKey = `scholarscope_tags:${uid}`;
      const index = stored(tagKey, {});
      index[paperId(paper)] = [
        ...new Set(
          next.tags
            .split(/[,，]/)
            .map((t) => t.trim())
            .filter(Boolean),
        ),
      ];
      persist(tagKey, index);
      window.dispatchEvent(new CustomEvent("scholarscope-notes"));
    }
  };
  const addExcerpt = () => {
    const text = window.getSelection()?.toString().trim();
    if (!text || !(paper.abstract || "").includes(text)) {
      notify("先在摘要中选择需要保存的原文片段");
      return;
    }
    if (!entry.excerpts.includes(text))
      update({ excerpts: [...entry.excerpts, text] });
    notify("摘录已保存到本机笔记");
  };
  return (
    <section className="reading-notes">
      <div className="section-title">
        <h3>阅读笔记</h3>
        <span>本机自动保存</span>
      </div>
      <label className="note-progress">
        阅读进度
        <select
          aria-label="阅读进度"
          value={entry.progress}
          onChange={(e) => update({ progress: e.target.value })}
        >
          <option value="unread">待阅读</option>
          <option value="reading">阅读中</option>
          <option value="reviewed">已梳理</option>
        </select>
      </label>
      <textarea
        aria-label="阅读笔记"
        value={entry.text}
        onChange={(e) => update({ text: e.target.value })}
        placeholder="记录方法、局限与值得追问的问题…"
        rows={5}
      />
      <input
        aria-label="笔记标签"
        value={entry.tags}
        onChange={(e) => update({ tags: e.target.value })}
        placeholder="标签，用逗号分隔"
      />
      <button className="secondary-button" onClick={addExcerpt}>
        <Highlighter size={15} />
        保存选中摘要
      </button>
      {entry.excerpts.map((text, i) => (
        <div className="saved-excerpt" key={i}>
          <blockquote>{text}</blockquote>
          <button
            className="plain-icon"
            aria-label={`删除摘录 ${i + 1}`}
            onClick={() =>
              update({ excerpts: entry.excerpts.filter((_, j) => i !== j) })
            }
          >
            <X size={14} />
          </button>
        </div>
      ))}
      <p className="chart-caption">
        笔记按账号保存在当前浏览器，不随文献导出。
      </p>
    </section>
  );
}
function EvidenceDetails({ paper }) {
  const sentences =
    (paper.abstract || "").match(/[^.!?。！？]+[.!?。！？]?/g) || [];
  const method = sentences
    .filter((s) =>
      /propos|introduc|method|model|framework|algorithm|方法|模型|算法|提出/i.test(
        s,
      ),
    )
    .slice(0, 2);
  const contribution = sentences
    .filter((s) =>
      /outperform|improv|demonstrat|contribut|results|提升|结果|贡献/i.test(s),
    )
    .slice(0, 2);
  return (
    <details className="evidence-details">
      <summary>
        研究要点与方法 <span>摘要摘录</span>
      </summary>
      {[
        ["贡献与结果", contribution],
        ["方法与算法", method],
      ].map(([title, content]) => (
        <section key={title}>
          <h3>{title}</h3>
          {content.length ? (
            content.map((s, i) => <blockquote key={i}>{s.trim()}</blockquote>)
          ) : (
            <p className="subtle-empty">
              摘要未明确提供相关信息，请阅读原文核对。
            </p>
          )}
        </section>
      ))}
      <section>
        <h3>数据集</h3>
        <p>{datasets(paper).join(" / ") || "检索元数据未提供数据集信息。"}</p>
      </section>
    </details>
  );
}
export function PaperWorkspace({
  papers,
  selected,
  active,
  setActive,
  mobileReader,
  setMobileReader,
  read,
  favorites,
  toggleFav,
  toggleRead,
  runAction,
  copyCitation,
  folders,
  movePaper,
  library,
  relationships = [],
  onMethod,
  standalone = false,
}) {
  const { uid } = useApp();
  const [tab, setTab] = useState("detail"),
    [expanded, setExpanded] = useState(standalone),
    [listMode, setListMode] = useState("list");
  const listRef = useRef(null);
  const favIds = new Set(favorites.map(paperId));
  const select = (i) => {
    setActive(i);
    setMobileReader(true);
  };
  useEffect(() => {
    const selectedRow = listRef.current?.querySelector(".selected");
    selectedRow?.scrollIntoView({ block: "nearest" });
    if (
      listRef.current?.contains(document.activeElement) &&
      document.activeElement.classList.contains("paper-select")
    )
      selectedRow
        ?.querySelector(".paper-select")
        ?.focus({ preventScroll: true });
  }, [active]);
  const onKeys = (e) => {
    if (
      e.target.closest("input,textarea,select") ||
      e.metaKey ||
      e.ctrlKey ||
      e.altKey
    )
      return;
    if (["ArrowDown", "ArrowUp"].includes(e.key)) {
      e.preventDefault();
      setActive(
        Math.max(
          0,
          Math.min(
            papers.length - 1,
            active + (e.key === "ArrowDown" ? 1 : -1),
          ),
        ),
      );
    }
    if (e.key === "Enter" && e.target === listRef.current) {
      e.preventDefault();
      setMobileReader(true);
      setTab("detail");
    }
  };
  const p = selected;
  return (
    <div
      className={`paper-workspace ${mobileReader ? "reader-open" : ""} ${expanded ? "reading-expanded" : ""}`}
    >
      <div
        className="paper-list"
        id="result-list"
        ref={listRef}
        tabIndex={0}
        onKeyDown={onKeys}
        aria-label="文献列表，使用上下方向键浏览"
      >
        <div className="section-bar">
          <span>文献 / {papers.length}</span>
          <div className="result-view-switch">
            <button
              aria-label="文献列表视图"
              aria-pressed={listMode === "list"}
              onClick={() => setListMode("list")}
            >
              <ListBullets size={14} />
              列表
            </button>
            <button
              aria-label="方法对比视图"
              aria-pressed={listMode === "compare"}
              onClick={() => setListMode("compare")}
            >
              <Table size={14} />
              方法对比
            </button>
          </div>
        </div>
        {listMode === "compare" ? (
          <MethodComparison
            {...{
              papers,
              onSelect: (i) => {
                select(i);
                setTab("detail");
              },
            }}
          />
        ) : (
          papers.map((p, i) => (
            <article
              key={paperId(p) + "-" + i}
              className={`paper-item paper-card ${i === Math.min(active, papers.length - 1) ? "selected" : ""}`}
            >
              <div className="paper-row-index">
                {String(i + 1).padStart(2, "0")}
              </div>
              <div className="paper-row-body">
                <button
                  className="paper-select"
                  onClick={() => {
                    select(i);
                    setTab("detail");
                  }}
                  aria-pressed={i === Math.min(active, papers.length - 1)}
                >
                  <div className="paper-meta">
                    <span>{p.venue || "来源未提供"}</span>
                    <span>{p.year || "年份未提供"}</span>
                    {read.has(paperId(p)) && (
                      <span className="read-badge">
                        <Check size={12} />
                        已阅
                      </span>
                    )}
                  </div>
                  <h3 className="paper-title">{p.title}</h3>
                  <p className="paper-authors">
                    {(p.authors || []).slice(0, 3).join(", ")}
                    {(p.authors || []).length > 3 ? " et al." : ""}
                  </p>
                  <p className="paper-snippet">
                    {p.abstract || "摘要暂缺，请打开原文继续核对。"}
                  </p>
                </button>
                <div className="paper-tags">
                  {methods(p)
                    .slice(0, 3)
                    .map((m) => (
                      <button key={m} onClick={() => onMethod?.(m)}>
                        {m}
                      </button>
                    ))}
                  {datasets(p)
                    .slice(0, 1)
                    .map((d) => (
                      <span key={d}>{d}</span>
                    ))}
                  {codeUrl(p) && (
                    <a href={codeUrl(p)} target="_blank" rel="noreferrer">
                      <Code size={12} />
                      Code
                      <ArrowUpRight size={11} />
                    </a>
                  )}
                </div>
                {p.recommendation_reason && (
                  <p className="paper-purpose">
                    <span>研究用途</span>
                    {p.recommendation_reason}
                  </p>
                )}
                {p.scope_notes?.map((note,i) => <p className="muted" key={i}>{note}</p>)}
                <div className="paper-item-actions">
                  <span className="citation-meta">
                    <Quotes size={13} />
                    {citationCount(p) !== null
                      ? `${citationCount(p).toLocaleString()} 次引用`
                      : "引用量未提供"}
                  </span>
                  <span className="paper-source">{p.source || ""}</span>
                  <button
                    className={
                      "plain-icon " +
                      (favIds.has(paperId(p)) ? "is-active" : "")
                    }
                    aria-label={favIds.has(paperId(p)) ? "取消收藏" : "收藏"}
                    onClick={() => runAction(() => toggleFav(p))}
                  >
                    <BookmarkSimple
                      size={16}
                      weight={favIds.has(paperId(p)) ? "fill" : "regular"}
                    />
                  </button>
                  <button
                    className={
                      "plain-icon " + (read.has(paperId(p)) ? "is-active" : "")
                    }
                    aria-label={read.has(paperId(p)) ? "取消已阅" : "已阅"}
                    onClick={() => runAction(() => toggleRead(p))}
                  >
                    <Check size={16} />
                  </button>
                </div>
              </div>
            </article>
          ))
        )}
      </div>
      {p && (
        <aside className="paper-reader" aria-label="文献阅读面板">
          <div className="reader-top">
            <button
              className="back-to-list"
              onClick={() => setMobileReader(false)}
            >
              <ArrowLeft size={16} />
              返回列表
            </button>
            <span>阅读与知识上下文</span>
            <div className="reader-window-tools">
              <a
                className="plain-icon"
                aria-label="独立阅读窗口"
                title="独立阅读窗口"
                href={"/app?reading=" + encodeURIComponent(paperId(p))}
                target="_blank"
                rel="noreferrer"
                onClick={() =>
                  persist(`scholarscope_reader:${uid}:${paperId(p)}`, p)
                }
              >
                <ArrowUpRight size={16} />
              </a>
              <button
                className="plain-icon expand-reader"
                aria-label={expanded ? "收起阅读器" : "展开阅读器"}
                onClick={() => setExpanded(!expanded)}
              >
                {expanded ? (
                  <ArrowsInSimple size={16} />
                ) : (
                  <ArrowsOutSimple size={16} />
                )}
              </button>
            </div>
          </div>
          <Tabs.Root value={tab} onValueChange={setTab}>
            <Tabs.List className="context-tabs" aria-label="阅读面板视图">
              <Tabs.Trigger value="detail">
                <FileText size={15} />
                文献详情
              </Tabs.Trigger>
              <Tabs.Trigger value="context">
                <Graph size={15} />
                知识上下文
              </Tabs.Trigger>
            </Tabs.List>
            <Tabs.Content value="detail" className="reader-content">
              <div className="reader-meta">
                <span>{p.venue || "文献"}</span>
                {p.year || ""}
              </div>
              <h2>{p.title}</h2>
              <p className="reader-authors">{(p.authors || []).join(", ")}</p>
              <div className="reader-buttons">
                <AddToProject paper={p} />
                <button
                  className={
                    "secondary-button " +
                    (favIds.has(paperId(p)) ? "is-active" : "")
                  }
                  onClick={() => runAction(() => toggleFav(p))}
                >
                  <BookmarkSimple
                    size={15}
                    weight={favIds.has(paperId(p)) ? "fill" : "regular"}
                  />
                  {favIds.has(paperId(p)) ? "已收藏" : "收藏"}
                </button>
                <button
                  className={
                    "secondary-button " +
                    (read.has(paperId(p)) ? "is-active" : "")
                  }
                  onClick={() => runAction(() => toggleRead(p))}
                >
                  <Check size={15} />
                  {read.has(paperId(p)) ? "已阅" : "标记已阅"}
                </button>
                <button
                  className="secondary-button"
                  onClick={() => copyCitation(p)}
                >
                  <Quotes size={15} />
                  引用
                </button>
              </div>
              {p.recommendation_reason && (
                <section className="reader-reason paper-reason">
                  <h3>与查询的关联</h3>
                  <p>{p.recommendation_reason}</p>
                  {p.evidence && <blockquote>{p.evidence}</blockquote>}
                </section>
              )}
              <section className="reader-abstract">
                {p.scope_notes?.map((note,i) => <p className="muted" key={i}>{note}</p>)}
                <div className="section-title">
                  <h3>摘要</h3>
                  <span>Abstract</span>
                </div>
                <p className="paper-abstract">
                  {p.abstract ||
                    "暂未获取到摘要。当前判断基于标题，请打开原文核对。"}
                </p>
              </section>
              {p.evidence_level === "title" && (
                <p className="evidence-note">当前推荐依据为标题，证据有限。</p>
              )}
              <EvidenceDetails paper={p} />
              <div className="reader-identifiers">
                {p.doi && (
                  <div>
                    <span>DOI</span>
                    <a
                      href={"https://doi.org/" + encodeURI(p.doi)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {p.doi}
                    </a>
                  </div>
                )}
                {p.arxiv_id && (
                  <div>
                    <span>arXiv</span>
                    <span>{p.arxiv_id}</span>
                  </div>
                )}
                {p.source && (
                  <div>
                    <span>来源</span>
                    <span>{p.source}</span>
                  </div>
                )}
                {codeUrl(p) && (
                  <div>
                    <span>代码</span>
                    <a href={codeUrl(p)} target="_blank" rel="noreferrer">
                      {codeUrl(p)}
                      <ArrowUpRight size={12} />
                    </a>
                  </div>
                )}
              </div>
              {library && (
                <label className="move-field">
                  所在文件夹
                  <select
                    aria-label="移动文献到文件夹"
                    value={p.folder_id || ""}
                    onChange={(e) =>
                      runAction(() => movePaper(p, e.target.value))
                    }
                  >
                    <option value="">未分类</option>
                    {folders.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {paperUrl(p) && (
                <a
                  className="original-link"
                  href={paperUrl(p)}
                  target="_blank"
                  rel="noreferrer"
                >
                  阅读原文
                  <ArrowUpRight size={16} />
                </a>
              )}
              <ReadingNotes key={uid + ":" + paperId(p)} paper={p} />
            </Tabs.Content>
            <Tabs.Content value="context">
              <KnowledgeContext
                {...{
                  papers,
                  selected,
                  relationships,
                  onSelect: select,
                  onMethod,
                }}
              />
            </Tabs.Content>
          </Tabs.Root>
        </aside>
      )}
    </div>
  );
}

function ConceptMap({ papers }) {
  const categories = [...new Set(papers.flatMap(methods))].slice(0, 4);
  const nodes = papers
    .map((p, i) => ({ p, i }))
    .filter(({ p }) => methods(p).some((m) => categories.includes(m)))
    .slice(0, 8);
  if (!categories.length || !nodes.length) return null;
  const h = Math.max(categories.length, nodes.length) * 23 + 20;
  return (
    <svg
      className="concept-map"
      viewBox={`0 0 300 ${h}`}
      role="img"
      aria-label="方法概念与文献对应图"
    >
      <title>连线表示论文标题或摘要包含该方法词，右侧数字为列表编号。</title>
      {categories.flatMap((m, j) =>
        nodes
          .filter(({ p }) => methods(p).includes(m))
          .map(({ i }) => (
            <line
              key={m + i}
              x1="146"
              y1={20 + j * 23}
              x2="265"
              y2={20 + nodes.findIndex((n) => n.i === i) * 23}
            />
          )),
      )}
      {categories.map((m, j) => (
        <g key={m}>
          <text x="0" y={23 + j * 23}>
            {m.length > 24 ? m.slice(0, 23) + "…" : m}
          </text>
          <circle cx="146" cy={20 + j * 23} r="3" />
        </g>
      ))}
      {nodes.map(({ p, i }, j) => (
        <g key={i}>
          <title>{p.title}</title>
          <circle cx="265" cy={20 + j * 23} r="3" />
          <text x="278" y={23 + j * 23}>
            {String(i + 1).padStart(2, "0")}
          </text>
        </g>
      ))}
    </svg>
  );
}
function MethodComparison({ papers, onSelect }) {
  return (
    <div className="method-comparison">
      <p>方法类别来自标题与摘要。数据集、代码仅在元数据提供时展示。</p>
      <div className="comparison-scroll">
        <table>
          <thead>
            <tr>
              <th>文献</th>
              <th>方法</th>
              <th>数据集 / 代码</th>
            </tr>
          </thead>
          <tbody>
            {papers.map((p, i) => (
              <tr key={paperId(p)}>
                <td>
                  <button onClick={() => onSelect(i)}>
                    <small>
                      {String(i + 1).padStart(2, "0")} /{" "}
                      {p.year || "年份未提供"}
                    </small>
                    <strong>{p.title}</strong>
                  </button>
                </td>
                <td>
                  {methods(p).length
                    ? methods(p).map((m) => <span key={m}>{m}</span>)
                    : "未提供"}
                </td>
                <td>
                  {datasets(p).join(" / ") || "数据集未提供"}
                  {codeUrl(p) && (
                    <a href={codeUrl(p)} target="_blank" rel="noreferrer">
                      <Code size={13} />
                      代码仓库
                      <ArrowUpRight size={12} />
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
