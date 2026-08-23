# 2026-08-22 评测归档

| 文件 | 配置 | F1@10 | Recall@20 | P@10 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `real_scholar_50_qwen3.json` | 本地 qwen3:8b 全量 50 条（旧代码） | 0.0893 | 0.1217 | 0.1160 | 免费基线，0 失败，31/50 命中 |
| `real_scholar_20_deepseek.json` | DeepSeek 20 条（旧代码，全通道） | 0.0833 | 0.1050 | 0.1450 | 08:04 启动 |
| `real_scholar_20_qwen3_v2.json` | 本地 qwen3 20 条（三件套） | 0.1016 | 0.1286 | 0.1550 | 本地模式已回退精排/双规划 |
| `real_scholar_20_deepseek_v2.json` | DeepSeek 20 条（三件套） | **0.1055** | **0.1354** | **0.1550** | 当前最佳，+27% vs 旧代码 |

运行环境：2026-08-22，OpenAlex/S2 免费额度 08:00 重置后；v2 运行时段
匿名额度再次耗尽（候选池偏小，但 F1 仍提升，见评测记录 §3.1）。

命令示例（守护启动）：

```bash
cd /Users/yangyazhou/SakuraPaper
SPAR2_DEADLINE=170 /Users/yangyazhou/miniconda3/bin/python scripts/run_eval_daemon.py \
  --n 50 --benchmarks real_scholar --engine spar2 --real --llm deepseek \
  --output /Users/yangyazhou/SakuraPaper/results/2026-08-22/real_scholar_50_deepseek_v2.json \
  --log /tmp/real50_deepseek_v2.log
```
