# XS2 Reference Distillation

该脚本只使用 Python 标准库，并以 Workflow Workspace 为当前目录。模型调用由 Agent Node 负责，脚本负责确定性分窗、哈希、证据校验、候选合并和蓝图落盘。

## 命令

- `split --input references/source.txt --window 4200 --overlap 400`：创建来源快照和窗口文件，并输出 `window_ids`。
- `normalize --input learning/cache/window-0001.raw.json --window-id window-0001`：校验模型结果。证据位置必须和来源快照的原文完全一致。
- `merge`：合并全部窗口的已校验候选，并生成本地选择页。
- `adopt --selection learning/selection.json`：只采用用户明确选择的候选，创建新的不可覆盖创作蓝图。
- `prepare-context --scope story-plan|outline|mvp|polish|post-hoc`：为指定流程生成上下文和读取回执。

脚本不会把来源原文写入 `learning/active_context.md`，也不会自动选中任何候选。
