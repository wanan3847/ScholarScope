import React, { useEffect, useState } from "react";
import { api } from "./api";

export default function ZoteroSync({ root, editable, onSaved }) {
  const [state, setState] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    library_type: "users",
    library_id: "",
    collection_key: "",
    api_key: "",
    allow_write: false,
  });
  const [attachments, setAttachments] = useState(false);
  useEffect(() => {
    let active = true;
    setState(null);
    setError("");
    setForm({
      library_type: "users",
      library_id: "",
      collection_key: "",
      api_key: "",
      allow_write: false,
    });
    if (editable)
      api(root + "/zotero")
        .then((data) => {
          if (!active) return;
          setState(data);
          if (data.configured)
            setForm({
              library_type: data.library_type,
              library_id: data.library_id,
              collection_key: data.collection_key,
              api_key: "",
              allow_write: data.allow_write,
            });
        })
        .catch((e) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [root, editable]);
  const run = async (fn) => {
    setBusy(true);
    setError("");
    try {
      setState(await fn());
      setForm((f) => ({ ...f, api_key: "" }));
      await onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const update = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  if (!editable)
    return (
      <div className="platform-empty">
        <h2>Zotero 文献同步</h2>
        <p>
          拥有者和编辑者可使用自己的账号配置同步。已导入的资料由项目成员共享。
        </p>
      </div>
    );
  return (
    <div className="zotero-workspace">
      <div className="module-heading">
        <div>
          <span className="workspace-label">连接你的文献库</span>
          <h2>Zotero 文献同步</h2>
          <p>
            导入库或集合的条目、标签和 PDF
            附件。两端同时修改时保留冲突，供你逐项核对。
          </p>
          <p>
            点击下方“获取库 ID 和密钥”，在 Zotero 官网登录自己的账号并创建专用
            API Key。个人库填写该页面显示的数字用户
            ID，再保存连接配置、增量导入到项目。导入需要文献库读取权限；PDF
            附件还需要文件读取权限。
          </p>
        </div>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <form
        className="template-form"
        onSubmit={(e) => {
          e.preventDefault();
          run(() => api(root + "/zotero", { method: "PUT", data: form }));
        }}
      >
        <label>
          库类型
          <select
            aria-label="库类型"
            value={form.library_type}
            onChange={(e) => update("library_type", e.target.value)}
          >
            <option value="users">个人库</option>
            <option value="groups">群组库</option>
          </select>
        </label>
        <label>
          数字库 ID
          <input
            required
            inputMode="numeric"
            value={form.library_id}
            onChange={(e) => update("library_id", e.target.value)}
          />
        </label>
        <label>
          集合键（可留空）
          <input
            maxLength={8}
            value={form.collection_key}
            onChange={(e) =>
              update("collection_key", e.target.value.toUpperCase())
            }
          />
        </label>
        <label>
          API Key
          <input
            type="password"
            autoComplete="new-password"
            required={!state?.configured}
            placeholder={
              state?.configured ? "已配置；留空保留" : "Zotero API Key"
            }
            value={form.api_key}
            onChange={(e) => update("api_key", e.target.value)}
          />
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={form.allow_write}
            onChange={(e) => update("allow_write", e.target.checked)}
          />
          允许此账号将项目元数据导出到该 Zotero 库
        </label>
        <div className="project-actions">
          <button className="secondary-button" disabled={busy}>
            保存连接配置
          </button>
          <a
            href="https://www.zotero.org/settings/keys"
            target="_blank"
            rel="noreferrer"
          >
            获取库 ID 和密钥
          </a>
        </div>
      </form>
      {state?.configured && (
        <>
          <div className="review-report">
            <h3>
              已保存 {state.library_type === "groups" ? "群组" : "个人"}库{" "}
              {state.library_id} 配置
            </h3>
            <p role="status">
              {state.connection_check
                ? state.connection_check.message
                : "尚未检查读取权限，保存配置后点击“检查连接”。"}
            </p>
            <p>
              已关联 {state.mapped_count || 0} 条文献 · 同步版本{" "}
              {state.version || 0}
              {state.pending ? " · 有待继续的分页" : ""}
            </p>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={attachments}
                onChange={(e) => setAttachments(e.target.checked)}
              />
              导入可下载的 PDF 附件（每个最多 25 MB）
            </label>
            <div className="project-actions">
              <button
                className="secondary-button"
                disabled={busy}
                onClick={() =>
                  run(() => api(root + "/zotero/check", { method: "POST" }))
                }
              >
                检查连接
              </button>
              <button
                className="primary-button"
                disabled={busy}
                onClick={() =>
                  run(() =>
                    api(root + "/zotero/sync", {
                      method: "POST",
                      data: { direction: "pull", attachments },
                    }),
                  )
                }
              >
                {busy ? "正在处理…" : "增量导入到项目"}
              </button>
              <button
                className="secondary-button"
                disabled={busy || !state.allow_write}
                onClick={() =>
                  run(() =>
                    api(root + "/zotero/sync", {
                      method: "POST",
                      data: { direction: "push" },
                    }),
                  )
                }
              >
                将项目文献导出到 Zotero
              </button>
              <button
                className="text-action"
                disabled={busy}
                onClick={() =>
                  run(() => api(root + "/zotero", { method: "DELETE" }))
                }
              >
                断开此账号连接
              </button>
            </div>
            <p className="muted">
              导出会新建或更新已关联条目的书目信息；远端版本变化时暂停覆盖。断开连接后，已导入的项目资料仍可阅读。
            </p>
          </div>
          {state.last_report && Object.keys(state.last_report).length > 0 && (
            <div className="review-report" role="status">
              <h3>最近同步记录</h3>
              <p>
                {state.last_report.complete
                  ? "本轮已完成"
                  : "本轮未全部完成，可继续同步"}{" "}
                · 导入 {state.last_report.imported} · 导出{" "}
                {state.last_report.exported} · PDF{" "}
                {state.last_report.attachments} · 未变更{" "}
                {state.last_report.unchanged}
              </p>
              {state.last_report.errors?.map((e, i) => (
                <p key={i}>
                  {e.key ? e.key + "：" : ""}
                  {e.message}
                </p>
              ))}
            </div>
          )}
          {state.conflicts?.map((c) => (
            <article className="review-report" key={c.key}>
              <h3>{c.title}</h3>
              <p>
                {c.reason} · Zotero 版本 {c.remote_version}
              </p>
              <details>
                <summary>查看远端元数据</summary>
                <p>{c.remote.abstract || "没有摘要"}</p>
                <p>
                  {c.remote.authors?.join("、")} ·{" "}
                  {c.remote.year || "年份未提供"}
                </p>
              </details>
              <div className="project-actions">
                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={() =>
                    run(() =>
                      api(root + "/zotero/conflicts/" + c.key, {
                        method: "POST",
                        data: { choice: "remote" },
                      }),
                    )
                  }
                >
                  采用 Zotero 元数据
                </button>
                <button
                  className="secondary-button"
                  disabled={busy || !state.allow_write}
                  onClick={() =>
                    run(() =>
                      api(root + "/zotero/conflicts/" + c.key, {
                        method: "POST",
                        data: { choice: "local" },
                      }),
                    )
                  }
                >
                  将本地修改写入 Zotero
                </button>
              </div>
            </article>
          ))}
        </>
      )}
    </div>
  );
}
