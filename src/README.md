# 研索 ScholarScope 源码说明

> 面向复杂学术查询的智能论文检索与推荐系统 —— 源码目录。
> 使用入口、评测方法、项目结构见仓库根目录 [README](../README.md)。

## 目录结构

```
src/
├── web/                    # FastAPI Web 服务（主入口）
│   ├── app.py              # REST API（搜索/收藏/已阅/文件夹/认证/LLM 配置）
│   └── templates/app.html  # Web 前端界面
├── agent/                  # 核心逻辑
│   ├── orchestrator.py     # 顶层编排器
│   ├── spar2/              # SPAR2 引擎（engine/query_planner/judge/retrievers/expand/normalize）
│   ├── graph_synthesizer.py# 三件套输出（JSON / MD 表格 / HTML 关系图）
│   ├── feedback_loop.py    # 反馈闭环
│   └── collections.py      # 收藏夹 / 已阅 / 文件夹 / 用户认证
├── retrieval/              # 检索后端（arXiv/OpenAlex/CrossRef/S2/本地语义）
├── llm/                    # LLM 客户端（Mock/OpenAI 兼容/DeepSeek/Qwen/GLM）
├── evaluation/             # 评测（P@K / R@K / F1@K + Runner）
├── data/                   # 评测集、收藏/已阅/用户等运行时 JSON
├── prompts/                # LLM prompt 模板
├── tests/                  # 单元测试（32 个，全绿）；ad_hoc/ 为手动脚本
├── examples/               # 演示脚本
├── run_eval.py             # 官方测试集评测入口
└── pytest.ini              # 测试配置（ad_hoc 不参与收集）
```

## 常用命令（均在 src/ 下）

```bash
# 启动 Web
python3 -m uvicorn web.app:app --host 127.0.0.1 --port 8765

# 官方测试集评测（绝对路径输出最稳）
python3 run_eval.py --n 10 --benchmarks real_scholar --real --llm deepseek --output /绝对路径/结果.json

# 单元测试
python3 -m pytest tests/ -q
```

## 说明

- Web 搜索始终走真实 SPAR2 多通道检索；外部 API 额度耗尽时自动静默降级。
- 收藏/已阅等 ID 路由一律用 `{paper_id:path}`（DOI 带斜杠，普通路径参数会 404）。
- 收藏夹支持默认收藏文件夹（`/api/folders/default`）与按用户隔离的批量导入/导出。
- 当前文档见根目录 `docs/`（评测记录与岗位化改造方案）；旧比赛项目文档见 `archive/previous_competition/`。
