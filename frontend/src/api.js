export function stored(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}
export function persist(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {}
}
export function storedText(key) {
  try {
    return localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

export async function fetchDownload(path, name) {
  const token = storedText("sakura_token");
  const response = await fetch(path, { headers: token ? { Authorization: "Bearer " + token } : {} });
  if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.detail || "文件下载失败"); }
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function api(
  path,
  { method = "GET", data, params = {}, signal } = {},
) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([k, v]) => k !== "token" && v !== undefined && v !== null),
  );
  const res = await fetch(path + (query.size ? "?" + query : ""), {
    method,
    signal,
    headers: {
      ...(data ? { "Content-Type": "application/json" } : {}),
      ...((params.token || storedText("sakura_token")) ? { Authorization: "Bearer " + (params.token || storedText("sakura_token")) } : {}),
    },
    body: data ? JSON.stringify(data) : undefined,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || body.status === "error")
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : body.error || `请求失败 (${res.status})`,
    );
  return body;
}
export const paperId = (p) =>
  p.paper_id || p.arxiv_id || p.doi || p.id || p.title;
export const safeUrl = (url) =>
  /^https?:\/\//i.test(url || "") ? url : undefined;
export const paperUrl = (p) =>
  safeUrl(p.url) ||
  (p.doi
    ? "https://doi.org/" + encodeURI(p.doi)
    : p.arxiv_id
      ? "https://arxiv.org/abs/" + encodeURIComponent(p.arxiv_id)
      : undefined);
export function citation(p) {
  const clean = (s) =>
    String(s ?? "")
      .replace(/[{}]/g, "")
      .replace(/[\r\n]/g, " ");
  const key =
    clean(p.authors?.[0]?.split(" ").at(-1) || "paper").replace(
      /[^a-z\d]/gi,
      "",
    ) +
    (p.year || "") +
    clean(p.title?.split(" ")[0] || "reference").replace(/[^a-z\d]/gi, "");
  const fields = {
    title: p.title,
    author: (p.authors || []).join(" and "),
    year: p.year,
    journal: p.venue,
    doi: p.doi,
    url: paperUrl(p),
    abstract: p.abstract,
  };
  return (
    "@article{" +
    (key || "reference") +
    ",\n" +
    Object.entries(fields)
      .filter(([, v]) => v)
      .map(([k, v]) => "  " + k + " = {" + clean(v) + "}")
      .join(",\n") +
    "\n}"
  );
}
export function download(name, text, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function csv(papers) {
  const keys = ["title", "authors", "year", "venue", "doi", "url", "abstract"];
  const quote = (v) => '"' + String(v ?? "").replace(/"/g, '""') + '"';
  return (
    "\ufeff" +
    keys.join(",") +
    "\n" +
    papers
      .map((p) =>
        keys
          .map((k) => quote(Array.isArray(p[k]) ? p[k].join("; ") : p[k]))
          .join(","),
      )
      .join("\n")
  );
}
export function ris(papers) {
  return papers
    .map((p) =>
      [
        "TY  - JOUR",
        "TI  - " + (p.title || ""),
        ...(p.authors || []).map((a) => "AU  - " + a),
        ...(p.year ? ["PY  - " + p.year] : []),
        ...(p.venue ? ["JO  - " + p.venue] : []),
        ...(p.doi ? ["DO  - " + p.doi] : []),
        ...(paperUrl(p) ? ["UR  - " + paperUrl(p)] : []),
        "ER  - ",
      ].join("\n"),
    )
    .join("\n\n");
}
