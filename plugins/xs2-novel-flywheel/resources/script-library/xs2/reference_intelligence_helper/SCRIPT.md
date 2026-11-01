# Reference Intelligence Helper

参考辅助工作流入口。写作上下文沿用 `reference_distill` 的已采用蓝图校验与渲染，不会自动采用蒸馏候选。

## 功能

- `init`：报告候选可用状态，不修改采用状态；没有参考资料也是正常成功。
- `check-similarity --chapter 0001`：使用现有词面重合检测器对照 `learning/sources/*.txt` 快照。无快照时明确报告 skipped，不生成虚假的相似度。报告仅是词面重合提示，不是文学质量或抄袭判定。

## 用途

在 reference-distillation 和 mvp 中调用。智能上下文节点直接使用独立的 `reference_distill prepare-context --scope mvp`，读取已采用蓝图并写入 `learning/context/mvp.md`；没有已采用参考时按原创继续。当前脚本不依赖兄弟脚本目录。
