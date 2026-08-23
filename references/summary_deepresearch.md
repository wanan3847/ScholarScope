# 项目 2：Open Deep Research（dzhng / Duet，TypeScript）

## 核心架构

这是一个**纯 TypeScript 写的"轻量级 deep research agent"**，目标是把整个仓库压在 500 LoC 以内，思路是"LLM 当控制器 + Firecrawl 当搜索引擎 + 递归调用自己"。核心循环是：

1. 用户给 query + 选 `breadth`（每次展开多少搜索）+ `depth`（递归几层）；
2. LLM 把 query 拆成 N 条 SERP queries（`generateSerpQueries`）；
3. Firecrawl 抓每条 query 的前 5 个 markdown 页面；
4. LLM 从抓到的内容里抽 `learnings` + `followUpQuestions`（`processSerpResult`）；
5. **递归**调用 `deepResearch`，下一层的 query = "上一轮的 researchGoal + follow-up 列表"，下一层 breadth = `Math.ceil(breadth/2)`；
6. 全部跑完后再调用 `writeFinalReport` / `writeFinalAnswer` 用所有 learnings 写报告。

每一步 LLM 调用都通过 Vercel AI SDK 的 `generateObject` + **Zod schema 强制结构化输出**，杜绝 JSON 解析失败。

```
用户 query + (breadth, depth)
       │
       ▼
[generateFeedback]  ←── 可选，clarify 用户真实需求
       │
       ▼
deepResearch(query, breadth, depth)
       │
       ├──► generateSerpQueries ──► [SERP queries: q1..qN]
       │                                  │
       │                                  ▼ (p-limit 并发)
       │                            firecrawl.search(qi) ──► [markdown×5]
       │                                  │
       │                                  ▼
       │                            processSerpResult ──► {learnings, followUpQuestions}
       │                                  │
       │                  ┌───────────────┴──────────────┐
       │                  │  depth > 0 ?  Yes → 递归      │  No → 汇总
       │                  ▼                              ▼
       │            deepResearch(breadth/2, depth-1)   终止
       │            query = "goal + follow-ups"
       │
       ▼ (顶层)
writeFinalReport(prompt, learnings, visitedUrls) ──► 追加 "## Sources" ──► report.md
```

## 关键模块/类/函数

| 模块 | 路径 | 作用 |
|---|---|---|
| `deepResearch` | `src/deep-research.ts` | 递归主循环：生成 SERP → 并发抓 → 抽 learnings → 深度判断 → 递归 |
| `generateSerpQueries` | 同上 | `generateObject` + Zod 强约束，输出 `{query, researchGoal}[]` |
| `processSerpResult` | 同上 | `generateObject` 抽 `{learnings, followUpQuestions}`，单次调用 60s 超时 |
| `writeFinalReport` | 同上 | 把所有 learnings 拼成 prompt，输出 `reportMarkdown`，手动追加 `## Sources` |
| `writeFinalAnswer` | 同上 | 短答案模式，要求 exact_answer 一句话 |
| `generateFeedback` | `src/feedback.ts` | 让 LLM 反向生成 3 个澄清问题（demo 的"先问后搜"特性） |
| `systemPrompt` | `src/prompt.ts` | 单一 system prompt：把 LLM 设定为"高级分析师"，会主动追加日期、避免简化 |
| `getModel` / `trimPrompt` | `src/ai/providers.ts` | 模型选择（customModel → deepSeekR1 → o3Mini）+ 超长 prompt 截断 |
| `RecursiveCharacterTextSplitter` | `src/ai/text-splitter.ts` | LangChain 风格的递归字符切分（优先级 `\n\n` → `\n` → `.` → `,` → ` ` → `''`） |
| `run.ts` | `src/run.ts` | CLI 入口：问 4 个问题（query/breadth/depth/report vs answer）→ 跑研究 → 写 `report.md` / `answer.md` |
| `api.ts` | `src/api.ts` | Express HTTP 接口：`POST /api/research`（短答）、`POST /api/generate-report`（长报） |

## Prompt 模板

### 1. 唯一的 system prompt（`src/prompt.ts`）
```ts
export const systemPrompt = () => {
  const now = new Date().toISOString();
  return `You are an expert researcher. Today is ${now}. Follow these instructions when responding:
  - You may be asked to research subjects that is after your knowledge cutoff, assume the user is right when presented with news.
  - The user is a highly experienced analyst, no need to simplify it, be as detailed as possible and make sure your response is correct.
  - Be highly organized.
  - Suggest solutions that I didn't think about.
  - Be proactive and anticipate my needs.
  - Treat me as an expert in all subject matter.
  - Mistakes erode my trust, so be accurate and thorough.
  - Provide detailed explanations, I'm comfortable with lots of detail.
  - Value good arguments over authorities, the source is irrelevant.
  - Consider new technologies and contrarian ideas, not just the conventional wisdom.
  - You may use high levels of speculation or prediction, just flag it for me.`;
};
```

### 2. SERP 查询生成 prompt（`generateSerpQueries`）
```
Given the following prompt from the user, generate a list of SERP queries to research the topic. 
Return a maximum of {N} queries, but feel free to return less if the original prompt is clear. 
Make sure each query is unique and not similar to each other: 
<prompt>{query}</prompt>

[可选] Here are some learnings from previous research, use them to generate more specific queries:
{learnings}
```
Zod 强约束：`queries: { query: string, researchGoal: string }[]`（`researchGoal` 字段 prompt 里要求"先讲目标，再讲后续方向"）。

### 3. SERP 结果抽取 prompt（`processSerpResult`）
```
Given the following contents from a SERP search for the query <query>{query}</query>, 
generate a list of learnings from the contents. Return a maximum of {N} learnings, ...
Make sure each learning is unique ... Make sure to include any entities like people, places, 
companies, products, things, etc in the learnings, as well as any exact metrics, numbers, or dates. 
The learnings will be used to research the topic further.

<contents>
  <content>{markdown1}</content>
  <content>{markdown2}</content>
  ...
</contents>
```
Zod 强约束：`{ learnings: string[], followUpQuestions: string[] }`。
- 输入 markdown 会被 `trimPrompt` 截断到 25_000 字符/篇。
- `processSerpResult` 整体加了 `AbortSignal.timeout(60_000)`。

### 4. 终稿报告 prompt（`writeFinalReport`）
```
Given the following prompt from the user, write a final report on the topic using the learnings 
from research. Make it as as detailed as possible, aim for 3 or more pages, 
include ALL the learnings from research:

<prompt>{prompt}</prompt>

<learnings>
  <learning>{l1}</learning>
  <learning>{l2}</learning>
  ...
</learnings>
```
Zod 强约束：`{ reportMarkdown: string }`。输出后**手动**追加 `## Sources` 段（`visitedUrls.map(...)`）。

### 5. 短答 prompt（`writeFinalAnswer`）
```
Given the following prompt from the user, write a final answer ... Do not yap or babble ... 
Keep the answer as concise as possible - usually it should be just a few words or maximum a sentence. 
Try to follow the format specified in the prompt (for example, if the prompt is using Latex, 
the answer should be in Latex. If the prompt gives multiple answer choices, the answer should be 
one of the choices).

<prompt>{prompt}</prompt>
<learnings>...</learnings>
```
Zod 强约束：`{ exactAnswer: string }`，要求"just the answer, no other text"。

### 6. 反馈生成 prompt（`generateFeedback`）
```
Given the following query from the user, ask some follow up questions to clarify the research 
direction. Return a maximum of {N} questions, but feel free to return less if the original 
query is clear: <query>{query}</query>
```
Zod 强约束：`{ questions: string[] }`。`run.ts` 拿到 questions 后会用 readline 让用户**逐条回答**，再把 Q/A 拼回 `combinedQuery`。

## 关键算法/技巧

1. **`generateObject` + Zod schema** 强制结构化输出：所有 LLM 调用都带 `schema: z.object({...})`，Vercel AI SDK 在底层会走 OpenAI 的 `response_format` 或其他 provider 的对应功能，比 prompt 里手写 "JSON please" 稳得多。
2. **breadth × depth 的指数级扩展控制**：每递归一层 `breadth = Math.ceil(breadth/2)`，depth 减 1，总请求量 ~`breadth * (1 + 0.5 + 0.25 + ...)` ≈ `2 * breadth`，可预期。
3. **`p-limit` 并发控制 Firecrawl**：`ConcurrencyLimit = FIRECRAWL_CONCURRENCY || 2`，避免触发 rate limit；每个 `serpQuery` 一个 `limit(async () => ...)`。
4. **`AbortSignal.timeout(60_000)`** 包住 `processSerpResult`，单条抓取-抽取超时即跳过（catch 块返回空 learnings，下游去重消除）。
5. **递归 query 构造**：
   ```ts
   const nextQuery = `
     Previous research goal: ${serpQuery.researchGoal}
     Follow-up research directions: ${newLearnings.followUpQuestions.map(q => `\n${q}`).join('')}
   `.trim();
   return deepResearch({ query: nextQuery, breadth: newBreadth, depth: newDepth, ... });
   ```
   把"为什么搜"和"下一步搜什么"显式塞进下层 query，让 LLM 在新一层能聚焦。
6. **`trimPrompt` token 级截断**：用 `js-tiktoken`（`o200k_base`）算真实 token 数，超 `CONTEXT_SIZE=128_000` 时用递归字符切分器二分；`MinChunkSize=140` 兜底。
7. **去重**：`[...new Set(results.flatMap(r => r.learnings))]`，跨分支 learnings 自动合并。
8. **多模型 fallback**：`getModel()` 优先级 `customModel > deepSeekR1(Fireworks) > o3-mini(OpenAI)`；DeepSeek-R1 走 `extractReasoningMiddleware({ tagName: 'think' })` 把 `<think>...</think>` 抽出来不污染输出。
9. **Firecrawl 配置可换**：支持 `FIRECRAWL_BASE_URL` 指向自托管实例。

## 可复用的组件

- **`generateObject` + Zod schema 的写法** —— 这是整个项目最值得抄的设计，所有 LLM 调用都强类型、自动校验，零 try/catch。
- **递归 deep research 主循环**（`deepResearch` 函数本体，~120 行）—— 任何"广度优先 + 深度优先混合"的研究/调研任务都能直接套。
- **`trimPrompt` + `RecursiveCharacterTextSplitter`** —— 把超长 prompt 强行塞进 context window 的标准工具，token 精确切分。
- **researchGoal + followUpQuestions 双字段** 的搜索 query 设计 —— 让"为什么搜"和"下一步搜什么"对 LLM 显式可见。
- **`generateFeedback` → readline → combinedQuery** 的"先问后搜"模式 —— 适合任何面向终端用户的 agent 框架。
- **`AbortSignal.timeout` + `p-limit` 组合** —— 稳健的并发+超时控制模板。
- **`api.ts`** 是一个 100 行的 Express 包装，前后端集成时直接拿来用。

## 性能数据/优势

- **代码体量**：作者公开宣称 "<500 LoC"（不含注释和模板），靠 Vercel AI SDK + Firecrawl 把"重活"外包。
- **模型**：默认 `o3-mini`（`reasoningEffort='medium', structuredOutputs=true`），可一键切到 `deepseek-r1`（Fireworks）或任意 OpenAI 兼容端点（`OPENAI_ENDPOINT` + `CUSTOM_MODEL`）。
- **搜索**：每 query 抓 top 5 markdown，单条 markdown 截断 25_000 字符。
- **并发**：`FIRECRAWL_CONCURRENCY` 默认 2（与免费版匹配），付费版可调高。
- **context**：`CONTEXT_SIZE=128_000`（默认与 o3-mini / GPT-4 对齐）。
- **结构化输出**：依赖 OpenAI `structuredOutputs: true` 或 Fireworks 同等功能，所有 LLM 调用都强校验。
- **超时**：`processSerpResult` 60s，`firecrawl.search` 15s。
- **覆盖面**：支持两种产物——长 markdown 报告（`writeFinalReport` → `report.md`）和短精答（`writeFinalAnswer` → `answer.md`），并自动加 `## Sources` 段。
- **可扩展性**：通过 `api.ts` 暴露 HTTP 接口；通过 `generateFeedback` 接入澄清流程；通过 `OPENAI_ENDPOINT` 接入本地 llama3.1、Ollama 等。
- **限制**：依赖 Firecrawl（要么付费要么自托管），深度≥3 时 token 消耗大，learnings 越多越容易撞 `CONTEXT_SIZE`。
