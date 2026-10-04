# XS2 Novel Flywheel

`xs2-novel-flywheel` 基于 `bishu-novel` 的本地小说生产流程改造，保留原有建书、规划、写作、后验和润色链路，并新增用户可选择的参考资料蒸馏。它把长链路写作流程拆成
独立 Agent Node、确定性脚本和文件检查点，所有小说资料都保存在用户选择的本地
Workflow Workspace（工作流工作区）中。

## 发布内容

| 本地 Workflow ID | 用途 |
|---|---|
| `reference-distillation` | 分窗分析参考资料，生成待选择的抽象叙事机制 |
| `build` | 构建世界观的六个核心维度 |
| `character` | 生成角色骨架、信念、深层维度和声音 |
| `story-plan` | 生成故事规划与风格档案 |
| `outline` | 生成卷纲和近纲 |
| `mvp` | 生产章节正文，支持单写手或多写手组合 |
| `post-hoc` | 根据成稿更新世界、角色、伏笔和叙事债务 |
| `polish` | 自审、人文化处理和专业润色 |

包内还包括：

- 34 个生产 Agent/Prompt，以及 Workflow 需要的 Script Library；
- `writing-assistant` Skill，让 Main 同时作为用户的写作助手和写作工作流主管；
- `world/`、`meta/`、`outline/`、`story/`、`archive/` 与 `cache/` 组成的本地存档；
- 工作区内的文件完整性检查、JSON 索引和 Markdown 渲染。

## 运行要求

- DeterminFlow Core `v0.1.0` 或兼容版本
- Core `main` Agent 使用的默认模型和凭据需要完成配置

安装后不需要数据库、迁移、API、HMAC Key 或 UUID。运行每条 Workflow 时，为同一本书
填写相同的 `workspace_override`，例如 `data/books/my-novel`。书籍目录名由用户自行决定，
无需注册或生成 ID。

建议依次运行：`build` → `character` → `story-plan` → `outline` → `mvp` →
可选 `polish` → `post-hoc`。每条流程会直接复用同一工作区中的已有文件；进入下一章前
应完成当前章的 `post-hoc`，让后续章节读取已更新的连续性状态。

通过 Chat Main 使用时，安装后的 `xs2-novel-flywheel-writing-assistant` Skill 默认启用并自动
注入 Main，会维护书籍上下文、选择下一条 Workflow、解释创作参数并监督落盘结果。用户仍可
在 Skill 页面关闭自动注入。同一 Main 会话创建不同 Task 时应使用相同的 `named_shared`
工作区名称；需要跨 Main 会话继续时，当前 Chat 工具不能仅凭同名 `workspace_ref` 重新连接
旧目录，应继续原会话，或通过 Web/API 使用固定的 `workspace_override`。

插件内的 Agent Definition（智能体定义）不固定模型，所有 Agent Node 默认继承 Core
`agents_config.json` 中 `main.model` 指向的模型。切换 Core 默认模型即可统一切换整套
工作流使用的模型，无需修改插件资源。

## 文档

- [Workflow 与资源](docs/workflows.md)
- [本地存档结构](docs/local-archive.md)
- [写作助手 Skill](resources/skill-bundles/writing-assistant/SKILL.md)

## License

XS2 Novel Flywheel 使用 [GNU AGPL v3](LICENSE)（`AGPL-3.0-only`）许可证。
## 参考资料蒸馏

运行 `reference-distillation` 后，脚本会把 UTF-8 TXT 按句子边界拆成窗口；每个窗口由 Agent 提取候选机制，再由本地脚本校验证据位置、来源哈希和输出结构。结果写入 `learning/candidates.json`，并生成 `learning/selection.html`。候选默认不会进入正文流程。

用户把下载的选择结果保存为 `learning/selection.json`，内容必须带有候选集哈希和 `selected_candidate_ids`。再次运行脚本的 `adopt` 命令会创建不可覆盖的 `learning/blueprints/vNNNN.json`，并生成 `learning/active_context.md`。`story-plan`、`outline`、`mvp`、`polish` 和 `post-hoc` 会读取这个文件；没有采用任何机制时，这些流程照常运行。

生成流程只收到抽象机制、迁移建议和使用边界。参考资料正文、标题、人物、具体事件和原句不会进入创作上下文。

