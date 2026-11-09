import { Cite } from "@citation-js/core";
import "@citation-js/plugin-bibtex";
import "@citation-js/plugin-ris";
function normalized(p) {
  return {
    id: String(
      p.paper_id ||
        p.arxiv_id ||
        p.doi ||
        p.DOI ||
        p.id ||
        p.key ||
        p.title ||
        "",
    ),
    title: p.title || "",
    authors: (Array.isArray(p.authors || p.author || p.creators)
      ? p.authors || p.author || p.creators
      : typeof p.authors === "string"
        ? p.authors.split(/;|\s+and\s+/)
        : []
    ).map((a) =>
      typeof a === "string"
        ? a
        : a.name ||
          [
            a.given || a.firstName || a.given_name,
            a.family || a.lastName || a.family_name,
          ]
            .filter(Boolean)
            .join(" "),
    ),
    year:
      parseInt(p.year || p.issued?.["date-parts"]?.[0]?.[0] || p.date) || null,
    venue:
      p.venue ||
      p["container-title"] ||
      p.publicationTitle ||
      p.bookTitle ||
      "",
    doi: p.doi || p.DOI || "",
    url: p.url || p.URL || "",
    abstract: p.abstract || p.abstractNote || "",
    tags: (Array.isArray(p.tags || p.keyword) ? p.tags || p.keyword : typeof (p.tags || p.keyword) === "string" ? (p.tags || p.keyword).split(/[;,；，]/) : []).map(t => typeof t === "string" ? t.trim() : t.tag || "").filter(Boolean),
  };
}
function parseCSV(text) {
  const rows = [];
  let row = [],
    value = "",
    quoted = false;
  for (let i = 0; i < text.length; i++) {
    let c = text[i];
    if (c === '"') {
      if (quoted && text[i + 1] === '"') {
        value += '"';
        i++;
      } else quoted = !quoted;
    } else if (c === "," && !quoted) {
      row.push(value);
      value = "";
    } else if ((c === "\n" || c === "\r") && !quoted) {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(value);
      if (row.some(Boolean)) rows.push(row);
      row = [];
      value = "";
    } else value += c;
  }
  row.push(value);
  if (row.some(Boolean)) rows.push(row);
  const heads = (rows.shift() || []).map((x) =>
    x
      .replace(/^\uFEFF/, "")
      .trim()
      .toLowerCase(),
  );
  return rows.map((r) => {
    const p = Object.fromEntries(heads.map((h, i) => [h, r[i] || ""]));
    p.authors = (p.authors || p.author || "")
      .split(/;|\s+and\s+/)
      .filter(Boolean);
    return normalized(p);
  });
}
export function parseImport(text, filename) {
  const ext = filename.split(".").at(-1).toLowerCase();
  let papers;
  if (ext === "csv") papers = parseCSV(text);
  else if (ext === "json" || /^[\s]*[\[{]/.test(text)) {
    const d = JSON.parse(text);
    papers = (
      Array.isArray(d) ? d : d.items || d.favorites || d.data || []
    ).map(normalized);
  } else if (ext === "xml") {
    const doc = new DOMParser().parseFromString(text, "text/xml");
    papers = [...doc.querySelectorAll("record")].map((r) =>
      normalized({
        title: r.querySelector("title")?.textContent,
        year: r.querySelector("year")?.textContent,
        doi: r.querySelector("electronic-resource-num")?.textContent,
        authors: [...r.querySelectorAll("author")].map((a) => a.textContent),
      }),
    );
  } else papers = new Cite(text).data.map(normalized);
  return papers.filter((p) => p.title || p.doi);
}
