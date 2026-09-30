# Evaluation Reports

本目录保存虚构或公开研究任务的自动评测数据，不包含 API Key。

## 推荐阅读顺序

1. [`repeated/2026-09-29-200k/analysis.md`](repeated/2026-09-29-200k/analysis.md)：30 次真实端到端评测的结论、问题分析与指标边界。
2. [`repeated/2026-09-29-200k/summary.md`](repeated/2026-09-29-200k/summary.md)：面向阅读的汇总。
3. [`repeated/2026-09-29-200k/summary.json`](repeated/2026-09-29-200k/summary.json)：机器可读汇总。
4. [`research_questions.json`](research_questions.json)：12 条基础研究任务。
5. [`content_filter_questions.json`](content_filter_questions.json)：内容安全与异常恢复任务。

`2026-09-29/` 是 50k Token 上限下的中间实验，`2026-09-29-200k/` 是完成修复后的最终基线。

## 指标边界

- “通过”表示任务完成，并满足计划覆盖、引用编号有效、证据引用覆盖和异常恢复等自动门槛。
- 自动指标不等于独立人工评审后的答案正确率、来源权威性或引用语义支持率。
- 公开网页内容和模型服务会变化，重新运行不保证得到完全相同的数值。
