# 项目 1：ScholarCopilot（TIGER-Lab，COLM 2025）

## 核心架构

ScholarCopilot 是一个面向**学术写作场景**的"检索-生成统一"系统。核心思路是用**同一个 7B LLM** 兼做"是否需要引文"决策器、引文检索向量查询器、续写生成器，避免传统 RAG 中"外挂 retriever + 生成器"的两段式延迟。系统在 5 个特殊 token 之上训练模型，让模型在生成时学会"在合适的位置主动停下来"→ 用最后一个 cite token 的 hidden state 去 HNSW 索引里做一次最近邻检索 → 把命中的论文 abstract 拼回去 → 继续生成。整体技术栈：PyTorch + HuggingFace Transformers + faiss (HNSW) + h5py + Gradio。

```
用户输入 LaTeX 文本 ──► 预处理(剥 \documentclass 等) ──► 加 <|paper_start|> 前缀
       │
       ▼
[单步生成 single_complete_step]  ←─── stop token: <|cite_start|>
       │  ├─ 命中 <|cite_start|>  → 取 hidden_states[-1][:,-1,:] 作为查询向量
       │  │      └─► faiss HNSW 检索 top-k 论文 abstract
       │  │           └─► llm_rerank 选 1 篇 → 拼 "<|reference_start|>abstract<|reference_end|>" 回去
       │  │                 └─► 再次调用 single_complete_step
       │  └─ 命中 <|paper_end|>  → 终止本轮
       ▼
post_process_output_text ──► 把 <|cite_start|><|cite_end|> 替换为 \cite{...}，合并相邻 \cite
       ▼
Gradio 流式 yield（每生成一词 yield 一次，按 "." 计数 3 句截断）
```

## 关键模块/类/函数

| 模块 | 路径 | 作用 |
|---|---|---|
| `load_model` | `run_demo/scholar_copilot_model.py` | 加载模型 + tokenizer + 6 个特殊 token |
| `single_complete_step` | 同上 | 单步续写：以 `<\|cite_start\|>` 为 eos，输出后取末位 hidden state |
| `retrieve_reference` | 同上 | 把 cite hidden state 做 L2 normalize → faiss.search → 返回 (corpus_id, score) |
| `llm_rerank` | 同上 | 在 top-k 候选中取第一名 abstract，包装为 `<\|reference_start\|>...<\|reference_end\|>` |
| `replace_citations` / `post_process_output_text` | 同上 | 把生成中的 cite 标记替换成 LaTeX `\cite{key}`，并合并相邻引用 |
| `stream_complete_3_sentence` / `stream_generate` | `run_demo/scholar_copilot_gradio.py` | Gradio 的流式生成器，按句号计数 3 句截断 |
| `search_and_show_citations` | 同上 | "随时查引用"按钮：手动加 `<\|cite_start\|>` → 取 hidden state → 检索 → 列候选 |
| `ArxivLLM.encode_query` | `train/src/arxivllm.py` | 训练时：在每个 query 中抽取所有 `<\|cite_start\|>` 位置的 hidden state，normalize，作为正负样本向量 |
| `ArxivLLM.encode_passage` | 同上 | 训练时：对 passage 取 EOS 位 hidden state，normalize |
| `TrainCollator` | `train/src/collator.py` | 构造 labels：`<\|cite_start\|>` 后到 `<\|cite_end\|>` 之间的 token label 置 -100（忽略损失） |
| `build_hnsw_index.py` | `utils/build_hnsw_index.py` | 把 h5 编码向量建 HNSW 索引（dim=3584, M=16, efC=1000, 内积） |
| `process_arxiv_meta_data.py` | `utils/process_arxiv_meta_data.py` | arXiv 元数据 → corpus jsonl（含 corpus_id/paper_id/title/abstract/bibtex/citation_key） |

## 特殊 Token 设计

完整定义（同时在 `load_model` 和 `train.py` 里注册）：
```
<|paper_start|>    <|paper_end|>        # 论文整体起止
<|cite_start|>     <|cite_end|>         # 引用占位起止（生成时被替换为 \cite{}）
<|reference_start|> <|reference_end|>   # 把检索到的 abstract 拼回去时的包裹符
```

**关键设计点**：
- `<|cite_start|>` 同时承担两个角色：① 作为 `eos_token_id` 让 `model.generate` 停下来；② 它的**末位 hidden state** 被复用为查询向量做 ANN 检索（这是论文最核心的 trick）。
- 训练 collator 把 `<|cite_start|>...<|cite_end|>` 区间内的 label 置 -100，避免模型去学习"复述 abstract 内容"，只学"何时停 + 检索什么"。

## Prompt 模板

输入侧模板（`template.txt`，启动 demo 默认加载）：
```
Title: [PUT YOUR TITLE HERE]

Abstract: [PUT YOUR ABSTRACT HERE]

Introduction:
[WRITE HERE]
```

`preprocess_input_text` 会先剥掉 `\documentclass`、`\usepackage`、`\begin{document}` 等 LaTeX 控制头，然后包成：
```
<|paper_start|> Title: ... \n\nAbstract: ... \n\nIntroduction: ... 
```
（demo 流程里输入文本会被 user 直接在 UI 里编辑，运行时同样经过这个包前缀操作。）

训练时 passage 端在 `process_arxiv_meta_data.py` 里包成：
```
<|reference_start|> {abstract} <|reference_end|>
```
query 端则把"当前写到第 N 句话 + 后面紧跟 `<|cite_start|>`"作为 query，正样本是该 cite 对应的 reference abstract，负样本是 in-batch 其他 reference。

## 关键算法/技巧

1. **"最后一 token 的 hidden state = 检索查询"**：`cite_start` 故意是生成 eos，模型学到"我决定要引文了"的那一瞬间的内部表征天然适合做查询向量，避免额外训练 dense retriever。
2. **HNSW + 内积 + L2 normalize**：因为向量已经 normalize，等价于 cosine 相似度；dim=3584 与 hidden_size 一致。
3. **"top-k 召回 + 取第 1 名"的 llm_rerank**（`llm_rerank` 函数）：检索 top-1 直接采纳，UI 的"查引用"按钮则返回 top-10 让用户勾选。
4. **对比学习 + 生成损失联合训练**：`compute_loss` = CE(scores/temperature, target) + 生成 LM loss；`temperature=0.01`（见 `start_train.sh`）让对比损失主导。
5. **隐藏区间 label mask**：`<|cite_start|>...<|cite_end|>` 内 label=-100，让模型只学"何时 cite / cite 谁"，不学"怎么复写 abstract"。
6. **HNSW 索引训练参数**：`M=16, efConstruction=1000`，单 GPU 编码（`encode.py` 不支持多卡），输出 `.h5` + `lookup_indices.npy`。
7. **DeepSpeed ZeRO-3** 训练：`ds_zero3_config.json` + `bf16` + `query_max_len=16384, passage_max_len=16384`（论文能塞 16K token 是因为用 abstract-级检索）。
8. **流式 UI**：Gradio `queue=True` + yield，按 `.` 计数 3 句截断，给作者"半句一回"的写作体验。

## 可复用的组件

- **统一 retriever/generator** 的"特殊 token + hidden state 检索"思路，可直接套到任意"写文档时插入参考资料"的场景（专利、法律意见书、技术博客等）。
- `ArxivLLM` 类（`encode_query` 用 cite-token 位取 hidden，passage 用 EOS 位取 hidden）是非常干净的 contrastive + LM 双任务训练范式。
- `TrainCollator` 那种"对特殊 token 区间做 label mask"的写法可以复用。
- `build_hnsw_index.py` 是独立的索引构建脚本，可以单独用。
- Gradio 流式 demo 框架（`stream_complete_3_sentence` + `replace_citations` + `merge_consecutive_citations`）是完整的"边写边引"前端模板。
- BibTeX 实时生成（`update_bibtex`）—— 按 citation_key 去重累加，可直接复用到任何 LaTeX 写作工具里。

## 性能数据/优势

- 论文："a unified 7B model for retrieval and generation"，3 大特性：Next-3-Sentence、On-demand Citation、Full-Section Auto-Complete。
- 训练规模：4 节点 × 8 GPU = 32 卡，`bf16`，`gradient_checkpointing`，`learning_rate=1e-5`，`temperature=0.01`。
- 检索 dim=3584（与 hidden_size 对齐），HNSW M=16 efC=1000，单轮 top-k=1（流式）或 top-10（按需检索）。
- 推理参数：`do_sample=True, top_p=0.95, temperature=0.6, max_new_tokens=4096`，超长上下文截断到 15000 tokens。
- 论文已被 COLM 2025 接收（arXiv:2504.00824）。
- 局限：当前版本只覆盖 introduction 和 related work，未来的 release 才支持 full-paper。
