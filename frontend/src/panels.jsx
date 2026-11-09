import React, { useState, useEffect, useRef } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import * as Tabs from "@radix-ui/react-tabs";
import {
  X,
  ArrowUpRight,
  Plus,
  Trash,
  UploadSimple,
  FileText,
  Check,
  SignOut,
  FolderSimple,
  FloppyDisk,
  WarningCircle,
} from "@phosphor-icons/react";
import { useApp } from "./context";
import { api, storedText } from "./api";

export function AppDialogs() {
  const { dialog, setDialog } = useApp();
  const names = {
    auth: "账号",
    model: "检索模型",
    settings: "设置",
    docs: "使用指南",
    import: "导入文献",
    folder: "新建课题文件夹",
    folders: "管理文件夹",
  };
  return (
    <Dialog.Root
      open={!!dialog}
      onOpenChange={(open) => !open && setDialog("")}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className={
            "dialog-content " +
            (["model", "settings", "docs"].includes(dialog)
              ? "dialog-wide"
              : "")
          }
          aria-describedby="dialog-description"
        >
          <div className="dialog-header">
            <div>
              <Dialog.Title>{names[dialog] || "研索"}</Dialog.Title>
              <Dialog.Description id="dialog-description">
                {dialog === "import"
                  ? "将已有的文献资料加入你的文献库。"
                  : dialog === "model"
                    ? "选择检索 Agent 使用的模型，或添加模型端点。"
                    : dialog === "auth"
                      ? "登录后按账号保存收藏、已阅和课题文件夹。"
                      : "管理研索工作台的资料与配置。"}
              </Dialog.Description>
            </div>
            <Dialog.Close className="plain-icon" aria-label="关闭面板">
              <X size={20} />
            </Dialog.Close>
          </div>
          <div className="dialog-body">
            {dialog === "auth" ? (
              <AuthPanel />
            ) : dialog === "model" ? (
              <ModelsPanel />
            ) : dialog === "settings" ? (
              <SettingsPanel />
            ) : dialog === "docs" ? (
              <DocsPanel />
            ) : dialog === "import" ? (
              <ImportPanel />
            ) : dialog === "folder" ? (
              <FolderPanel />
            ) : dialog === "folders" ? (
              <FoldersPanel />
            ) : null}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
function ErrorText({ error }) {
  return error ? (
    <p className="form-error" role="alert">
      <WarningCircle size={16} />
      {error}
    </p>
  ) : null;
}
function Field({ label, children, ...props }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children || <input {...props} />}
    </label>
  );
}
function useTask() {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function run(fn) {
    setBusy(true);
    setError("");
    try {
      return await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run, setError };
}
function AuthPanel() {
  const { user, token, setUser, setToken, setDialog, notify } = useApp();
  const [mode, setMode] = useState("login"),
    [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [old, setOld] = useState(""),
    [newPass, setNewPass] = useState("");
  const task = useTask();
  async function submit(e) {
    e.preventDefault();
    task.run(async () => {
      if (mode === "register")
        await api("/api/auth/register", {
          method: "POST",
          data: { username, password },
        });
      const d = await api("/api/auth/login", {
        method: "POST",
        data: { username, password },
      });
      setUser(d.username || username);
      setToken(d.token);
      localStorage.setItem("sakura_user", d.username || username);
      localStorage.setItem("sakura_token", d.token);
      notify("已登录 " + (d.username || username));
      setDialog("");
    });
  }
  async function logout() {
    task.run(async () => {
      await api("/api/auth/logout", { method: "POST", params: { token } });
      setUser("");
      setToken("");
      localStorage.removeItem("sakura_user");
      localStorage.removeItem("sakura_token");
      notify("已登出");
      setDialog("");
    });
  }
  if (user)
    return (
      <>
        <div className="account-summary">
          <div className="account-initial">
            {user.slice(0, 1).toUpperCase()}
          </div>
          <div>
            <strong>{user}</strong>
            <p>收藏与已阅由当前账号管理</p>
          </div>
        </div>
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault();
            task.run(async () => {
              await api("/api/auth/change-password", {
                method: "POST",
                data: { token, old_password: old, new_password: newPass },
              });
              setOld("");
              setNewPass("");
              notify("密码已修改");
            });
          }}
        >
          <h3>修改密码</h3>
          <Field
            label="当前密码"
            type="password"
            value={old}
            onChange={(e) => setOld(e.target.value)}
            autoComplete="current-password"
            required
          />
          <Field
            label="新密码"
            type="password"
            minLength={4}
            value={newPass}
            onChange={(e) => setNewPass(e.target.value)}
            autoComplete="new-password"
            required
          />
          <ErrorText error={task.error} />
          <button className="secondary-button" disabled={task.busy}>
            保存新密码
          </button>
        </form>
        <button className="logout-button" onClick={logout} disabled={task.busy}>
          <SignOut size={17} />
          退出登录
        </button>
      </>
    );
  return (
    <>
      <div className="segmented">
        <button
          className={mode === "login" ? "active" : ""}
          onClick={() => {
            setMode("login");
            task.setError("");
          }}
        >
          登录
        </button>
        <button
          className={mode === "register" ? "active" : ""}
          onClick={() => {
            setMode("register");
            task.setError("");
          }}
        >
          注册账号
        </button>
      </div>
      <form onSubmit={submit} className="form-stack">
        <Field
          label="用户名"
          id="login-username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
        />
        <Field
          label="密码"
          type="password"
          id="login-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={4}
          autoComplete={
            mode === "register" ? "new-password" : "current-password"
          }
          required
        />
        <ErrorText error={task.error} />
        <button
          className="primary-button"
          id="login-submit"
          disabled={task.busy}
        >
          {task.busy ? "正在提交" : mode === "login" ? "登录" : "注册并登录"}
          <ArrowUpRight size={17} />
        </button>
      </form>
    </>
  );
}
function ModelsPanel() {
  const { models, model, setModel, reloadModels, token, notify } = useApp();
  const [presets, setPresets] = useState([]),
    [preset, setPreset] = useState("deepseek"),
    [customModel, setCustomModel] = useState(false),
    [testResult, setTestResult] = useState("");
  const [form, setForm] = useState({
    name: "",
    model: "",
    base_url: "",
    api_key: "",
    priority: 30,
  });
  const task = useTask();
  useEffect(() => {
    api("/api/llm/presets")
      .then((d) => setPresets(d.presets || []))
      .catch((e) => task.setError(e.message));
  }, []);
  const update = (key, value) => setForm((s) => ({ ...s, [key]: value }));
  const selectedPreset = presets.find((p) => p.key === preset);
  const commonModels = selectedPreset?.models || [];
  const register = (custom) =>
    task.run(async () => {
      await api("/api/llm/" + (custom ? "register" : "register_preset"), {
        method: "POST",
        params: { token },
        data: custom
          ? { ...form, priority: Number(form.priority) }
          : {
              provider: preset,
              api_key: form.api_key,
              model: form.model,
              priority: Number(form.priority),
            },
      });
      await reloadModels();
      setForm({ ...form, api_key: "" });
      notify("模型配置已保存");
    });
  return (
    <>
      <Field label="本次检索使用的模型">
        <select
          id="llm-select"
          value={model}
          onChange={(e) => {
            setModel(e.target.value);
            localStorage.setItem("sakura_llm", e.target.value);
          }}
        >
          <option value="">自动选择</option>
          {models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name} · {m.model}
            </option>
          ))}
        </select>
      </Field>
      <div className="model-list">
        {models.length ? (
          models.map((m) => (
            <div key={m.name} className="model-row">
              <div>
                <strong>{m.name}</strong>
                <span>
                  {m.model} · 优先级 {m.priority}
                </span>
                <small>{m.base_url}</small>
              </div>
              <div>
                <button
                  className="secondary-button"
                  disabled={task.busy}
                  onClick={() =>
                    task.run(async () => {
                      const d = await api("/api/llm/test", {
                        method: "POST",
                        data: { name: m.name },
                      });
                      setTestResult(
                        d.status === "ok"
                          ? `${m.name}：${d.response}`
                          : d.error || "测试失败",
                      );
                    })
                  }
                >
                  测试
                </button>
                <button
                  className="plain-icon"
                  aria-label={"删除模型 " + m.name}
                  disabled={task.busy}
                  onClick={() =>
                    task.run(async () => {
                      await api(
                        "/api/llm/unregister/" + encodeURIComponent(m.name),
                        { method: "POST", params: { token } },
                      );
                      await reloadModels();
                      if (model === m.name) {
                        setModel("");
                        localStorage.removeItem("sakura_llm");
                      }
                      notify("模型已移除");
                    })
                  }
                >
                  <Trash size={17} />
                </button>
              </div>
            </div>
          ))
        ) : (
          <p className="panel-note">尚未配置模型，检索会使用文本匹配降级。</p>
        )}
      </div>
      {testResult && <p className="test-result">{testResult}</p>}
      <Tabs.Root defaultValue="preset" className="settings-tabs">
        <Tabs.List aria-label="添加模型">
          <Tabs.Trigger value="preset">预设提供商</Tabs.Trigger>
          <Tabs.Trigger value="custom">自定义端点</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="preset">
          <p className="panel-note">
            选择常用模型或填写模型
            ID，直接使用已有的模型接入服务。已添加的端点可在上方测试；项目功能自动使用优先级最高的可用端点。
          </p>
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              register(false);
            }}
          >
            <Field label="提供商">
              <select
                value={preset}
                onChange={(e) => {
                  setPreset(e.target.value);
                  setCustomModel(false);
                  setForm((s) => ({ ...s, model: "" }));
                }}
              >
                {presets.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.name || p.key}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="常用模型">
              <select
                value={
                  customModel ||
                  (form.model &&
                    !commonModels.some((m) => m.model === form.model))
                    ? "__custom__"
                    : form.model
                }
                onChange={(e) => {
                  setCustomModel(e.target.value === "__custom__");
                  update(
                    "model",
                    e.target.value === "__custom__" ? "" : e.target.value,
                  );
                }}
              >
                <option value="">
                  提供商默认 · {selectedPreset?.model || ""}
                </option>
                {commonModels.map((m) => (
                  <option key={m.model} value={m.model}>
                    {m.name || m.model} · {m.model}
                  </option>
                ))}
                <option value="__custom__">自定义模型 ID</option>
              </select>
            </Field>
            <Field
              label="模型 ID（可直接填写，留空使用默认）"
              value={form.model}
              onChange={(e) => {
                setCustomModel(true);
                update("model", e.target.value);
              }}
              placeholder={selectedPreset?.model || ""}
            />
            <Field
              label="API Key（已保存可留空保留；Ollama 无需填写）"
              type="password"
              autoComplete="off"
              value={form.api_key}
              onChange={(e) => update("api_key", e.target.value)}
            />
            <Field
              label="优先级（数字越大越优先）"
              type="number"
              value={form.priority}
              onChange={(e) => update("priority", e.target.value)}
              required
            />
            {preset === "ollama" && (
              <p className="panel-note">
                填写本机已安装的模型 ID；此处不会下载模型。
              </p>
            )}
            <button className="primary-button" disabled={task.busy}>
              添加模型
              <Plus size={17} />
            </button>
          </form>
        </Tabs.Content>
        <Tabs.Content value="custom">
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              register(true);
            }}
          >
            <div className="form-two">
              <Field
                label="端点名称"
                value={form.name}
                onChange={(e) => update("name", e.target.value)}
                required
              />
              <Field
                label="模型 ID"
                value={form.model}
                onChange={(e) => update("model", e.target.value)}
                required
              />
            </div>
            <Field
              label="API Base URL"
              type="url"
              value={form.base_url}
              onChange={(e) => update("base_url", e.target.value)}
              placeholder="http://localhost:11434/v1"
              required
            />
            <Field
              label="API Key"
              type="password"
              autoComplete="off"
              value={form.api_key}
              onChange={(e) => update("api_key", e.target.value)}
            />
            <Field
              label="优先级"
              type="number"
              value={form.priority}
              onChange={(e) => update("priority", e.target.value)}
            />
            <button className="primary-button" disabled={task.busy}>
              添加端点
              <Plus size={17} />
            </button>
          </form>
        </Tabs.Content>
      </Tabs.Root>
      <ErrorText error={task.error} />
      <p className="panel-note">模型配置和数据源密钥由管理员账号管理。</p>
    </>
  );
}
function SettingsPanel() {
  const {
    token,
    theme,
    setTheme,
    defaultFolder,
    setDefaultFolder,
    folders,
    uid,
    setDialog,
    notify,
  } = useApp();
  const [cfg, setCfg] = useState({
      openalex_key: "",
      openalex_email: "",
      s2_key: "",
      crossref_token: "",
      scopus_key: "",
      scopus_institution_token: "",
      unpaywall_email: "",
    }),
    [masked, setMasked] = useState({});
  const task = useTask();
  useEffect(() => {
    api("/api/settings/api", { params: { token } })
      .then((d) => {
        setMasked(d);
        setCfg((s) => ({
          ...s,
          openalex_email: d.openalex_email || "",
          unpaywall_email: d.unpaywall_email || "",
        }));
      })
      .catch((e) => task.setError(e.message));
  }, [token]);
  return (
    <>
      <section className="setting-block">
        <h3>工作台</h3>
        <Field label="外观">
          <select value={theme} onChange={(e) => setTheme(e.target.value)}>
            <option value="light">浅色</option>
            <option value="dark">深色</option>
          </select>
        </Field>
        <Field label="默认收藏文件夹">
          <select
            value={defaultFolder}
            onChange={(e) =>
              task.run(async () => {
                const fid = e.target.value;
                await api("/api/folders/default", {
                  method: "PUT",
                  params: { user_id: uid },
                  data: { folder_id: fid },
                });
                setDefaultFolder(fid);
                notify("默认文件夹已更新");
              })
            }
          >
            <option value="">未分类</option>
            {folders.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </Field>
        <button className="setting-link" onClick={() => setDialog("model")}>
          配置检索模型
          <ArrowUpRight size={17} />
        </button>
        <button className="setting-link" onClick={() => setDialog("folders")}>
          管理课题文件夹
          <ArrowUpRight size={17} />
        </button>
      </section>
      <section className="setting-block">
        <h3>检索数据源</h3>
        <p className="panel-note">
          留空保留已有密钥。填写邮箱用于 OpenAlex 请求身份。
        </p>
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault();
            task.run(async () => {
              await api("/api/settings/api", {
                method: "PUT",
                params: { token },
                data: {
                  openalex_email: cfg.openalex_email,
                  ...(cfg.openalex_key
                    ? { openalex_key: cfg.openalex_key }
                    : {}),
                  ...(cfg.s2_key ? { s2_key: cfg.s2_key } : {}),
                  unpaywall_email: cfg.unpaywall_email,
                  ...Object.fromEntries(
                    ["crossref_token", "scopus_key", "scopus_institution_token"]
                      .filter((k) => cfg[k])
                      .map((k) => [k, cfg[k]]),
                  ),
                },
              });
              setCfg((s) => ({
                ...s,
                openalex_key: "",
                s2_key: "",
                crossref_token: "",
                scopus_key: "",
                scopus_institution_token: "",
              }));
              notify("数据源配置已保存");
            });
          }}
        >
          <Field
            label="OpenAlex API Key"
            type="password"
            autoComplete="off"
            placeholder={masked.openalex_key ? "已配置密钥" : ""}
            value={cfg.openalex_key}
            onChange={(e) => setCfg({ ...cfg, openalex_key: e.target.value })}
          />
          <Field
            label="OpenAlex 联系邮箱"
            type="email"
            value={cfg.openalex_email}
            onChange={(e) => setCfg({ ...cfg, openalex_email: e.target.value })}
          />
          <Field
            label="Semantic Scholar API Key"
            type="password"
            autoComplete="off"
            placeholder={masked.s2_key ? "已配置密钥" : ""}
            value={cfg.s2_key}
            onChange={(e) => setCfg({ ...cfg, s2_key: e.target.value })}
          />
          {[
            ["crossref_token", "Crossref Plus Token（授权）"],
            ["scopus_key", "Scopus API Key（授权）"],
            ["scopus_institution_token", "Scopus 机构 Token（可选）"],
          ].map(([key, label]) => (
            <Field
              key={key}
              label={label}
              type="password"
              autoComplete="off"
              value={cfg[key]}
              placeholder={masked[key] ? "已配置密钥" : ""}
              onChange={(e) => setCfg({ ...cfg, [key]: e.target.value })}
            />
          ))}
          <Field
            label="开放全文查找邮箱（Unpaywall）"
            type="email"
            value={cfg.unpaywall_email}
            onChange={(e) =>
              setCfg({ ...cfg, unpaywall_email: e.target.value })
            }
          />
          <p className="muted">
            Europe PMC
            无需密钥；授权来源按已配置凭据使用，失败时保留其他来源。数据源配置由管理员保存。
          </p>
          <ErrorText error={task.error} />
          <button className="primary-button" disabled={task.busy}>
            保存配置
            <FloppyDisk size={17} />
          </button>
        </form>
      </section>
    </>
  );
}
function DocsPanel() {
  const { token, notify } = useApp();
  const [sections, setSections] = useState([]),
    [editable, setEditable] = useState(false),
    [editing, setEditing] = useState(false);
  const task = useTask();
  useEffect(() => {
    task.run(async () => {
      const d = await api("/api/docs", { params: { token } });
      setSections(d.sections || []);
      setEditable(d.can_edit);
    });
  }, [token]);
  return (
    <>
      <div className="docs-content" id="docs-body">
        {task.busy && (
          <p className="panel-note" role="status">
            正在加载使用指南...
          </p>
        )}
        {sections.map((s, i) => (
          <section key={i}>
            {editing ? (
              <>
                <Field
                  label="章节标题"
                  value={s.title}
                  onChange={(e) =>
                    setSections((prev) =>
                      prev.map((x, j) =>
                        i === j ? { ...x, title: e.target.value } : x,
                      ),
                    )
                  }
                />
                <Field label="章节内容">
                  <textarea
                    rows={4}
                    value={s.body}
                    onChange={(e) =>
                      setSections((prev) =>
                        prev.map((x, j) =>
                          i === j ? { ...x, body: e.target.value } : x,
                        ),
                      )
                    }
                  />
                </Field>
              </>
            ) : (
              <>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </>
            )}
          </section>
        ))}
      </div>
      <ErrorText error={task.error} />
      {editable && (
        <button
          className="secondary-button"
          disabled={task.busy}
          onClick={() =>
            editing
              ? task.run(async () => {
                  await api("/api/docs", {
                    method: "PUT",
                    params: { token },
                    data: { sections },
                  });
                  setEditing(false);
                  notify("使用指南已保存");
                })
              : setEditing(true)
          }
        >
          {editing ? "保存使用指南" : "编辑使用指南"}
        </button>
      )}
    </>
  );
}
function ImportPanel() {
  const { uid, reloadLibrary, setDialog, setView, notify } = useApp();
  const [items, setItems] = useState([]),
    [filename, setFilename] = useState(""),
    [text, setText] = useState("");
  const task = useTask();
  const input = useRef(null);
  const parse = async (content, name) =>
    task.run(async () => {
      const { parseImport } = await import("./import");
      const papers = parseImport(content, name);
      if (!papers.length)
        throw new Error("未识别到文献，请检查文件内容和格式。");
      setItems(papers);
      setFilename(name);
    });
  async function file(file) {
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) {
      task.setError("文件超过 20 MB，请分批导入。");
      return;
    }
    await parse(await file.text(), file.name);
  }
  return (
    <>
      <button
        className="import-drop"
        onClick={() => input.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          file(e.dataTransfer.files[0]);
        }}
      >
        <UploadSimple size={30} />
        <strong>选择或拖入文献文件</strong>
        <span>BibTeX、RIS、CSV、JSON、EndNote XML</span>
      </button>
      <input
        ref={input}
        type="file"
        className="visually-hidden"
        accept=".bib,.ris,.csv,.json,.xml"
        aria-label="选择文献文件"
        onChange={(e) => file(e.target.files[0])}
      />
      <details className="paste-import">
        <summary>粘贴文献内容</summary>
        <textarea
          aria-label="文献内容"
          rows={5}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="粘贴 BibTeX、RIS 或 JSON 文献内容"
        />
        <button
          className="secondary-button"
          disabled={task.busy}
          onClick={() => parse(text, "references.bib")}
        >
          解析内容
        </button>
      </details>
      <ErrorText error={task.error} />
      {items.length > 0 && (
        <div className="import-preview">
          <div>
            <FileText size={18} />
            <span>{filename}</span>
            <strong>{items.length} 篇</strong>
          </div>
          <ol>
            {items.slice(0, 4).map((p, i) => (
              <li key={i}>{p.title}</li>
            ))}
          </ol>
          <button
            className="primary-button"
            disabled={task.busy}
            onClick={() =>
              task.run(async () => {
                const d = await api("/api/favorites/import", {
                  method: "POST",
                  data: {
                    items,
                    source: filename.split(".").at(-1),
                    user_id: uid,
                  },
                });
                await reloadLibrary();
                setView("library");
                notify(`已导入 ${d.imported} 篇文献`);
                setDialog("");
              })
            }
          >
            {task.busy ? "正在导入" : "加入文献库"}
            <ArrowUpRight size={17} />
          </button>
        </div>
      )}
    </>
  );
}
function FolderPanel() {
  const { uid, reloadLibrary, setDialog, notify } = useApp();
  const [name, setName] = useState(""),
    [description, setDescription] = useState("");
  const task = useTask();
  return (
    <form
      className="form-stack"
      onSubmit={(e) => {
        e.preventDefault();
        task.run(async () => {
          await api("/api/folders", {
            method: "POST",
            params: { user_id: uid },
            data: { name, description },
          });
          await reloadLibrary();
          notify("课题文件夹已创建");
          setDialog("");
        });
      }}
    >
      <Field
        label="文件夹名称"
        value={name}
        onChange={(e) => setName(e.target.value)}
        required
        placeholder="例如：分子性质预测"
      />
      <Field label="课题说明（可选）">
        <textarea
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>
      <ErrorText error={task.error} />
      <button className="primary-button" disabled={task.busy}>
        创建文件夹
        <Plus size={17} />
      </button>
    </form>
  );
}
function FoldersPanel() {
  const { uid, folders, reloadLibrary, setDialog, notify, setFolder } =
    useApp();
  const task = useTask();
  const [editing, setEditing] = useState(""),
    [name, setName] = useState("");
  return (
    <>
      <div className="manage-folders">
        {folders.map((f) => (
          <div key={f.id}>
            <FolderSimple size={19} />
            {editing === f.id ? (
              <input
                aria-label="新的文件夹名称"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            ) : (
              <strong>{f.name}</strong>
            )}
            <button
              className="secondary-button"
              disabled={task.busy}
              onClick={() =>
                editing === f.id
                  ? task.run(async () => {
                      if (!name.trim()) throw new Error("文件夹名称不能为空");
                      await api("/api/folders/" + f.id, {
                        method: "PUT",
                        params: { user_id: uid },
                        data: { name },
                      });
                      await reloadLibrary();
                      setEditing("");
                      notify("文件夹已重命名");
                    })
                  : (setEditing(f.id), setName(f.name))
              }
            >
              {editing === f.id ? "保存" : "重命名"}
            </button>
            <button
              className="plain-icon"
              aria-label={"删除文件夹 " + f.name}
              disabled={task.busy}
              onClick={() =>
                task.run(async () => {
                  await api("/api/folders/" + f.id, {
                    method: "DELETE",
                    params: { user_id: uid },
                  });
                  setFolder("");
                  await reloadLibrary();
                  notify("文件夹已删除，文献保留在未分类中");
                })
              }
            >
              <Trash size={16} />
            </button>
          </div>
        ))}
      </div>
      <ErrorText error={task.error} />
      <button className="primary-button" onClick={() => setDialog("folder")}>
        新建文件夹
        <Plus size={17} />
      </button>
    </>
  );
}
