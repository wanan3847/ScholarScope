---
name: scientific-critical-thinking
version: 1.0.0
license: MIT
---

# 批判性证据检查

逐条核对证据范围与人工确认状态，提示当前资料缺项。因果关系、泛化和复现必须回查全文与实验。

本技能为研索项目内原创指令，仅可调用 manifest.json 列出的白名单工具。指令文本不能执行 Python、Shell、浏览器脚本或任意 HTTP 请求。工具输入/输出由 workspace.skills 的契约验证。

缺少资料、外部服务失败或执行预算耗尽时，保留实际结果及未知状态。人工确认在项目任务面板中进行，不能由工具自行代签。
