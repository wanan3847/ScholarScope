"""结构化输出三件套生成器（JSON / Markdown 对比表 / HTML 关系图）。

为检索结果提供可读、可追溯的结构化展示。本模块从引擎结果中生成：

- `json`：论文列表 + 关系边（机器可读）
- `markdown_table`：排名对比表（人工可读）
- `graph_html`：关系图（自包含 SVG，离线可开）
- `cluster_summary`：按来源/主题聚类的归纳摘要
- `summary`：一句话归纳
"""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Sequence


_STOP = {
    "the", "a", "an", "of", "on", "in", "and", "or", "is", "are", "to", "for",
    "that", "this", "with", "from", "by", "at", "as", "was", "were", "be",
    "been", "has", "have", "had", "do", "does", "did", "which", "what", "how",
    "why", "who", "whose", "using", "used", "use", "papers", "paper", "works",
    "work", "studies", "study", "show", "showed", "explored", "explore",
    "within", "realm", "area", "related", "similar", "find", "give", "me",
    "can", "could", "would", "should", "their", "they", "them", "these",
    "those", "some", "many", "more", "most", "than", "into", "over", "under",
    "based", "using", "approach", "method", "results", "result", "new",
}


def _node_id(node: Any) -> str:
    """取节点稳定 ID：arxiv/doi/title 依次降级。"""
    for attr in ("arxiv_id", "doi", "s2_corpus_id", "title", "id"):
        if isinstance(node, dict):
            val = node.get(attr) or ""
        else:
            val = getattr(node, attr, "") or ""
        if val:
            return str(val)
    return "node"


def _node_title(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("title") or "")
    return str(getattr(node, "title", "") or "")


def _node_score(node: Any) -> float:
    if isinstance(node, dict):
        return float(node.get("final_score") or node.get("score") or 0.0)
    raw = getattr(node, "final_score", 0.0) or getattr(node, "score", 0.0) or 0.0
    return float(raw)


def _node_meta(node: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for attr in ("year", "venue", "source"):
        if isinstance(node, dict):
            val = node.get(attr)
        else:
            val = getattr(node, attr, None)
        if val:
            out[attr] = str(val)
    return out


def _node_authors(node: Any) -> List[str]:
    if isinstance(node, dict):
        return [str(a) for a in (node.get("authors") or [])]
    return [str(a) for a in (getattr(node, "authors", None) or [])]


def _node_text(node: Any) -> str:
    """标题 + 摘要拼接文本（用于相似度计算）。"""
    title = _node_title(node)
    abstract = ""
    if isinstance(node, dict):
        abstract = node.get("abstract") or ""
    else:
        abstract = getattr(node, "abstract", "") or ""
    return f"{title} {abstract}"


def records_to_nodes(records: Sequence[Dict]) -> List:
    """把 PaperRecord dict 列表转成 PaperNode 列表，并动态挂载 final_score。

    PaperNode 没有 final_score 字段（由 hidden_state_rerank 动态挂载），
    所以这里把 final_score 单独挂回节点对象上。
    """
    from data.paper_node import PaperNode
    nodes: List = []
    for r in records:
        node = PaperNode(
            title=r.get("title", ""),
            abstract=r.get("abstract", ""),
            arxiv_id=r.get("arxiv_id", ""),
            doi=r.get("doi", ""),
            year=r.get("year", 0),
            authors=r.get("authors", []),
            venue=r.get("venue", ""),
            url=r.get("url", ""),
            source=r.get("source", ""),
            select_score=r.get("select_score", 0.0),
            rerank_score=r.get("rerank_score", 0.0),
        )
        node.final_score = r.get("final_score", r.get("select_score", 0.0))  # type: ignore[attr-defined]
        nodes.append(node)
    return nodes


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(t) > 3 and t not in _STOP}


def similarity_edges(nodes: Sequence[Any], max_edges: int = 40,
                     threshold: float = 0.20) -> List[Dict[str, Any]]:
    """按标题+摘要 token 重合度生成 similar 关系边；同作者论文补 author 边。

    返回去重后的边列表，每条边含 src / dst / relation（similar|author）/ weight。
    """
    edges: List[Dict[str, Any]] = []
    n = len(nodes)
    for i in range(n):
        if len(edges) >= max_edges:
            break
        ti = _tokens(_node_text(nodes[i]))
        ai = set(_node_authors(nodes[i]))
        for j in range(i + 1, n):
            tj = _tokens(_node_text(nodes[j]))
            if not ti or not tj:
                continue
            inter = len(ti & tj)
            sim = inter / max(1, len(ti | tj))
            if sim >= threshold:
                edges.append({
                    "src": _node_id(nodes[i]),
                    "dst": _node_id(nodes[j]),
                    "relation": "similar",
                    "weight": round(sim, 3),
                })
            else:
                # 没有强词面重合但共享作者 → 补 author 边（星图不至于完全空白）
                aj = set(_node_authors(nodes[j]))
                if ai and ai & aj:
                    edges.append({
                        "src": _node_id(nodes[i]),
                        "dst": _node_id(nodes[j]),
                        "relation": "author",
                        "weight": 0.5,
                    })
            if len(edges) >= max_edges:
                break
    return edges


def make_markdown_table(nodes: Sequence[Any]) -> str:
    """排名对比表（Markdown）。"""
    rows = ["| # | Title | Score | Year | Source |", "|---:|------|------:|-----:|--------|"]
    for i, nd in enumerate(nodes[:20], 1):
        title = (_node_title(nd) or "")[:80].replace("|", "/")
        meta = _node_meta(nd)
        rows.append(f"| {i} | {title} | {_node_score(nd):.3f} | "
                    f"{meta.get('year', '-')} | {meta.get('source', '-')} |")
    return "\n".join(rows)


def make_comparison_table(nodes: Sequence[Any]) -> List[Dict[str, Any]]:
    """机器可读对比表（供前端/评测使用）。"""
    return [
        {
            "rank": i + 1,
            "title": _node_title(nd),
            "id": _node_id(nd),
            "score": round(_node_score(nd), 4),
            **_node_meta(nd),
        }
        for i, nd in enumerate(nodes[:20])
    ]


def make_cluster_summary(nodes: Sequence[Any]) -> Dict[str, Any]:
    """按来源/主题聚类归纳：每组返回代表标题与数量。"""
    clusters: Dict[str, List[str]] = {}
    for nd in nodes[:50]:
        meta = _node_meta(nd)
        key = meta.get("source") or meta.get("venue") or "other"
        clusters.setdefault(key, []).append(_node_title(nd))
    out = []
    for key, titles in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
        out.append({
            "group": key,
            "count": len(titles),
            "representatives": titles[:3],
        })
    return {"clusters": out, "total": len(nodes)}


def make_summary(query: str, nodes: Sequence[Any],
                 candidates: int = 0, judged: int = 0) -> str:
    """确定性一句话归纳（不编造，仅汇总已有数据）。"""
    n = len(nodes)
    high = sum(1 for nd in nodes if _node_score(nd) >= 0.7)
    partial = sum(1 for nd in nodes if 0.4 <= _node_score(nd) < 0.7)
    freq: Dict[str, int] = {}
    for nd in nodes[:20]:
        for w in _tokens(_node_title(nd)):
            freq[w] = freq.get(w, 0) + 1
    top_words = [w for w, c in sorted(freq.items(), key=lambda kv: -kv[1])[:6] if c >= 2]
    scope = "；".join(top_words) if top_words else query.strip()[:60]
    parts = [f"共整理 {n} 篇论文"]
    if high:
        parts.append(f"高度相关 {high} 篇")
    if partial:
        parts.append(f"部分相关 {partial} 篇")
    if candidates or judged:
        parts.append(f"候选 {candidates} / 判分 {judged}")
    return f"围绕「{query.strip()[:60]}」：{'，'.join(parts)}；主要覆盖主题：{scope}。"


def _get_edge_field(edge: Any, field: str) -> str:
    if isinstance(edge, dict):
        return str(edge.get(field) or "")
    return str(getattr(edge, field, "") or "")


def render_relation_graph_html(nodes: Sequence[Any], edges: Sequence[Any],
                               title: str = "Paper Relationship Graph") -> str:
    """自包含 SVG 关系图（离线可开，无需 CDN）。"""
    import math

    n = len(nodes)
    cx, cy, radius = 320, 240, 190
    positions: List[Dict[str, Any]] = []
    for i, nd in enumerate(nodes[:24]):
        if n <= 1:
            x, y = cx, cy
        else:
            ang = 2 * math.pi * i / min(n, 24)
            x = cx + radius * math.cos(ang)
            y = cy + radius * math.sin(ang)
        positions.append({"x": x, "y": y, "id": _node_id(nd),
                          "title": _node_title(nd), "score": _node_score(nd)})

    esc = html.escape
    edge_svg = ""
    for e in list(edges)[:40]:
        src = _get_edge_field(e, "src")
        dst = _get_edge_field(e, "dst")
        p1 = next((p for p in positions if p["id"] == src), None)
        p2 = next((p for p in positions if p["id"] == dst), None)
        if not p1 or not p2 or p1["id"] == p2["id"]:
            continue
        edge_svg += (f'<line x1="{p1["x"]:.1f}" y1="{p1["y"]:.1f}" '
                     f'x2="{p2["x"]:.1f}" y2="{p2["y"]:.1f}" '
                     'stroke="#B8B8B4" stroke-width="1" opacity="0.55"/>')

    node_svg = ""
    for p in positions:
        color = "#00D26A" if p["score"] >= 0.7 else "#D4A574" if p["score"] >= 0.4 else "#FFB7C5"
        r = max(8.0, min(22.0, 8 + p["score"] * 14))
        tip = esc((p["title"] or p["id"])[:60])
        node_svg += (f'<circle cx="{p["x"]:.1f}" cy="{p["y"]:.1f}" r="{r:.1f}" '
                     f'fill="{color}" fill-opacity="0.85" stroke="#0E0E0C" stroke-width="1">'
                     f'<title>{tip}</title></circle>')
        node_svg += (f'<text x="{p["x"]:.1f}" y="{p["y"] + r + 12:.1f}" '
                     'text-anchor="middle" font-size="9" fill="#0E0E0C">'
                     f'{tip[:28]}</text>')

    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>{esc(title)}</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#FAFAF7;color:#0E0E0C;margin:24px}}
h1{{font-size:18px;font-weight:600}} .legend span{{display:inline-block;width:12px;height:12px;border-radius:50%;margin:0 4px 0 14px;vertical-align:-1px}}</style>
</head><body>
<h1>{esc(title)}</h1>
<div class="legend"><span style="background:#00D26A"></span>高度相关
<span style="background:#D4A574"></span>部分相关
<span style="background:#FFB7C5"></span>低相关/候选</div>
<svg width="640" height="480" viewBox="0 0 640 480" xmlns="http://www.w3.org/2000/svg">
{edge_svg}
{node_svg}
</svg>
</body></html>"""


def generate_three_part_output(query: str, nodes: Sequence[Any],
                               edges: Sequence[Any] | None = None,
                               candidates: int = 0, judged: int = 0) -> Dict[str, Any]:
    """生成三件套：JSON / Markdown 对比表 / HTML 关系图 + 聚类摘要。"""
    edges = list(edges) if edges is not None else similarity_edges(nodes)
    json_part = {
        "query": query,
        "papers": [
            {
                "title": _node_title(nd),
                "id": _node_id(nd),
                "score": round(_node_score(nd), 4),
                **_node_meta(nd),
            }
            for nd in nodes
        ],
        "relationships": [
            {"src": _get_edge_field(e, "src"), "dst": _get_edge_field(e, "dst"),
             "relation": _get_edge_field(e, "relation") or "similar",
             "weight": float(_get_edge_field(e, "weight") or 1.0)}
            for e in edges
        ],
    }
    return {
        "json": json_part,
        "markdown_table": make_markdown_table(nodes),
        "comparison": make_comparison_table(nodes),
        "graph_html": render_relation_graph_html(nodes, edges, title=query),
        "cluster_summary": make_cluster_summary(nodes),
        "summary": make_summary(query, nodes, candidates=candidates, judged=judged),
        "relationships": json_part["relationships"],
    }
