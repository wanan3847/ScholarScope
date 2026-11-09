"""Reported or researcher-supplied data, with units and explicit provenance."""
from __future__ import annotations
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from workspace.store import WorkspaceError, normalized


def numbers(value):
    return [float(n) for n in re.findall(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", str(value))]


def save_chart(store, pid, actor, data, cid=None, revision=None):
    old = store.item(pid, actor, cid, "chart") if cid else None
    if old and old["revision"] != revision:
        raise WorkspaceError("图表已被其他成员更新，请重新加载", 409)
    title = normalized(data.get("title", ""))
    labels = [str(v)[:150] for v in data.get("labels", [])]
    if not title or not 1 <= len(labels) <= 500:
        raise WorkspaceError("图表需要标题及 1–500 个数据标签")
    if data.get("type") not in ("bar", "line"):
        raise WorkspaceError("支持柱状图或折线图")
    if not data.get("x_label", "").strip() or not data.get("y_label", "").strip():
        raise WorkspaceError("请写明横轴、纵轴名称及单位；无单位时明确注明")
    origin = data.get("origin", "reported")
    if origin not in ("reported", "researcher_data", "derived"):
        raise WorkspaceError("请选择数据来源类型")
    if origin != "reported" and not data.get("provenance_note", "").strip():
        raise WorkspaceError("研究者提供或计算的数据需说明来源与计算方法")
    series = data.get("series", [])
    if not 1 <= len(series) <= 8:
        raise WorkspaceError("图表需为 1–8 组数据")
    clean_series, dependencies = [], set()
    for s in series:
        values, eids = s.get("values", []), s.get("evidence_ids", [])
        if len(values) != len(labels):
            raise WorkspaceError("每组数据长度需与标签一致")
        if eids and len(eids) != len(labels):
            raise WorkspaceError("每个数据点需有对应的证据标识或空值")
        clean_values, sources = [], []
        for i, value in enumerate(values):
            try: value = float(value)
            except (ValueError, TypeError): raise WorkspaceError("图表数值格式无效") from None
            if not math.isfinite(value) or abs(value) > 1e15:
                raise WorkspaceError("图表数值需为有限、合理范围的数字")
            eid = eids[i] if eids else None
            source = None
            if eid:
                e = store.item(pid, actor, eid, "evidence")
                if not store.verify_evidence(pid, actor, eid)["valid"]:
                    raise WorkspaceError("数据来源已变化，请重新核对证据")
                if origin == "reported" and not any(math.isclose(value, n, rel_tol=1e-6, abs_tol=1e-9) for n in numbers(e["data"]["quote"])):
                    raise WorkspaceError("报告值未出现在指定原文片段中；计算或换算请明确选择派生数据并说明")
                source = {"evidence_id": eid, "source_hash": e["data"]["source_hash"], "evidence_revision": e["revision"]}
                dependencies.add(eid)
            elif origin == "reported":
                raise WorkspaceError("原文报告数据的每个点都需要可核对证据")
            clean_values.append(value); sources.append(source)
        clean_series.append({"name": str(s.get("name", "数据"))[:150], "values": clean_values, "evidence_ids": [s["evidence_id"] if s else None for s in sources], "sources": sources})
    clean = {"title": title, "type": data["type"], "labels": labels, "series": clean_series, "origin": origin, "x_label": str(data["x_label"])[:200],
        "y_label": str(data["y_label"])[:200], "provenance_note": str(data.get("provenance_note", ""))[:10000], "evidence_ids": sorted(dependencies), "stale": False}
    return chart_view(store, pid, actor, store.put(pid, actor, "chart", title, clean, cid, revision))


def chart_view(store, pid, actor, item):
    evidence, invalid = [], 0
    for series in item["data"]["series"]:
        for source in series.get("sources", []):
            if not source: continue
            try:
                e = store.item(pid, actor, source["evidence_id"], "evidence")
                valid = store.verify_evidence(pid, actor, e["id"])["valid"] and source["source_hash"] == e["data"]["source_hash"] and source["evidence_revision"] == e["revision"]
                paper = store.item(pid, actor, e["data"]["paper_id"], "paper")
                evidence.append({**e["data"], "evidence_id": e["id"], "valid": valid, "title": paper["label"], "doi": paper["data"].get("doi")})
            except WorkspaceError:
                valid = False
            invalid += not valid
    return {**item, "sources": evidence, "validation": {"invalid_sources": invalid}, "stale": bool(invalid or item["data"].get("stale"))}


def export_chart(store, pid, actor, cid, fmt):
    view = chart_view(store, pid, actor, store.item(pid, actor, cid, "chart"))
    if fmt not in ("svg", "png"):
        raise WorkspaceError("图表支持 SVG、PNG 导出")
    if view["stale"]:
        raise WorkspaceError("图表来源已变化，请核对并保存后再导出", 409)
    with tempfile.TemporaryDirectory(prefix="scholarscope-plot-") as tmp:
        source = Path(tmp) / "chart.json"; output = Path(tmp) / ("chart." + fmt)
        source.write_text(json.dumps({**view["data"], "_sources": view["sources"]}, ensure_ascii=False))
        # Rebuilding the system-font index for every preview can exceed the
        # rendering budget. Cache contains font metadata, never project content.
        runtime=Path(os.getenv("SCHOLARSCOPE_WORKSPACE_DIR",Path(__file__).resolve().parents[1]/"data"/"workspace"))
        font_cache=Path(os.getenv("MPLCONFIGDIR",runtime/"cache"/"matplotlib"))
        font_cache.mkdir(parents=True,exist_ok=True)
        try:
            result = subprocess.run([sys.executable, "-m", "workspace.charts", "--plot", str(source), str(output)], capture_output=True, timeout=25,
                cwd=Path(__file__).resolve().parents[1], env={**os.environ, "MPLCONFIGDIR":str(font_cache)})
            if result.returncode or not output.exists(): raise WorkspaceError("科研图表渲染暂不可用", 503)
            return output.read_bytes(), "image/svg+xml" if fmt == "svg" else "image/png"
        except (subprocess.TimeoutExpired, OSError):
            raise WorkspaceError("科研图表渲染超时，请减少数据量后重试", 503) from None


def table_analysis(store, pid, actor, did, page_number, table_id):
    doc = store.item(pid, actor, did, "document")
    page = next((p for p in doc["data"]["pages"] if p["number"] == page_number), None)
    table = next((t for t in page.get("tables", []) if t["id"] == table_id), None) if page else None
    if not table:
        raise WorkspaceError("该页未找到指定的真实表格", 404)
    rows = table["rows"]
    columns = []
    for i in range(max((len(r) for r in rows), default=0)):
        values = [str(r[i] or "") if i < len(r) else "" for r in rows]
        numeric = [numbers(v)[0] for v in values[1:] if len(numbers(v)) == 1]
        columns.append({"index": i, "header": values[0] if values else "", "numeric_cells": len(numeric),
            "minimum": min(numeric) if numeric else None, "maximum": max(numeric) if numeric else None})
    return {"document_id": did, "paper_id": doc["data"]["paper_id"], "page": page_number, "table_id": table_id, "bbox": table["bbox"],
        "rows": rows, "columns": columns, "mode": "parsed_table_structure", "note": "统计仅针对已解析为单个数字的单元格；单位、表头和合并单元格请在原 PDF 核对。不能由图形位置推断实验结论。"}


def element_analysis(store, pid, actor, did, page_number, kind, element_id, *, model=None, visual=False):
    doc = store.item(pid, actor, did, "document")
    page = next((p for p in doc["data"]["pages"] if p["number"] == page_number), None)
    if not page: raise WorkspaceError("原文页码不存在", 404)
    if kind == "table":
        result = table_analysis(store, pid, actor, did, page_number, element_id)
    elif kind in ("figure", "equation"):
        elements = page["figures"] if kind == "figure" else [s for s in page["spans"] if s["id"] in page["equations"]]
        element = next((f for f in elements if f["id"] == element_id), None)
        if not element: raise WorkspaceError("当前页没有指定图像或公式候选", 404)
        result = {"document_id": did, "paper_id": doc["data"]["paper_id"], "page": page_number, "element_id": element_id,
            "bbox": element["bbox"], "kind": kind, "mode": "original_layout_and_context", "quote": element.get("text", ""),
            "note": "原图或含公式符号的候选行与附近原文一起查看。未对图像进行 OCR，不从像素位置推断数值、方法或实验结论。"}
    else: raise WorkspaceError("未知原文元素类型")
    top, bottom = result["bbox"][1], result["bbox"][3]
    near = [s for s in page["spans"] if max(top - 70, 0) <= s["bbox"][1] <= bottom + 70]
    result["context"] = [{"quote": s["text"], "paper_id": doc["data"]["paper_id"], "document_id": did, "page": page_number,
        "scope": "fulltext", "span_id": s["id"], "bbox": s["bbox"], "source_hash": page["text_hash"]} for s in near[:35]]
    if visual:
        from workspace.visual_analysis import interpret_element
        result["visual_analysis"]=interpret_element(doc,page,result,model=model)
    return result


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--plot":
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    data = json.loads(Path(sys.argv[2]).read_text())
    available = {f.name for f in font_manager.fontManager.ttflist}
    font = next((f for f in ("Noto Sans CJK SC", "Arial Unicode MS", "PingFang SC", "Heiti TC", "DejaVu Sans") if f in available), "DejaVu Sans")
    plt.rcParams.update({"font.family": font, "axes.unicode_minus": False, "svg.fonttype": "none", "font.size": 10})
    fig, ax = plt.subplots(figsize=(9, 5.5), layout="constrained")
    x = list(range(len(data["labels"]))); colors = ["#EF6F5C", "#222820", "#4C6D81", "#948559", "#697C68", "#956C82", "#566288", "#977969"]
    for i, series in enumerate(data["series"]):
        if data["type"] == "line": ax.plot(x, series["values"], label=series["name"], marker="o", color=colors[i], linewidth=1.7)
        else:
            width = .8 / len(data["series"])
            ax.bar([v - .4 + width * (i + .5) for v in x], series["values"], width=width, label=series["name"], color=colors[i])
    ax.set_xticks(x, data["labels"], rotation=30 if len(x) > 6 else 0); ax.set_xlabel(data["x_label"]); ax.set_ylabel(data["y_label"]); ax.set_title(data["title"], pad=18)
    ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="y", alpha=.2); ax.set_axisbelow(True); ax.legend(frameon=False)
    origin = {"reported": "Source-reported data", "researcher_data": "Researcher-supplied data", "derived": "Researcher-derived data"}[data["origin"]]
    source_titles = list(dict.fromkeys(s["title"] for s in data.get("_sources", [])))
    caption = origin + " | " + ("; ".join(source_titles[:2]) if source_titles else data.get("provenance_note", ""))[:180]
    fig.text(.01, .005, caption, fontsize=8)
    provenance = json.dumps({"origin": origin, "note": data.get("provenance_note", ""), "sources": data.get("_sources", [])}, ensure_ascii=False)
    fig.savefig(sys.argv[3], dpi=240, metadata={"Title": data["title"], "Description": provenance})
    plt.close(fig)
