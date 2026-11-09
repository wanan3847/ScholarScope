# 容器启动与恢复

验收日期：2026-10-14。使用入口为根 [README](../../README.md)。需要运行中的 Docker Engine、Docker Compose（支持 configs.content）及联网安装依赖；浏览器字体、编辑器、PDF.js 和脚本均在镜像内。

## 本地存储模式

从仓库根运行：

```bash
docker compose up -d --build
```

访问 `http://127.0.0.1:8765/app`。`research-data` 卷保留账号、项目、文件和集成配置。镜像以非 root 用户、只读根文件系统运行；临时目录为受限 tmpfs。默认是 SQLite、本地对象与关键词检索；需要语义模型时用 `INCLUDE_EMBEDDINGS=1` 构建、`SCHOLARSCOPE_DISABLE_EMBEDDINGS=0` 启用，并在 `/data/models` 准备已许可的多语言模型。`SCHOLARSCOPE_ALLOW_MODEL_DOWNLOAD=1` 可明确允许首次模型下载；读取失败仍退回关键词。

端口可通过 `SCHOLARSCOPE_PORT=8768 docker compose up -d` 修改。Web API 与任务监督进程在同一工作进程中启动，任务工具仍由有执行预算的独立子进程运行。

## PostgreSQL / pgvector / S3 模式

```bash
python3 scripts/create_storage_env.py .env.storage
docker compose --env-file .env.storage -f compose.yaml -f compose.storage.yaml up -d --build
```

配置生成器创建 0600 文件，拒绝覆盖，使用随机十六进制凭据且不打印值。PostgreSQL 与 S3 只在 Compose 私有网络内提供服务；应用启动时完成数据库/index schema 初始化，并在经过认证的 S3 中创建研究文件桶。账号配置、集成加密密钥留在 `research-data`，数据库与 S3 使用独立卷。外部 PostgreSQL/S3 的环境变量见根 README；服务、管理命令和工具子进程使用相同连接设置。

## 备份与空目标恢复

```bash
docker compose exec app python /app/scripts/workspace_admin.py backup /data/runtime/research-backup-2026-10-14.zip
```

备份实际数据库、对象文件、账号、配置及集成加密记录/密钥，权限 0600。备份文件可通过容器执行管道保存到操作员指定的私有文件；文件字节不应输出到终端。例：

```bash
umask 077
docker compose exec -T app python -c "import sys;sys.stdout.buffer.write(open('/data/runtime/research-backup-2026-10-14.zip','rb').read())" > research-backup-2026-10-14.zip
```

恢复使用新的 Compose 项目和空数据库/对象卷/运行目录，先把备份文件放入该容器，再执行：

```bash
docker compose -p research-restore exec app python /app/scripts/workspace_admin.py restore /tmp/restore.zip
```

恢复验证全部对象哈希以及集成密钥配对与解密，拒绝非空目标。原始 ID、成员、证据定位、已完成步骤和账号会话保持一致；运行中中断的任务保留为可恢复状态，不能冒称执行成功。已在确认阶段暂停的任务重启后仍等待确认。

## 实测

`src/tests/ad_hoc/workspace_container.py` 针对独立测试项目，完成真实账号/API、PDF 上传与私有读取、完整任务、确认阶段重启、实际 DOCX/12 页 PPTX、私有备份、恢复到新的容器及原会话读取。上述流程分别在 SQLite/本地文件及 PostgreSQL 17/pgvector 0.8.7/认证 S3 上通过；PostgreSQL 备份还恢复到 SQLite/本地文件。S3 无签名文件请求返回 403。

镜像构建和 npm 安全审计分别记录在总验收文件中。Zotero 个人库写入仍需要用户实际授权凭据；测试不创建默认假论文或配置固定管理员密码。


## 本机研究模型与扫描件（2026-10-14）

镜像包含 Poppler 与 Tesseract 英文/简体中文语言包，默认 `SCHOLARSCOPE_OCR_LANG=eng+chi_sim`；扫描件按页 OCR 有时间预算，失败页保留原图阅读。其他语言需先安装相应语言包，再指定环境变量。2026-10-14 的 OCR 镜像 `36921cf50465` 完成 108 项容器回归和实际中文扫描页解析，识别出“神经网络预测测井孔隙度，样本120个。”，置信度 92.9。该镜像验收早于随后研究标记校验的改动，部署当前代码仍需按上述命令重新构建。

容器模型设置连接 macOS 宿主机 Ollama 时填写 `http://host.docker.internal:11434/v1`；容器内 `127.0.0.1` 指向容器自身。模型凭据及配置不写入镜像，仍保存在私有运行卷。研究模型请求限制上下文及生成长度，并保留超时降级；视觉输出需人工核对。

本机模型默认使用 8K 上下文，同一服务进程串行推理并将排队计入预算，空闲约 90 秒后释放。可用 `SCHOLARSCOPE_RESEARCH_CONTEXT=8192` 限制研究请求的上下文（允许 2048–32768）；提高上下文会增加占用，需要按实际内存检查。16 GB 机器上的 9B 对比使用单独的内存压力保护验收，下载大小不等于运行占用，尚不能据下载成功认定可稳定运行。
