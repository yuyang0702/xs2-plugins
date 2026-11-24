# XS2 Reference Distillation

该脚本只使用 Python 标准库，并以 Workflow Workspace 为当前目录。模型调用由 Agent Node 负责，脚本负责确定性分窗、哈希、证据校验、候选合并和蓝图落盘。

## 命令

- `split --input references/source.txt --window 4200 --overlap 400`：创建来源快照和窗口文件，并输出 `window_ids`。
- `--source-mode auto` 识别带连续章号和独立完结标记的本地长篇，并优先采用与网页原文哈希匹配的导入记录。已确认完整的本地文本也可使用 `--source-mode serial_full`。章节样本使用 `serial_chapters`，短篇全文使用 `short_full`。
- `normalize --input learning/cache/window-0001.raw.json --window-id window-0001`：校验模型结果。证据位置必须和来源快照的原文完全一致。
- `merge`：合并全部窗口的已校验候选，并生成本地选择页。
- 正式全文流程使用 `--batch-max-chapters 10 --batch-max-chars 40000`。两项分别可调为 1～30 章与 800～60000 字符，先达到的限制决定何时开新批。超长章单独切分，每段保留原章身份和坐标。校验失败时只重交未通过的片段。
- `learning/cache/progress.json` 记录已读章节和批次进度。相同来源与参数重新运行 `split` 时复用原有校验回执。按章合批产生的章节事件和线索位于已校验窗口的 `chapter_readings` 中。短篇全文和长篇章节样本继续使用原窗口设置。
- `cross-prepare` 从原文检索首轮线索的候选命中。模型回查选中的焦点章与候选片段，`cross-validate --batch-id <批次编号>` 重新打开来源快照核对引用。`cross-finalize` 分别记录首轮章节覆盖和重点回查，并汇总观察、跨章判断及阶段节奏，供 Writing DNA 使用。
- `adopt --selection learning/selection.json`：只采用用户明确选择的候选，创建新的不可覆盖创作蓝图。
- `prepare-context --scope story-plan|outline|mvp|polish|post-hoc`：为指定流程生成上下文和读取回执。

脚本不会把来源原文写入 `learning/active_context.md`，也不会自动选中任何候选。
