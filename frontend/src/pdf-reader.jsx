import React, { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { ArrowLeft, ArrowRight, Check } from "@phosphor-icons/react";
import { api, storedText } from "./api";
import { projectPath } from "./project-workspace";
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export default function PDFReader({
  pid,
  document: doc,
  papers,
  editable,
  onSaved,
  onSource,
}) {
  const [pdf, setPDF] = useState(null),
    [pageNumber, setPage] = useState(doc.initialPage || 1),
    [zoom, setZoom] = useState(1),
    [width, setWidth] = useState(600);
  const [error, setError] = useState(""),
    [quote, setQuote] = useState(doc.highlightQuote || ""),
    [field, setField] = useState("finding"),
    [status, setStatus] = useState(""),
    [saving, setSaving] = useState(false);
  const canvas = useRef(null),
    host = useRef(null),
    renderRef = useRef(null);
  const [highlightBox, setHighlightBox] = useState(null), [tableReport, setTableReport] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const activePage = useRef("");
  activePage.current = doc.id + ":" + pageNumber;
  const [question, setQuestion] = useState(""), [answer, setAnswer] = useState(null), [asking, setAsking] = useState(false);
  const [note, setNote] = useState("");
  const [annotations, setAnnotations] = useState([]);
  const loadAnnotations = () => api(projectPath(pid) + "/items", { params: { kind: "evidence" } }).then(d => setAnnotations(d.items.filter(e => e.data.document_id === doc.id)));
  useEffect(() => { let live = true; api(projectPath(pid) + "/items", { params: { kind: "evidence" } }).then(d => live && setAnnotations(d.items.filter(e => e.data.document_id === doc.id))).catch(e => live && setError(e.message)); return () => { live = false; }; }, [pid, doc.id]);
  const page = doc.data.pages.find((p) => p.number === pageNumber),
    paper = papers.find((p) => p.id === doc.data.paper_id);
  const scale = Math.min(width / (page?.width || 600), 1.5) * zoom;
  useEffect(() => { setHighlightBox(null); setTableReport(null); setNote(""); }, [pageNumber]);
  useEffect(() => {
    let live = true,
      loadingTask;
    const controller = new AbortController();
    fetch(projectPath(pid) + "/documents/" + doc.id + "/file", {
      signal: controller.signal,
      headers: storedText("sakura_token")
        ? { Authorization: "Bearer " + storedText("sakura_token") }
        : {},
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("PDF 文件未能读取");
        loadingTask = pdfjs.getDocument({
          data: new Uint8Array(await response.arrayBuffer()),
          cMapUrl: "/static/pdfjs/cmaps/",
          cMapPacked: true,
          standardFontDataUrl: "/static/pdfjs/standard_fonts/",
          wasmUrl: "/static/pdfjs/wasm/",
          useSystemFonts: true,
        });
        const value = await loadingTask.promise;
        if (live) setPDF(value);
      })
      .catch((e) => {
        if (live && e.name !== "AbortError") setError(e.message);
      });
    return () => {
      live = false;
      controller.abort();
      loadingTask?.destroy();
    };
  }, [pid, doc.id]);
  useEffect(() => {
    if (!host.current) return;
    const measure = () =>
      setWidth(Math.max(200, Math.min(740, host.current.clientWidth - 32)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let live = true;
    renderRef.current?.cancel();
    if (pdf && canvas.current)
      pdf
        .getPage(pageNumber)
        .then((p) => {
          if (!live) return;
          const viewport = p.getViewport({ scale });
          const ratio = Math.min(window.devicePixelRatio || 1, 2);
          canvas.current.width = viewport.width * ratio;
          canvas.current.height = viewport.height * ratio;
          canvas.current.style.width = viewport.width + "px";
          canvas.current.style.height = viewport.height + "px";
          const task = p.render({
            canvasContext: canvas.current.getContext("2d"),
            viewport,
            transform: [ratio, 0, 0, ratio, 0, 0],
          });
          renderRef.current = task;
          task.promise.catch((e) => {
            if (live && e.name !== "RenderingCancelledException")
              setError("PDF 页面显示失败，可使用下方提取原文继续阅读。");
          });
        })
        .catch((e) => live && setError(e.message));
    return () => {
      live = false;
      renderRef.current?.cancel();
    };
  }, [pdf, pageNumber, scale]);
  const save = async (span) => {
    const value = span?.text || quote;
    if (!value.trim()) {
      setError("先选择或填写一段原文");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api(projectPath(pid) + "/evidence", {
        method: "POST",
        data: {
          data: {
            paper_id: doc.data.paper_id,
            document_id: doc.id,
            page: pageNumber,
            quote: value,
            field,
            note,
            ...(span ? { span_id: span.id } : {}),
            confirmed: true,
          },
        },
      });
      setStatus(`已保存原文第 ${pageNumber} 页的证据`);
      setQuote("");
      setNote("");
      await loadAnnotations();
      await onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="pdf-workspace">
      <aside className="pdf-outline">
        <h2>原文导航</h2>
        <p>{doc.label}</p>
        {doc.highlightQuote && <p className="source-preview">引用片段：{doc.highlightQuote}</p>}
        {doc.data.outline.map((h, i) => (
          <button
            key={i}
            onClick={() => {
              setPage(h.page);
              setQuote("");
            }}
          >
            {h.title}
            <small>{h.page}</small>
          </button>
        ))}
        {!doc.data.outline.length && (
          <p className="muted">PDF 未提供章节；使用页码浏览。</p>
        )}
        <h3>文档信息</h3>
        <p>
          {doc.data.page_count} 页 ·{" "}
          {doc.data.status === "scan_no_text"
            ? "扫描件，需人工阅读"
            : "已提取正文"}
        </p>
        <p className="muted">{doc.data.warnings.join("。")}</p>
      </aside>
      <section className="pdf-center" ref={host}>
        <div className="pdf-toolbar">
          <button
            className="plain-icon"
            aria-label="PDF 上一页"
            disabled={pageNumber <= 1}
            onClick={() => {
              setPage(pageNumber - 1);
              setQuote("");
            }}
          >
            <ArrowLeft />
          </button>
          <label>
            页码
            <input
              aria-label="PDF 页码"
              type="number"
              min={1}
              max={doc.data.page_count}
              value={pageNumber}
              onChange={(e) => {
                const n = Number(e.target.value);
                if (n >= 1 && n <= doc.data.page_count) {
                  setPage(n);
                  setQuote("");
                }
              }}
            />
          </label>
          <span>/ {doc.data.page_count}</span>
          <button
            className="plain-icon"
            aria-label="PDF 下一页"
            disabled={pageNumber >= doc.data.page_count}
            onClick={() => {
              setPage(pageNumber + 1);
              setQuote("");
            }}
          >
            <ArrowRight />
          </button>
          <select
            aria-label="PDF 缩放"
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
          >
            <option value={0.8}>80%</option>
            <option value={1}>适合宽度</option>
            <option value={1.2}>120%</option>
            <option value={1.5}>150%</option>
          </select>
        </div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="pdf-scroll">
          <div
            className="pdf-page"
            style={{ width: page.width * scale, height: page.height * scale }}
          >
            <canvas ref={canvas} aria-label={`PDF 第 ${pageNumber} 页`} />
            <div
              className="pdf-text-layer"
              onMouseUp={() => {
                const selection = window.getSelection()?.toString();
                if (selection) setQuote(selection.trim());
              }}
            >
              {page.spans.map((s) => (
                <span
                  key={s.id}
                  style={{
                    background: doc.highlightQuote && (doc.highlightQuote.replace(/\s+/g, " ").includes(s.text.replace(/\s+/g, " ")) || s.text.includes(doc.highlightQuote)) ? "rgb(237 111 92 / 25%)" : undefined,
                    left: s.bbox[0] * scale,
                    top: s.bbox[1] * scale,
                    width: (s.bbox[2] - s.bbox[0]) * scale,
                    height: (s.bbox[3] - s.bbox[1]) * scale,
                    fontSize: (s.bbox[3] - s.bbox[1]) * scale,
                  }}
                >
                  {s.text}
                </span>
              ))}
            </div>
            {highlightBox && <div className="pdf-location-highlight" style={{ left: highlightBox[0] * scale, top: highlightBox[1] * scale, width: (highlightBox[2] - highlightBox[0]) * scale, height: (highlightBox[3] - highlightBox[1]) * scale }} />}
          </div>
        </div>
        <details className="pdf-extracted">
          <summary>查看可定位的提取原文、表格与图表</summary>
          {page.spans.map((s) => (
            <div className="pdf-span" key={s.id}>
              <p>{s.text}</p>
              {editable && (
                <button
                  className="text-action"
                  disabled={saving}
                  onClick={() => save(s)}
                >
                  摘录为证据
                </button>
              )}
            </div>
          ))}
          {!page.spans.length && (
            <p>{page.text || "该页没有可提取文字，请阅读 PDF 图像。"}</p>
          )}
          {page.tables.map((t) => (
            <div className="matrix-scroll" key={t.id}>
              <h3>原文表格 {t.id}</h3>
              <div className="project-actions"><button className="text-action" onClick={() => setHighlightBox(t.bbox)}>定位原文表格</button><button className="text-action" onClick={async () => { try { setTableReport(await api(projectPath(pid) + "/documents/" + doc.id + "/tables/" + pageNumber + "/" + t.id)); setHighlightBox(t.bbox); } catch (e) { setError(e.message); } }}>核对表格结构与数值</button></div>
              <table>
                <tbody>
                  {t.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((value, j) => (
                        <td key={j}>{value || ""}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          {tableReport && <div className="source-preview"><h3>{tableReport.kind === "figure" ? "图像与对应原文" : tableReport.kind === "equation" ? "公式候选与对应原文" : "表格结构核对"}</h3><p className="muted">{tableReport.note}</p>{tableReport.columns?.map(c => <p key={c.index}>{c.header || "列 " + (c.index + 1)}：{c.numeric_cells} 个数字单元格{c.minimum !== null ? `，范围 ${c.minimum}–${c.maximum}` : "，未解析为单个数值"}</p>)}<button className="secondary-button" disabled={analyzing} onClick={async () => { const requestedPage = activePage.current; setAnalyzing(true); try { const kind = tableReport.kind || "table"; const id = tableReport.element_id || tableReport.table_id; const result = await api(projectPath(pid) + "/documents/" + doc.id + "/elements/" + pageNumber + "/" + kind + "/" + id + "/analyze", {method:"POST"}); if (activePage.current === requestedPage) setTableReport(result); } catch(e) { if (activePage.current === requestedPage) setError(e.message); } finally { setAnalyzing(false); } }}>辅助解读图表或公式</button>{tableReport.visual_analysis && <div className="review-finding"><strong>视觉辅助解读 · 待人工核对</strong><p>{tableReport.visual_analysis.message}</p><p>{tableReport.visual_analysis.description}</p>{tableReport.visual_analysis.latex && <pre>{tableReport.visual_analysis.latex}</pre>}{tableReport.visual_analysis.observations?.map((s,i) => <p key={i}>{s}</p>)}{tableReport.visual_analysis.uncertainties?.map((s,i) => <p className="muted" key={i}>{s}</p>)}</div>}{tableReport.context?.map(c => <button className="agent-source" key={c.span_id} onClick={() => { setHighlightBox(c.bbox); setQuote(c.quote); }}>{c.quote}<span>对应原文第 {c.page} 页 · 可摘录核对</span></button>)}</div>}
          <div className="project-actions">{page.figures.map(f => <button className="text-action" key={f.id} onClick={async () => { setHighlightBox(f.bbox); try { setTableReport(await api(projectPath(pid) + "/documents/" + doc.id + "/elements/" + pageNumber + "/figure/" + f.id)); } catch (e) { setError(e.message); } }}>查看原图区域 {f.id}</button>)}{page.equations.map(id => <button className="text-action" key={id} onClick={async () => { const s = page.spans.find(s => s.id === id); setHighlightBox(s?.bbox); setQuote(s?.text || ""); try { setTableReport(await api(projectPath(pid) + "/documents/" + doc.id + "/elements/" + pageNumber + "/equation/" + id)); } catch (e) { setError(e.message); } }}>定位公式候选 {id}</button>)}</div>
          <p className="muted">
            检测到 {page.figures.length} 个图像区域、{page.equations.length}{" "}
            个含公式符号的文本行。位置来自 PDF 布局，未推断图像中的实验结论。
          </p>
        </details>
      </section>
      <aside className="pdf-evidence">
        <span className="workspace-label">原文 · 第 {pageNumber} 页</span>
        <h2>{paper?.label}</h2>
        <p className="muted">
          选择文字，或从下方提取原文逐行摘录。系统核对页码和片段后保存。
        </p>
        {editable && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              save();
            }}
          >
            <label>
              证据字段
              <input
                aria-label="PDF 证据字段"
                value={field}
                onChange={(e) => setField(e.target.value)}
                required
              />
            </label>
            <label>
              原文片段
              <textarea
                aria-label="PDF 证据片段"
                value={quote}
                onChange={(e) => setQuote(e.target.value)}
                required
              />
            </label>
            <label>阅读批注<textarea aria-label="PDF 阅读批注" maxLength={5000} value={note} onChange={e => setNote(e.target.value)} placeholder="记录对这段原文的理解，随证据和页码保存" /></label>
            <button className="primary-button" disabled={saving}>
              <Check size={15} />
              核对并保存证据
            </button>
          </form>
        )}
        {status && <p role="status">{status}</p>}
        <details className="pdf-annotations"><summary>本页摘录与批注 · {annotations.filter(e => e.data.page === pageNumber).length}</summary>{annotations.filter(e => e.data.page === pageNumber).map(e => <div key={e.id} className="pdf-annotation"><button className="agent-source" onClick={() => { setQuote(e.data.quote); setHighlightBox(e.data.bbox || null); }}>{e.data.quote}<span>已核对原文 · {e.data.confirmed_by || "待人工确认"}</span></button>{e.data.note && <p>{e.data.note}</p>}</div>)}</details>
        <form onSubmit={async e => { e.preventDefault(); setAsking(true); setError(""); try { const result = await api(projectPath(pid) + "/questions", { method: "POST", data: { question, paper_ids: [doc.data.paper_id] } }); setAnswer(result.data || result); await onSaved(); } catch (e) { setError(e.message); } finally { setAsking(false); } }}><label>基于本文资料提问<textarea aria-label="PDF 研究问题" required value={question} onChange={e => setQuestion(e.target.value)} placeholder="例如：数据规模与验证指标有哪些原文依据？" /></label><button className="secondary-button" disabled={asking}>{asking ? "正在检索原文…" : "查找本文依据"}</button></form>
        {answer && <div className="pdf-answer"><p className="muted">模型综合与原文摘录均保留出处；图表未报告的结论不能推断。</p><p className="answer-text">{answer.answer}</p>{answer.citations.map(c => <button className="text-action" key={c.number} onClick={() => { if (c.document_id === doc.id) { setPage(c.page); setQuote(c.quote); } else onSource?.(c); }}>[{c.number}] {c.page ? `原文第 ${c.page} 页` : "摘要依据"}</button>)}</div>}
        <p className="muted">
          证据保留文档哈希、页码与原文位置。只有你在实际原文中核对的内容可进入研究成果。
        </p>
      </aside>
    </div>
  );
}
