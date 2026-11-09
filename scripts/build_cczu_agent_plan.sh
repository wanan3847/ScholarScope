#!/usr/bin/env bash
# 生成常州大学首届智能体创新大赛提交材料（项目计划书 PDF / DOCX）。
# 用法（仓库根目录）：bash scripts/build_cczu_agent_plan.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/比赛材料/常州大学智能体大赛/源文件"
OUT="$ROOT/比赛材料/常州大学智能体大赛/提交材料"
NAME="研索ScholarScope项目计划书（智能体创新大赛）"

mkdir -p "$OUT"

pandoc "$SRC/项目计划书.md" \
  --resource-path="$SRC" \
  --toc --toc-depth=2 -V toc-title="目录" \
  -V geometry:margin=2.2cm -V fontsize=11pt -V documentclass=article \
  -V CJKmainfont="PingFang SC" -V mainfont="PingFang SC" -V monofont=Menlo \
  -V colorlinks=true -V linkcolor=black \
  -H "$SRC/latex-header.tex" \
  --pdf-engine=xelatex \
  -o "$OUT/$NAME.pdf"

# 可编辑副本；不参与提交
pandoc "$SRC/项目计划书.md" --resource-path="$SRC" -o "$SRC/项目计划书.docx"

cp "$SRC/作品原型与运行说明.md" "$SRC/演示视频分镜脚本.md" "$OUT/"

echo "已生成："
ls -lh "$OUT"
