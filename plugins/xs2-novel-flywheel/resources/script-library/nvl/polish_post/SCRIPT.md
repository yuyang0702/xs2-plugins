# Polish Post

该脚本有两种互斥用法，均在校验成功后才替换目标文件。

自审后、润色前，校验并规范化供两名编辑读取的报告：

```text
--normalize-critique cache/sc/critique.json --source-chapter story/0001/chapter.md
```

保留 `feels_human`、`issues` 和旧问题描述。问题可附加 `scope`、`location`、`evidence`（正文原文摘录列表）、`impact`、`repair`；`major/moderate/minor` 兼容为 `high/medium/low`。只有中高影响问题的所有摘录均能在正文中找到、且附有具体影响说明时，才进入 `blocking_issues`（`issues` 数组中从零开始的索引）。这仅验证报告的引用依据，不能证明模型的文学判断正确。

旧格式或未核实的中高影响问题保留原文、等级及引用，以 `evidence_status=unverified` 和 `review_warnings` 标明，不能当成已确证问题直接改剧情。`review_status` 为 `revise`、`needs_review`、`pass_with_notes` 或 `pass`；有确证问题同时还有未核实问题时，状态仍为 `revise`，警告继续保留。只有低影响建议时 `feels_human=true`；未核实的重大疑问不会被自动改成通过。该字段表示编辑判断，不表示作者身份检测。

专业润色后，写入完整正文：

```text
--body-json cache/pp/body.json --output story/0001/chapter.md
```

输入必须是含非空字符串 `body` 的 JSON 对象。缺失、空白或非文本正文均报错，并保留原有章节。正常正文中的段落、引号和措辞原样保留，不执行词频或句法过滤。
