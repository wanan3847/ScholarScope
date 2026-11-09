import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { MotionConfig, motion, AnimatePresence } from "motion/react";
import {
  IconContext,
  ArrowRight,
  MagnifyingGlass,
  Books,
  ClockCounterClockwise,
  FolderSimple,
  Plus,
  Gear,
  Sun,
  Moon,
  BookOpen,
  UploadSimple,
  DownloadSimple,
  BookmarkSimple,
  Check,
  X,
  SlidersHorizontal,
  WarningCircle,
  Trash,
  Tag,
  PushPin,
} from "@phosphor-icons/react";
import "./style.css";
import "./atelier.css";
import ProjectWorkspace from "./project-workspace";
import {
  api,
  stored,
  storedText,
  persist,
  paperId,
  paperUrl,
  citation,
  download,
  csv,
  ris,
} from "./api";
import { AppContext } from "./context";
import { AppDialogs } from "./panels";
import {
  PaperWorkspace,
  ResearchStart,
  FilterPanel,
  filterPapers,
  methods,
} from "./research";

const examples = [
  {
    kind: "方法与应用",
    query: "graph neural network pretraining for molecular property prediction",
    title: "图神经网络预训练，如何改善分子性质预测？",
  },
  {
    kind: "研究综述",
    query: "retrieval augmented generation survey",
    title: "检索增强生成的主要方法与研究进展",
  },
];
const readingId = new URLSearchParams(location.search).get("reading");
const readerOwner = storedText("sakura_token")
  ? storedText("sakura_user")
  : "web-anonymous";
const readingPaper = readingId
  ? stored(`scholarscope_reader:${readerOwner}:${readingId}`, null)
  : null;
const loadHistory = () =>
  stored("sakura_history", [])
    .map((h) => ({
      ...h,
      result: h.result || h._cached_result,
      time: h.time || h.timestamp || Date.now(),
    }))
    .reverse();
function App() {
  const [view, setView] = useState(
    location.hash === "#favorites"
      ? "library"
      : location.hash === "#history"
        ? "history"
        : location.hash === "#projects"
          ? "projects"
          : "search",
  );
  const [dialog, setDialog] = useState(
    ["#model", "#settings", "#docs", "#import", "#login"].includes(
      location.hash,
    )
      ? location.hash === "#login"
        ? "auth"
        : location.hash.slice(1)
      : "",
  );
  const [token, setToken] = useState(storedText("sakura_token"));
  const [user, setUser] = useState(
    storedText("sakura_token") ? storedText("sakura_user") : "",
  );
  const [theme, setTheme] = useState(
    document.documentElement.dataset.theme || "light",
  );
  const [favorites, setFavorites] = useState([]),
    [read, setRead] = useState(new Set()),
    [folders, setFolders] = useState([]),
    [defaultFolder, setDefaultFolder] = useState("");
  const [models, setModels] = useState([]),
    [model, setModel] = useState(storedText("sakura_llm"));
  const [history, setHistory] = useState(loadHistory);
  const [folder, setFolder] = useState(""),
    [query, setQuery] = useState(
      new URLSearchParams(location.search).get("q") || "",
    );
  const [yearFrom, setYearFrom] = useState(""),
    [yearTo, setYearTo] = useState(""),
    [result, setResult] = useState(
      readingPaper ? { papers: [readingPaper], relationships: [] } : null,
    ),
    [resultQuery, setResultQuery] = useState(""),
    [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false),
    [elapsed, setElapsed] = useState(0),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [dataError, setDataError] = useState("");
  const [libraryQuery, setLibraryQuery] = useState(""),
    [readFilter, setReadFilter] = useState(false),
    [mobileReader, setMobileReader] = useState(false);
  const [filters, updateFilters] = useState({
    source: "",
    method: "",
    citations: "",
    code: false,
  });
  const setFilters = (next) => {
    updateFilters(next);
    setActive(0);
    setMobileReader(false);
  };
  const [advanced, setAdvanced] = useState(false);
  const [savedSearches, setSavedSearches] = useState([]);
  const [noteTags, setNoteTags] = useState({});
  const [tagFilter, setTagFilter] = useState("");
  const controller = useRef(null),
    noticeTimer = useRef(null),
    initialized = useRef(false);
  const uid = user || "web-anonymous";
  const [projectSelection, setProjectSelection] = useState({
    owner: readerOwner,
    id: storedText("scholarscope_project:" + readerOwner),
  });
  const projectId = projectSelection.owner === uid ? projectSelection.id : "";
  const setProjectId = (id) => {
    setProjectSelection({ owner: uid, id });
    try {
      localStorage.setItem("scholarscope_project:" + uid, id);
    } catch {}
  };
  const notify = (msg) => {
    setNotice(msg);
    clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(""), 3200);
  };
  const runAction = async (fn) => {
    try {
      return await fn();
    } catch (e) {
      notify(e.message);
      return undefined;
    }
  };
  const reloadModels = async () => {
    const d = await api("/api/llm/models");
    setModels(d.models || []);
  };
  const reloadLibrary = async () => {
    const tasks = await Promise.allSettled([
      api("/api/favorites", { params: { user_id: uid } }),
      api("/api/read_papers", { params: { user_id: uid } }),
      api("/api/folders", { params: { user_id: uid } }),
      api("/api/folders/default", { params: { user_id: uid } }),
    ]);
    if (tasks[0].status === "fulfilled")
      setFavorites(tasks[0].value.favorites || []);
    if (tasks[1].status === "fulfilled")
      setRead(new Set((tasks[1].value.papers || []).map((p) => p.paper_id)));
    if (tasks[2].status === "fulfilled")
      setFolders(tasks[2].value.folders || []);
    if (tasks[3].status === "fulfilled")
      setDefaultFolder(tasks[3].value.folder_id || "");
    setDataError(
      tasks.some((t) => t.status === "rejected")
        ? "部分文献库信息未能加载，请重试。"
        : "",
    );
  };
  useEffect(() => {
    setSavedSearches(stored(`scholarscope_saved:${uid}`, []));
    setNoteTags(stored(`scholarscope_tags:${uid}`, {}));
    setTagFilter("");
    setFavorites([]);
    setRead(new Set());
    setFolders([]);
    setFolder("");
    setActive(0);
    reloadLibrary();
  }, [uid]);
  useEffect(() => {
    const refreshTags = () =>
      setNoteTags(stored(`scholarscope_tags:${uid}`, {}));
    const synchronize = (e) => {
      if (e.key === `scholarscope_tags:${uid}`) refreshTags();
    };
    window.addEventListener("scholarscope-notes", refreshTags);
    window.addEventListener("storage", synchronize);
    return () => {
      window.removeEventListener("scholarscope-notes", refreshTags);
      window.removeEventListener("storage", synchronize);
    };
  }, [uid]);
  useEffect(() => {
    reloadModels().catch(() => {});
    if (token)
      api("/api/auth/me", { params: { token } })
        .then((d) => {
          if (!d.logged_in) {
            setUser("");
            setToken("");
            localStorage.removeItem("sakura_token");
            localStorage.removeItem("sakura_user");
          } else setUser(d.username);
        })
        .catch(() => {});
    return () => {
      controller.current?.abort();
      clearTimeout(noticeTimer.current);
    };
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("scholarscope_theme_v2", theme);
    } catch {}
  }, [theme]);
  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    setElapsed(0);
    const t = setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => clearInterval(t);
  }, [busy]);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    if (query.trim()) search(query);
    if (location.hash && location.hash !== "#projects")
      window.history.replaceState(
        null,
        "",
        location.pathname + location.search,
      );
  }, []);
  function navigate(next) {
    setView(next);
    window.history.replaceState(
      null,
      "",
      location.pathname +
        location.search +
        (next === "projects" ? "#projects" : ""),
    );
    setActive(0);
    setMobileReader(false);
    if (next === "search") {
      setFolder("");
      setReadFilter(false);
    }
    setTagFilter("");
    updateFilters({ source: "", method: "", citations: "", code: false });
  }
  useEffect(() => {
    const openHash = () => {
      const hash = location.hash;
      if (hash === "#favorites") {
        navigate("library");
        setFolder("");
        setReadFilter(false);
      } else if (["#history", "#search", "#projects"].includes(hash)) {
        navigate(hash.slice(1));
      } else if (
        ["#model", "#settings", "#docs", "#import", "#login"].includes(hash)
      ) {
        setDialog(hash === "#login" ? "auth" : hash.slice(1));
      } else return;
      if (hash !== "#projects")
        window.history.replaceState(
          null,
          "",
          location.pathname + location.search,
        );
    };
    window.addEventListener("hashchange", openHash);
    return () => window.removeEventListener("hashchange", openHash);
  }, []);
  function saveHistory(q, data) {
    setHistory((prev) => {
      const next = [
        { query: q, result: data, time: Date.now() },
        ...prev.filter((h) => h.query !== q),
      ].slice(0, 30);
      persist("sakura_history", [...next].reverse());
      return next;
    });
  }
  async function search(value = query) {
    const q = value.trim();
    if (!q) {
      setError("请输入研究问题或关键词。");
      return;
    }
    const yf = yearFrom ? Number(yearFrom) : null,
      yt = yearTo ? Number(yearTo) : null;
    if (
      (yearFrom && (!Number.isInteger(yf) || yf < 1500 || yf > 2100)) ||
      (yearTo && (!Number.isInteger(yt) || yt < 1500 || yt > 2100)) ||
      (yf !== null && yt !== null && yf > yt)
    ) {
      setError("请填写有效的年份范围，开始年份应早于结束年份。");
      return;
    }
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setQuery(q);
    setView("search");
    setTagFilter("");
    setFilters({ source: "", method: "", citations: "", code: false });
    setBusy(true);
    setError("");
    setMobileReader(false);
    try {
      const data = await api("/api/search", {
        method: "POST",
        data: {
          query: q,
          format: "json",
          llm_model: model,
          year_from: yf,
          year_to: yt,
        },
        signal: request.signal,
      });
      if (controller.current !== request) return;
      setResult(data);
      setResultQuery(q);
      setActive(0);
      saveHistory(q, data);
    } catch (e) {
      if (e.name !== "AbortError" && controller.current === request)
        setError("检索未完成：" + e.message);
    } finally {
      if (controller.current === request) {
        setBusy(false);
        controller.current = null;
      }
    }
  }
  function cancel() {
    controller.current?.abort();
    controller.current = null;
    setBusy(false);
    notify("已取消本次检索");
  }
  function restore(h) {
    cancel();
    setQuery(h.query);
    setFilters({ source: "", method: "", citations: "", code: false });
    setResult(h.result || null);
    setResultQuery(h.query);
    setActive(0);
    navigate("search");
    if (!h.result) search(h.query);
  }
  async function toggleFav(p) {
    const id = paperId(p),
      exists = favorites.some((f) => paperId(f) === id);
    await api("/api/favorites/" + encodeURIComponent(id), {
      method: exists ? "DELETE" : "POST",
      params: { user_id: uid },
      ...(!exists ? { data: { paper_meta: p, folder_id: defaultFolder } } : {}),
    });
    setFavorites((prev) =>
      exists
        ? prev.filter((f) => paperId(f) !== id)
        : [{ ...p, paper_id: id, folder_id: defaultFolder }, ...prev],
    );
    notify(exists ? "已移出文献库" : "已收藏到文献库");
  }
  async function toggleRead(p) {
    const id = paperId(p),
      exists = read.has(id);
    await api("/api/read_papers/" + encodeURIComponent(id), {
      method: exists ? "DELETE" : "POST",
      params: { user_id: uid },
    });
    setRead((prev) => {
      const next = new Set(prev);
      exists ? next.delete(id) : next.add(id);
      return next;
    });
    notify(exists ? "已取消已阅标记" : "已标记已阅");
  }
  async function movePaper(p, fid) {
    await api(
      "/api/folders/" +
        encodeURIComponent(fid || "unfiled") +
        "/papers/" +
        encodeURIComponent(paperId(p)),
      { method: "POST", params: { user_id: uid } },
    );
    setFavorites((prev) =>
      prev.map((f) =>
        paperId(f) === paperId(p) ? { ...f, folder_id: fid } : f,
      ),
    );
    notify("文献已移动");
  }
  const selectedFolder = folders.find((f) => f.id === folder);
  const library = favorites.filter(
    (p) =>
      (!folder || folder === "unfiled"
        ? !folder || !p.folder_id
        : p.folder_id === folder) &&
      (!readFilter || read.has(paperId(p))) &&
      (!libraryQuery ||
        [p.title, p.abstract, ...(p.authors || [])]
          .join(" ")
          .toLowerCase()
          .includes(libraryQuery.toLowerCase())),
  );
  const unfiltered = view === "library" ? library : result?.papers || [];
  const papers = filterPapers(unfiltered, filters).filter(
    (p) => !tagFilter || (noteTags[paperId(p)] || []).includes(tagFilter),
  );
  const allTags = [...new Set(Object.values(noteTags).flat())];
  const availableMethods = [...new Set(unfiltered.flatMap(methods))];
  const saveSearch = () => {
    if (!query.trim()) {
      notify("先输入需要保存的研究问题");
      return;
    }
    const exists = savedSearches.some((h) => h.query === query.trim());
    const next = exists
      ? savedSearches.filter((h) => h.query !== query.trim())
      : [
          { query: query.trim(), yearFrom, yearTo, time: Date.now() },
          ...savedSearches,
        ];
    setSavedSearches(next);
    persist(`scholarscope_saved:${uid}`, next);
    notify(exists ? "已取消保存检索" : "检索条件已保存到当前浏览器");
  };
  const restoreSaved = (h) => {
    setQuery(h.query);
    setYearFrom(h.yearFrom || "");
    setYearTo(h.yearTo || "");
    navigate("search");
    document.getElementById("query-input")?.focus();
  };
  useEffect(() => {
    const shortcut = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        navigate("search");
        requestAnimationFrame(() =>
          document.getElementById("query-input")?.focus(),
        );
      }
      if (e.key === "Escape" && !dialog) setMobileReader(false);
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [dialog]);
  const selected = papers[Math.min(active, Math.max(0, papers.length - 1))];
  const state = {
    user,
    token,
    setUser,
    setToken,
    dialog,
    setDialog,
    notify,
    runAction,
    uid,
    models,
    model,
    setModel,
    reloadModels,
    reloadLibrary,
    folders,
    defaultFolder,
    setDefaultFolder,
    setFolder,
    setView,
    setHistory,
    history,
    theme,
    setTheme,
    projectId,
    setProjectId,
    navigate,
  };
  const copyCitation = async (p) => {
    const text = citation(p);
    try {
      if (!navigator.clipboard?.writeText)
        throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(text);
      notify("BibTeX 引用已复制");
    } catch {
      download("reference.bib", text);
      notify("已下载 BibTeX 引用");
    }
  };
  const exportLibrary = (format) => {
    if (!papers.length) {
      notify("当前列表没有可导出的文献");
      return;
    }
    const body =
      format === "bib"
        ? papers.map(citation).join("\n\n")
        : format === "ris"
          ? ris(papers)
          : format === "csv"
            ? csv(papers)
            : JSON.stringify(papers, null, 2);
    download((selectedFolder?.name || "ScholarScope") + "." + format, body);
    notify(`已导出 ${papers.length} 篇文献`);
  };
  return (
    <AppContext.Provider value={state}>
      <IconContext.Provider value={{ size: 20, weight: "regular" }}>
        <MotionConfig reducedMotion="user">
          <div
            className={
              "app-frame " + (readingPaper ? "standalone-reading" : "")
            }
          >
            <aside className="rail">
              <a
                href="/"
                className="wordmark"
                aria-label="研索 ScholarScope 首页"
              >
                <div className="brand-symbol" aria-hidden="true">
                  Ø
                </div>
                <div>
                  <strong>研索</strong>
                  <span>ScholarScope</span>
                </div>
              </a>
              <nav className="primary-nav" aria-label="主导航">
                <button
                  className={
                    view === "search" ? "nav-button current" : "nav-button"
                  }
                  onClick={() => navigate("search")}
                  id="search-nav"
                >
                  <MagnifyingGlass />
                  <span>文献检索</span>
                  {view === "search" && <kbd className="nav-key">⌘ K</kbd>}
                </button>
                <button
                  className={
                    view === "library" && !readFilter && !folder
                      ? "nav-button current"
                      : "nav-button"
                  }
                  onClick={() => {
                    navigate("library");
                    setFolder("");
                    setReadFilter(false);
                  }}
                  id="fav-btn"
                >
                  <Books />
                  <span>我的文献库</span>
                  <small>{favorites.length}</small>
                </button>
                <button
                  className={
                    view === "history" ? "nav-button current" : "nav-button"
                  }
                  onClick={() => navigate("history")}
                  id="history-btn"
                >
                  <ClockCounterClockwise />
                  <span>检索历史</span>
                </button>
                <button
                  id="projects-nav"
                  className={
                    "nav-button " + (view === "projects" ? "current" : "")
                  }
                  onClick={() => navigate("projects")}
                >
                  <FolderSimple />
                  <span>科研项目</span>
                </button>
              </nav>
              <div className="rail-scroll">
                <section className="saved-nav">
                  <div className="rail-section">
                    <span>保存的检索</span>
                    <button
                      className="plain-icon"
                      aria-label="保存当前检索"
                      onClick={saveSearch}
                    >
                      <Plus size={14} />
                    </button>
                  </div>
                  {savedSearches.length ? (
                    savedSearches.map((h) => (
                      <div className="saved-query" key={h.query}>
                        <button onClick={() => restoreSaved(h)} title={h.query}>
                          <PushPin size={14} />
                          <span>{h.query}</span>
                        </button>
                        <button
                          className="plain-icon"
                          aria-label={"删除保存的检索 " + h.query}
                          onClick={() => {
                            const next = savedSearches.filter(
                              (x) => x.query !== h.query,
                            );
                            setSavedSearches(next);
                            persist(`scholarscope_saved:${uid}`, next);
                          }}
                        >
                          <X size={12} />
                        </button>
                      </div>
                    ))
                  ) : (
                    <p className="folder-empty">保存常用问题与年份条件</p>
                  )}
                </section>
                <div className="folder-nav">
                  <div className="rail-section">
                    <span>课题文件夹</span>
                    <button
                      className="plain-icon"
                      title="新建文件夹"
                      aria-label="新建文件夹"
                      onClick={() => setDialog("folder")}
                    >
                      <Plus size={16} />
                    </button>
                  </div>
                  <div className="folder-list">
                    {folders.length ? (
                      folders.map((f) => (
                        <button
                          key={f.id}
                          className={
                            "folder-button " +
                            (view === "library" && folder === f.id
                              ? "chosen"
                              : "")
                          }
                          onClick={() => {
                            navigate("library");
                            setFolder(f.id);
                            setReadFilter(false);
                          }}
                        >
                          <FolderSimple size={17} />
                          <span>{f.name}</span>
                        </button>
                      ))
                    ) : (
                      <p className="folder-empty">按课题归档你的文献</p>
                    )}
                  </div>
                  <button
                    className={
                      "folder-button " +
                      (view === "library" && readFilter ? "chosen" : "")
                    }
                    onClick={() => {
                      navigate("library");
                      setReadFilter(true);
                      setFolder("");
                    }}
                  >
                    <Check size={17} />
                    <span>已阅文献</span>
                    <small>{read.size}</small>
                  </button>
                </div>
                <section className="topic-nav">
                  <div className="rail-section">
                    <span>研究主题与方法</span>
                    <Tag size={13} />
                  </div>
                  {availableMethods.length ? (
                    availableMethods.slice(0, 6).map((m) => (
                      <button
                        className={
                          "folder-button " +
                          (filters.method === m ? "chosen" : "")
                        }
                        key={m}
                        onClick={() =>
                          setFilters({
                            ...filters,
                            method: filters.method === m ? "" : m,
                          })
                        }
                      >
                        <Tag size={14} />
                        <span>{m}</span>
                        <small>
                          {
                            unfiltered.filter((p) => methods(p).includes(m))
                              .length
                          }
                        </small>
                      </button>
                    ))
                  ) : (
                    <p className="folder-empty">根据文献标题与摘要整理</p>
                  )}
                </section>
                <section className="tag-nav">
                  <div className="rail-section">
                    <span>笔记标签</span>
                    {tagFilter && (
                      <button
                        className="plain-icon"
                        aria-label="清除标签筛选"
                        onClick={() => setTagFilter("")}
                      >
                        <X size={12} />
                      </button>
                    )}
                  </div>
                  {allTags.length ? (
                    allTags.map((t) => (
                      <button
                        key={t}
                        className={
                          "folder-button " + (tagFilter === t ? "chosen" : "")
                        }
                        onClick={() => {
                          setTagFilter(tagFilter === t ? "" : t);
                          setActive(0);
                          setMobileReader(false);
                        }}
                      >
                        <Tag size={14} />
                        <span>{t}</span>
                        <small>
                          {
                            Object.values(noteTags).filter((ts) =>
                              ts.includes(t),
                            ).length
                          }
                        </small>
                      </button>
                    ))
                  ) : (
                    <p className="folder-empty">在阅读笔记中添加标签</p>
                  )}
                </section>
              </div>
              <div className="rail-bottom">
                <button
                  className="nav-button"
                  onClick={() => setDialog("import")}
                  aria-label="导入文献"
                >
                  <UploadSimple />
                  <span>导入文献</span>
                </button>
                <button
                  className="nav-button"
                  id="docs-btn"
                  aria-label="使用指南"
                  onClick={() => setDialog("docs")}
                >
                  <BookOpen />
                  <span>使用指南</span>
                </button>
                <div className="rail-user">
                  <button
                    onClick={() => setDialog("auth")}
                    className="user-button"
                    id="login-btn"
                  >
                    <div className="user-monogram">
                      {user ? user.slice(0, 1).toUpperCase() : "研"}
                    </div>
                    <span>
                      <strong id="login-text">{user || "登录账号"}</strong>
                      <small>
                        {user ? "个人文献库" : "保存并整理研究资料"}
                      </small>
                    </span>
                  </button>
                  <button
                    className="plain-icon"
                    id="settings-btn"
                    title="设置"
                    aria-label="设置"
                    onClick={() => setDialog("settings")}
                  >
                    <Gear size={18} />
                  </button>
                </div>
              </div>
            </aside>
            <div className="workspace">
              <header className="workspace-header">
                <div className="breadcrumb">
                  <span>研究工作台</span>
                  <ArrowRight size={12} />
                  <strong>
                    {view === "search"
                      ? "文献检索"
                      : view === "library"
                        ? "我的文献库"
                        : view === "projects"
                          ? "科研项目"
                          : "检索历史"}
                  </strong>
                </div>
                <div className="header-actions">
                  <span className="workspace-subtitle">
                    问题 · 文献 · 证据 · 知识
                  </span>
                  <button
                    className="plain-icon"
                    id="model-btn"
                    title="模型设置"
                    aria-label="模型设置"
                    onClick={() => setDialog("model")}
                  >
                    <SlidersHorizontal size={18} />
                  </button>
                  <button
                    className="plain-icon"
                    title={theme === "dark" ? "切换浅色" : "切换深色"}
                    aria-label={theme === "dark" ? "切换浅色" : "切换深色"}
                    onClick={() =>
                      setTheme(theme === "dark" ? "light" : "dark")
                    }
                  >
                    {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
                  </button>
                  <button
                    className="mobile-login"
                    onClick={() => setDialog("auth")}
                  >
                    {user || "登录"}
                  </button>
                </div>
              </header>
              <main
                className={
                  "workspace-body " +
                  (view === "search" && result ? "with-results" : "")
                }
              >
                <AnimatePresence mode="wait" initial={false}>
                  <motion.div
                    key={view}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.12 }}
                  >
                    {view === "search" && (
                      <>
                        <section className="search-stage">
                          <div className="workspace-title">
                            <div>
                              <h1>文献检索</h1>
                              <span>Research search</span>
                            </div>
                            <button
                              className="secondary-button"
                              onClick={saveSearch}
                            >
                              <BookmarkSimple size={15} />
                              {savedSearches.some(
                                (h) => h.query === query.trim(),
                              )
                                ? "已保存检索"
                                : "保存检索"}
                            </button>
                          </div>
                          <form
                            className="query-composer"
                            onSubmit={(e) => {
                              e.preventDefault();
                              search();
                            }}
                          >
                            <MagnifyingGlass size={20} />
                            <label
                              className="visually-hidden"
                              htmlFor="query-input"
                            >
                              检索内容
                            </label>
                            <input
                              id="query-input"
                              value={query}
                              onChange={(e) => {
                                setQuery(e.target.value);
                                setError("");
                              }}
                              placeholder="检索研究问题、关键词或论文标题"
                              autoComplete="off"
                            />
                            <kbd className="search-key">Enter</kbd>
                            {busy ? (
                              <button
                                type="button"
                                className="primary-button"
                                onClick={cancel}
                              >
                                <X size={15} />
                                取消检索
                              </button>
                            ) : (
                              <button
                                className="primary-button"
                                id="search-btn"
                              >
                                <MagnifyingGlass size={15} />
                                检索文献
                              </button>
                            )}
                          </form>
                          <div className="composer-tools">
                            <div className="query-options">
                              <label className="year-fields">
                                <span>发表年份</span>
                                <input
                                  id="year-from"
                                  aria-label="开始年份"
                                  type="number"
                                  min="1500"
                                  max="2100"
                                  placeholder="不限"
                                  value={yearFrom}
                                  onChange={(e) => setYearFrom(e.target.value)}
                                />
                                <span>至</span>
                                <input
                                  id="year-to"
                                  aria-label="结束年份"
                                  type="number"
                                  min="1500"
                                  max="2100"
                                  placeholder="不限"
                                  value={yearTo}
                                  onChange={(e) => setYearTo(e.target.value)}
                                />
                              </label>
                              <select
                                className="model-select"
                                aria-label="检索模型"
                                value={model}
                                onChange={(e) => {
                                  setModel(e.target.value);
                                  localStorage.setItem(
                                    "sakura_llm",
                                    e.target.value,
                                  );
                                }}
                              >
                                <option value="">自动选择模型</option>
                                {models.map((m) => (
                                  <option key={m.name} value={m.name}>
                                    {m.name}
                                  </option>
                                ))}
                              </select>
                              <button
                                className={
                                  "secondary-button filter-toggle " +
                                  (advanced ? "is-active" : "")
                                }
                                aria-expanded={advanced}
                                onClick={() => setAdvanced(!advanced)}
                              >
                                <SlidersHorizontal size={15} />
                                高级筛选
                              </button>
                            </div>
                            <span className="search-sources">
                              arXiv / OpenAlex / Crossref / Semantic Scholar /
                              本地索引
                            </span>
                          </div>
                          {advanced && (
                            <FilterPanel
                              {...{ filters, setFilters, availableMethods }}
                            />
                          )}
                        </section>
                        {error && (
                          <div className="inline-alert" role="alert">
                            <WarningCircle size={18} />
                            {error}
                          </div>
                        )}
                        {busy ? (
                          <SearchLoading elapsed={elapsed} />
                        ) : result ? (
                          <>
                            <div className="list-heading">
                              <div>
                                <h2>
                                  {readingPaper ? "独立阅读" : "检索结果"}{" "}
                                  <span>
                                    {papers.length}
                                    {papers.length !== unfiltered.length
                                      ? ` / ${unfiltered.length}`
                                      : ""}{" "}
                                    篇
                                  </span>
                                  {tagFilter && (
                                    <button
                                      className="active-tag-filter"
                                      onClick={() => setTagFilter("")}
                                    >
                                      {tagFilter}
                                      <X size={12} />
                                    </button>
                                  )}
                                </h2>
                                <p className="result-query">{resultQuery}</p>
                              </div>
                              <span className="source-info">
                                {result.stats?.elapsed_seconds
                                  ? `${Number(result.stats.elapsed_seconds).toFixed(1)}s / `
                                  : ""}
                                {(result.stats?.backends_used || []).join(
                                  " / ",
                                )}
                              </span>
                            </div>
                            {papers.length ? (
                              <PaperWorkspace
                                {...{
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
                                }}
                                standalone={!!readingPaper}
                                relationships={result?.relationships || []}
                                onMethod={(m) =>
                                  setFilters({
                                    ...filters,
                                    method: filters.method === m ? "" : m,
                                  })
                                }
                              />
                            ) : (
                              <Empty
                                icon={<MagnifyingGlass size={32} />}
                                title={
                                  unfiltered.length
                                    ? "没有符合筛选条件的文献"
                                    : "暂未找到可推荐的文献"
                                }
                                body="尝试更具体的学术术语、放宽年份范围，或稍后重新检索。"
                              />
                            )}
                          </>
                        ) : (
                          <>
                            <ResearchStart
                              {...{
                                examples,
                                history,
                                restore,
                                setQuery,
                                favorites,
                                read,
                                folders,
                              }}
                            />
                          </>
                        )}
                      </>
                    )}
                    {view === "library" && (
                      <>
                        <div className="page-heading">
                          <div>
                            <h1>
                              {readFilter
                                ? "已阅文献"
                                : selectedFolder?.name || "我的文献库"}
                            </h1>
                            <p>
                              {papers.length} 篇文献
                              {selectedFolder
                                ? " · 课题文件夹"
                                : " · 按课题整理阅读资料"}
                            </p>
                          </div>
                          <div className="page-tools">
                            <button
                              className="secondary-button"
                              onClick={() => setDialog("import")}
                            >
                              <UploadSimple size={16} />
                              导入
                            </button>
                            <ExportButton onExport={exportLibrary} />
                          </div>
                        </div>
                        <div className="library-toolbar">
                          <label className="filter-input">
                            <MagnifyingGlass size={17} />
                            <input
                              aria-label="筛选文献"
                              placeholder="筛选标题、摘要或作者"
                              value={libraryQuery}
                              onChange={(e) => {
                                setLibraryQuery(e.target.value);
                                setActive(0);
                              }}
                            />
                          </label>
                          <select
                            aria-label="文献库文件夹"
                            value={folder}
                            onChange={(e) => {
                              setFolder(e.target.value);
                              setActive(0);
                            }}
                          >
                            <option value="">全部文献</option>
                            <option value="unfiled">未分类</option>
                            {folders.map((f) => (
                              <option key={f.id} value={f.id}>
                                {f.name}
                              </option>
                            ))}
                          </select>
                          {selectedFolder && (
                            <button
                              className="secondary-button"
                              onClick={() => setDialog("folders")}
                            >
                              管理文件夹
                            </button>
                          )}
                        </div>
                        <FilterPanel
                          {...{ filters, setFilters, availableMethods }}
                        />
                        {dataError && (
                          <div className="inline-alert" role="alert">
                            {dataError}
                            <button onClick={reloadLibrary}>重试</button>
                          </div>
                        )}
                        {papers.length ? (
                          <PaperWorkspace
                            {...{
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
                            }}
                            onMethod={(m) =>
                              setFilters({
                                ...filters,
                                method: filters.method === m ? "" : m,
                              })
                            }
                            library
                          />
                        ) : (
                          <Empty
                            icon={<Books size={34} />}
                            title={
                              unfiltered.length
                                ? "没有符合筛选条件的文献"
                                : tagFilter
                                  ? "没有匹配该笔记标签的文献"
                                  : libraryQuery
                                    ? "没有匹配的文献"
                                    : readFilter
                                      ? "尚未标记已阅文献"
                                      : "开始建立你的文献库"
                            }
                            body={
                              libraryQuery || unfiltered.length
                                ? "换一个关键词，或清空筛选条件。"
                                : "在检索结果中收藏文献，或导入已有的文献文件。"
                            }
                          />
                        )}
                      </>
                    )}
                    {view === "projects" && <ProjectWorkspace />}
                    {view === "history" && (
                      <>
                        <div className="page-heading">
                          <div>
                            <h1>检索历史</h1>
                            <p>重新打开研究问题，继续阅读已保存的结果。</p>
                          </div>
                        </div>
                        {history.length ? (
                          <div className="history-list">
                            {history.map((h, i) => (
                              <article key={h.time + "-" + i}>
                                <ClockCounterClockwise size={19} />
                                <button
                                  className="history-open"
                                  onClick={() => restore(h)}
                                >
                                  <strong>{h.query}</strong>
                                  <span>
                                    {new Date(h.time).toLocaleDateString(
                                      "zh-CN",
                                    )}
                                    {h.result
                                      ? " · " +
                                        (h.result.papers?.length || 0) +
                                        " 篇结果"
                                      : ""}
                                  </span>
                                </button>
                                <button
                                  className="plain-icon"
                                  aria-label="删除该检索记录"
                                  onClick={() => {
                                    const next = history.filter(
                                      (_, j) => i !== j,
                                    );
                                    setHistory(next);
                                    persist(
                                      "sakura_history",
                                      [...next].reverse(),
                                    );
                                  }}
                                >
                                  <Trash size={17} />
                                </button>
                              </article>
                            ))}
                          </div>
                        ) : (
                          <Empty
                            icon={<ClockCounterClockwise size={34} />}
                            title="尚无检索记录"
                            body="输入研究问题完成一次检索，之后可以从这里继续。"
                          />
                        )}
                      </>
                    )}
                  </motion.div>
                </AnimatePresence>
              </main>
            </div>
          </div>
          <AppDialogs />
          <AnimatePresence>
            {notice && (
              <motion.div
                className="toast"
                role="status"
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
              >
                <Check size={17} />
                {notice}
              </motion.div>
            )}
          </AnimatePresence>
        </MotionConfig>
      </IconContext.Provider>
    </AppContext.Provider>
  );
}
function SearchLoading({ elapsed }) {
  return (
    <section className="search-loading" aria-live="polite">
      <div className="loading-heading">
        <div>
          <h2>正在检索学术文献</h2>
          <p>正在查找相关文献并核对标题与摘要。</p>
        </div>
        <span>{elapsed}s</span>
      </div>
      <div className="skeleton-list">
        {[0, 1, 2].map((i) => (
          <div key={i} className="skeleton-row">
            <i />
            <i />
            <i />
          </div>
        ))}
      </div>
    </section>
  );
}
function Empty({ icon, title, body }) {
  return (
    <div className="empty-panel">
      {icon}
      <h2>{title}</h2>
      <p>{body}</p>
    </div>
  );
}
function ExportButton({ onExport }) {
  const [format, setFormat] = useState("bib");
  return (
    <div className="export-control">
      <select
        aria-label="导出格式"
        value={format}
        onChange={(e) => setFormat(e.target.value)}
      >
        <option value="bib">BibTeX</option>
        <option value="ris">RIS</option>
        <option value="csv">CSV</option>
        <option value="json">JSON</option>
      </select>
      <button className="secondary-button" onClick={() => onExport(format)}>
        <DownloadSimple size={16} />
        导出
      </button>
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
